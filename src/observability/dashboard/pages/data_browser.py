"""数据浏览器页面 (Data Browser Page).

展示文档列表、Chunk 详情、图片预览。

Features:
- 📄 文档列表视图：展示 source_path、集合、chunk 数、摄入时间
- 🔍 集合筛选：按集合名称过滤文档
- 📝 Chunk 详情视图：点击文档展开所有 chunk，显示内容（可折叠）、metadata 字段、关联图片
- 🖼️ 图片预览：查看文档中的提取图片

Design Principles Applied:
- User-Friendly: 清晰的 UI 布局，易于浏览和查看详细信息
- Pluggable: 通过 DataService 访问数据，支持任意存储后端
- Fail-Safe: 数据加载失败时显示友好的错误信息
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st
from typing import Any, Dict

from src.core.settings import load_settings
from src.observability.dashboard.services.data_service import (
    DataService,
    ChunkDisplay,
    ImageDisplay,
)
from src.observability.logger import get_logger

logger = get_logger(__name__)


def render() -> None:
    """渲染数据浏览器页面。"""
    st.set_page_config(
        page_title="数据浏览器",
        page_icon="📁",
        layout="wide",
    )

    st.title("📁 数据浏览器")
    st.markdown("---")

    # 加载 Data Service（使用缓存避免重复初始化）
    @st.cache_resource
    def load_data_service():
        """加载数据服务（缓存）。"""
        settings = load_settings()
        return DataService(settings)

    try:
        data_service = load_data_service()
    except Exception as e:
        st.error(f"加载数据服务失败: {e}")
        logger.error("Failed to load data service: %s", e)
        return

    # 侧边栏：集合筛选和搜索
    with st.sidebar:
        st.header("筛选与搜索")

        # 获取所有集合
        collections = data_service.get_collections()
        collection_options = ["全部"] + collections

        # 集合选择
        selected_collection = st.selectbox(
            "集合",
            options=collection_options,
            index=0,
        )

        # 搜索关键词
        search_keyword = st.text_input("搜索文档（文件名）", placeholder="输入关键词...")

        # 刷新按钮
        if st.button("刷新", key="refresh_docs"):
            st.rerun()

        # 统计信息
        st.markdown("---")
        st.markdown("### 统计信息")

        # 获取文档列表用于统计
        collection_filter = selected_collection if selected_collection != "全部" else None
        docs = data_service.list_documents(collection=collection_filter)

        st.metric("文档总数", len(docs))

        # 统计 chunks 数量
        total_chunks = sum(d.chunk_count for d in docs)
        st.metric("Chunk 总数", total_chunks)

        # 统计图片数量
        total_images = sum(d.image_count for d in docs)
        st.metric("图片总数", total_images)

    # 主区域：文档列表
    st.subheader("📄 文档列表")

    # 获取文档列表
    collection_filter = selected_collection if selected_collection != "全部" else None
    docs = data_service.list_documents(collection=collection_filter)

    # 应用搜索关键词过滤
    if search_keyword.strip():
        docs = [
            d for d in docs
            if search_keyword.lower() in d.source_path.lower()
        ]

    if not docs:
        st.info("📭 暂无文档数据。请先运行摄取脚本导入文档。")
        st.markdown("""
        **提示：**
        1. 使用 `python scripts/ingest.py --path <文件或目录>` 摄取文档
        2. 摄取完成后刷新此页面查看数据
        """)
        return

    # 展示文档列表
    st.markdown(f"共找到 **{len(docs)}** 个文档")

    # 创建文档列表（使用 expander 展示每个文档）
    for doc in docs:
        with st.expander(
            f"📄 {doc.source_path}",
            expanded=False,
        ):
            # 文档基本信息
            col1, col2, col3 = st.columns(3)
            with col1:
                st.write(f"**集合**: `{doc.collection}`")
            with col2:
                st.write(f"**Chunk 数**: {doc.chunk_count}")
            with col3:
                st.write(f"**图片数**: {doc.image_count}")

            col1, col2, col3 = st.columns(3)
            with col1:
                st.write(f"**类型**: `{doc.doc_type or 'N/A'}`")
            with col2:
                # 格式化文件大小
                size_str = f"{doc.file_size / 1024:.1f} KB" if doc.file_size else "N/A"
                st.write(f"**大小**: {size_str}")
            with col3:
                # 格式化摄入时间
                ingest_time = format_datetime(doc.ingested_at)
                st.write(f"**摄入时间**: {ingest_time}")

            st.markdown("---")

            # 操作按钮
            col1, col2 = st.columns(2)
            with col1:
                if st.button(
                    "🔍 查看 Chunks",
                    key=f"view_chunks_{doc.doc_id}",
                ):
                    st.session_state[f"show_chunks_{doc.doc_id}"] = True
            with col2:
                if st.button(
                    "🖼️ 查看图片",
                    key=f"view_images_{doc.doc_id}",
                ):
                    st.session_state[f"show_images_{doc.doc_id}"] = True

            # 显示 Chunk 详情（如果用户点击了查看按钮）
            if st.session_state.get(f"show_chunks_{doc.doc_id}", False):
                render_chunk_details(data_service, doc.doc_id)

            # 显示图片预览（如果用户点击了查看按钮）
            if st.session_state.get(f"show_images_{doc.doc_id}", False):
                render_image_preview(data_service, doc.doc_id)


def render_chunk_details(
    data_service: DataService,
    doc_id: str,
) -> None:
    """渲染 Chunk 详情。

    Args:
        data_service: 数据服务实例。
        doc_id: 文档 ID。
    """
    st.markdown("#### 📝 Chunk 详情")

    # 获取该文档的所有 Chunks
    chunks = data_service.get_chunks_by_doc_id(doc_id, include_images=True)

    if not chunks:
        st.info("⚠️ 该文档没有 Chunk 数据。")
        return

    st.markdown(f"共 **{len(chunks)}** 个 Chunk")

    # 展示每个 Chunk
    for i, chunk in enumerate(chunks, 1):
        chunk_header = f"Chunk {i}/{len(chunks)}: `{chunk.chunk_id[:16]}...`"
        with st.expander(chunk_header, expanded=(i == 1)):
            # Chunk 内容
            st.text_area(
                "内容",
                value=chunk.content,
                height=200,
                key=f"chunk_content_{chunk.chunk_id}",
                disabled=True,
            )

            # Metadata
            if chunk.metadata:
                with st.expander("📋 Metadata", expanded=False):
                    for key, value in chunk.metadata.items():
                        # 格式化 value（如果是字典则美化显示）
                        if isinstance(value, dict):
                            st.write(f"**{key}**:")
                            st.json(value)
                        else:
                            st.write(f"**{key}**: `{value}`")

            # 关联图片（如果有）
            if chunk.images:
                st.markdown(f"**关联图片** ({len(chunk.images)} 张)")
                for img in chunk.images:
                    st.caption(f"- `{img.get('image_id', 'N/A')}`")


def render_image_preview(
    data_service: DataService,
    doc_id: str,
) -> None:
    """渲染图片预览。

    Args:
        data_service: 数据服务实例。
        doc_id: 文档 ID。
    """
    st.markdown("#### 🖼️ 图片预览")

    # 获取该文档的所有图片
    images = data_service.get_document_images(doc_id)

    if not images:
        st.info("⚠️ 该文档没有图片。")
        return

    st.markdown(f"共 **{len(images)}** 张图片")

    # 使用网格布局展示图片（每行 3 张）
    cols = st.columns(3)
    for i, image in enumerate(images):
        with cols[i % 3]:
            st.caption(f"`{image.file_path}`")
            if image.page_num is not None:
                st.caption(f"📄 Page {image.page_num}")

            # 读取并显示图片
            image_path = data_service.get_image_path(image.image_id)
            if image_path and Path(image_path).exists():
                try:
                    st.image(image_path, use_container_width=True)
                except Exception as e:
                    st.error(f"无法加载图片: {e}")
                    logger.error("Failed to load image %s: %s", image_path, e)
            else:
                st.warning(f"图片文件不存在: {image_path}")


def format_datetime(dt_str: str) -> str:
    """格式化日期时间字符串。

    Args:
        dt_str: 日期时间字符串（ISO 8601 格式）。

    Returns:
        格式化的日期时间字符串。
    """
    try:
        dt = datetime.fromisoformat(dt_str)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        # 如果解析失败，返回原字符串
        return dt_str


if __name__ == "__page__":
    render()
elif __name__ == "__main__":
    render()