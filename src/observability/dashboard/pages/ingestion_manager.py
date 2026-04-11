"""Ingestion 管理页面 (Ingestion Manager Page).

提供文件上传、摄取触发、文档删除功能。

Features:
- 📤 文件上传：选择文件 + 集合选择
- 🚀 摄取触发：调用 IngestionPipeline 并显示实时进度条
- 🗑️ 文档删除：在文档列表中提供删除按钮
- 📊 进度追踪：实时显示摄取各阶段的进度状态

Design Principles Applied:
- User-Friendly: 清晰的 UI 布局，提供即时反馈
- Pluggable: 通过 IngestionPipeline 和 DocumentManager 访问，支持任意实现
- Fail-Safe: 处理错误时显示友好的错误信息
- Real-Time: 使用 Streamlit 的 progress 组件实现实时进度显示
"""

from __future__ import annotations

import streamlit as st
import tempfile
from pathlib import Path
from typing import Optional
from datetime import datetime

from src.core.settings import load_settings
from src.ingestion.pipeline import IngestionPipeline
from src.ingestion.document_manager import DocumentManager
from src.observability.dashboard.services.data_service import DataService
from src.observability.logger import get_logger

logger = get_logger(__name__)


def render() -> None:
    """渲染摄取管理页面。

    注意：页面配置在 app.py 中统一设置，此处不再调用 st.set_page_config()
    """
    st.title("📥 摄取管理")
    st.markdown("---")

    # 加载服务和配置（使用缓存避免重复初始化）
    @st.cache_resource
    def load_services():
        """加载所需服务和配置（缓存）。"""
        settings = load_settings()
        data_service = DataService(settings)
        return settings, data_service

    try:
        settings, data_service = load_services()
    except Exception as e:
        st.error(f"加载数据服务失败: {e}")
        logger.error("Failed to load services: %s", e)
        return

    # 创建两个标签页：上传摄取 和 文档管理
    tab1, tab2 = st.tabs(["📤 上传摄取", "🗑️ 文档管理"])

    with tab1:
        render_upload_section(settings, data_service)

    with tab2:
        render_document_management_section(data_service)


def render_upload_section(
    settings,
    data_service: DataService,
) -> None:
    """渲染上传摄取区域。

    Args:
        settings: 应用配置对象。
        data_service: 数据服务实例。
    """
    st.subheader("📤 上传文件并摄取")

    # 获取可用集合
    collections = data_service.get_collections()
    if not collections:
        st.warning("⚠️ 未找到任何集合，系统将使用默认配置的集合。")
        # 使用配置中的默认集合名
        default_collection = getattr(
            settings.vector_store,
            "collection_name",
            "knowledge_base",
        )
        collections = [default_collection]

    # 文件上传控件
    uploaded_file = st.file_uploader(
        "选择要摄取的文件",
        type=["pdf", "md", "markdown", "txt", "chm"],
        help="支持 PDF、Markdown、CHM 格式",
    )

    # 集合选择
    selected_collection = st.selectbox(
        "目标集合",
        options=collections,
        index=0,
        help="选择文件将被存储到哪个集合",
    )

    # 强制重新摄取选项
    force_reprocess = st.checkbox(
        "强制重新摄取",
        value=False,
        help="如果文件已被摄取过，勾选此项可强制重新处理",
    )

    # 上传并摄取按钮
    col1, col2 = st.columns([1, 5])
    with col1:
        process_button = st.button(
            "🚀 开始摄取",
            type="primary",
            disabled=uploaded_file is None,
        )

    with col2:
        if uploaded_file:
            st.info(f"已选择文件: `{uploaded_file.name}`")

    # 执行摄取
    if process_button and uploaded_file:
        process_ingestion(
            uploaded_file=uploaded_file,
            collection_name=selected_collection,
            force_reprocess=force_reprocess,
            settings=settings,
        )


def process_ingestion(
    uploaded_file,
    collection_name: str,
    force_reprocess: bool,
    settings,
) -> None:
    """执行摄取流程。

    Args:
        uploaded_file: 上传的文件对象。
        collection_name: 目标集合名称。
        force_reprocess: 是否强制重新摄取。
        settings: 应用配置对象。
    """
    # 创建状态容器用于存储进度信息
    status_container = st.container()

    with status_container:
        st.info(f"🔄 开始处理文件: `{uploaded_file.name}`")

    # 创建进度条和状态文本
    progress_bar = st.progress(0, text="准备中...")
    status_text = st.empty()

    # 保存上传的文件到临时目录
    with tempfile.NamedTemporaryFile(
        delete=False,
        suffix=f".{uploaded_file.name.split('.')[-1]}",
    ) as tmp_file:
        tmp_file.write(uploaded_file.getvalue())
        tmp_file_path = tmp_file.name

    try:
        # 创建 IngestionPipeline 实例
        pipeline = IngestionPipeline(
            settings=settings,
            collection=collection_name,
        )

        # 定义进度回调函数
        def on_progress(stage_name: str, current: int, total: int) -> None:
            """摄取进度回调函数。

            Args:
                stage_name: 当前阶段名称
                current: 当前进度（0 或 1）
                total: 总数（固定为 1）
            """
            # 更新状态文本
            status_messages = {
                "integrity": "完整性检查中...",
                "load": "加载文档中...",
                "split": "切分文档中...",
                "transform": "转换和增强中...",
                "encode": "向量化编码中...",
                "store": "存储到向量库中...",
            }

            message = status_messages.get(stage_name, f"{stage_name}...")
            status_text.text(f"📋 {message}")

            # 更新进度条（6 个阶段，每个阶段占 1/6）
            stages = ["integrity", "load", "split", "transform", "encode", "store"]
            if stage_name in stages:
                stage_index = stages.index(stage_name)
                progress = (stage_index + current) / len(stages)
                progress_bar.progress(
                    min(progress, 1.0),
                    text=message,
                )

        # 运行摄取管道
        result = pipeline.run(
            file_path=tmp_file_path,
            force=force_reprocess,
            on_progress=on_progress,
        )

        # 摄取完成
        progress_bar.progress(1.0, text="✅ 摄取完成！")

        # 显示结果摘要
        with status_container:
            if result.get("status") == "success":
                st.success("✅ 摄取成功！")

                # 显示处理统计
                stages_info = result.get("stages", {})
                col1, col2, col3, col4 = st.columns(4)

                with col1:
                    chunk_count = stages_info.get("store", {}).get("chunk_count", 0)
                    st.metric("Chunks", chunk_count)

                with col2:
                    image_count = stages_info.get("load", {}).get("image_count", 0)
                    if image_count > 0:
                        st.metric("图片", image_count)

                with col3:
                    text_length = stages_info.get("load", {}).get("text_length", 0)
                    size_kb = text_length / 1024
                    st.metric("文档大小", f"{size_kb:.1f} KB")

                with col4:
                    ingest_time = datetime.now().strftime("%H:%M:%S")
                    st.metric("完成时间", ingest_time)

                # 显示详细信息（可折叠）
                with st.expander("📋 查看详细信息", expanded=False):
                    st.json(result)

            elif result.get("status") == "skipped":
                st.warning("⚠️ 文件已被摄取过（使用 --force 可强制重新处理）")
                if "error" in result:
                    st.text(result["error"])
            else:
                st.error(f"❌ 摄取失败: {result.get('error', '未知错误')}")

    except FileNotFoundError:
        st.error("❌ 找不到上传的文件")
        logger.error("File not found: %s", tmp_file_path)
    except Exception as e:
        st.error(f"❌ 摄取过程出错: {e}")
        logger.error("Ingestion failed: %s", e, exc_info=True)
    finally:
        # 清理临时文件
        try:
            Path(tmp_file_path).unlink()
        except Exception as e:
            logger.warning("Failed to cleanup temp file: %s", e)


def render_document_management_section(data_service: DataService) -> None:
    """渲染文档管理区域。

    Args:
        data_service: 数据服务实例。
    """
    st.subheader("🗑️ 文档管理")

    # 获取文档列表
    try:
        docs = data_service.list_documents()

        if not docs:
            st.info("📭 暂无文档。请先上传并摄取文件。")
            return

        st.markdown(f"共 **{len(docs)}** 个文档")

        # 创建文档列表，每个文档包含删除按钮
        for doc in docs:
            with st.container():
                col1, col2, col3, col4 = st.columns([6, 2, 2, 2])

                with col1:
                    st.write(f"📄 `{doc.source_path}`")

                with col2:
                    st.write(f"Chunks: {doc.chunk_count}")

                with col3:
                    size_str = f"{doc.file_size / 1024:.1f} KB" if doc.file_size else "N/A"
                    st.write(f"大小: {size_str}")

                with col4:
                    delete_button_key = f"delete_{doc.doc_id[:16]}"
                    if st.button(
                        "🗑️ 删除",
                        key=delete_button_key,
                        type="secondary",
                    ):
                        handle_document_deletion(doc, data_service)

                st.divider()

    except Exception as e:
        st.error(f"❌ 加载文档列表失败: {e}")
        logger.error("Failed to load documents for management: %s", e)


def handle_document_deletion(doc, data_service: DataService) -> None:
    """处理文档删除。

    Args:
        doc: 要删除的文档信息。
        data_service: 数据服务实例。
    """
    # 在 session_state 中存储待删除的文档
    if "delete_doc_id" not in st.session_state:
        st.session_state.delete_doc_id = None
        st.session_state.delete_doc_data = None

    # 设置待删除文档
    st.session_state.delete_doc_id = doc.doc_id
    st.session_state.delete_doc_data = doc

    # 显示确认对话框
    st.warning(f"⚠️ 确定要删除文档 `{doc.source_path}` 吗？")
    st.caption(f"这将删除该文档的所有_chunks ({doc.chunk_count} 个) 和关联数据")

    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "确认删除",
            key=f"confirm_delete_{doc.doc_id[:16]}",
            type="primary",
        ):
            excute_delete_document(doc, data_service)

    with col2:
        if st.button(
            "取消",
            key=f"cancel_delete_{doc.doc_id[:16]}",
        ):
            # 清理待删除状态
            st.session_state.delete_doc_id = None
            st.session_state.delete_doc_data = None
            st.rerun()


def excute_delete_document(doc, data_service: DataService) -> None:
    """执行文档删除。

    Args:
        doc: 要删除的文档信息。
        data_service: 数据服务实例。
    """
    try:
        # 获取 DocumentManager 实例
        # 注意：Data Service 内部已经创建了 DocumentManager
        # 我们需要通过访问私有属性或添加公共方法来获取
        # 这里通过直接创建 DocumentManager 实例来处理

        from src.core.settings import load_settings
        from src.libs.vector_store.vector_store_factory import VectorStoreFactory
        from src.libs.loader.file_integrity import FileIntegrityChecker
        from src.ingestion.storage.bm25_indexer import BM25Indexer
        from src.ingestion.storage.image_storage import SQLiteImageStorage

        settings = load_settings()

        # 初始化各个组件
        vector_store = VectorStoreFactory.create(settings)
        file_integrity = FileIntegrityChecker()
        bm25_indexer = BM25Indexer()
        image_storage = SQLiteImageStorage()

        # 创建 DocumentManager
        doc_manager = DocumentManager(
            chroma_store=vector_store,
            bm25_indexer=bm25_indexer,
            image_storage=image_storage,
            file_integrity=file_integrity,
        )

        # 执行删除
        result = doc_manager.delete_document(
            source_path=doc.source_path,
            collection=doc.collection,
        )

        # 显示删除结果
        if result.success:
            st.success(
                f"✅ 文档删除成功！已删除 {result.chunks_deleted} 个 chunks"
                f" 和 {result.images_deleted} 张图片"
            )
            logger.info(
                "Deleted document %s: %d chunks, %d images",
                doc.source_path,
                result.chunks_deleted,
                result.images_deleted,
            )

            # 清理待删除状态并刷新页面
            st.session_state.delete_doc_id = None
            st.session_state.delete_doc_data = None
            st.rerun()
        else:
            st.error(f"❌ 删除失败: {result.error}")
            logger.error("Failed to delete document %s: %s", doc.source_path, result.error)

    except Exception as e:
        st.error(f"❌ 删除过程出错: {e}")
        logger.error("Delete operation failed: %s", e, exc_info=True)


if __name__ == "__page__":
    render()
elif __name__ == "__main__":
    render()