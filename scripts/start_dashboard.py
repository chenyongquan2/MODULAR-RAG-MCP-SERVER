"""Dashboard 启动脚本。

启动 Streamlit Dashboard 应用的入口脚本。

Usage:
    python scripts/start_dashboard.py
    streamlit run scripts/start_dashboard.py

Design Principles Applied:
- Simplicity: 单一职责，仅负责启动应用
- CLI-Friendly: 同时支持直接运行和 streamlit run 命令
"""

import subprocess
import sys
import io
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 设置标准输出编码为 UTF-8，支持 emoji 字符
stdout_encoding = (sys.stdout.encoding or "").lower()
stderr_encoding = (sys.stderr.encoding or "").lower()
if stdout_encoding != "utf-8" and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if stderr_encoding != "utf-8" and hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def main() -> None:
    """启动 Dashboard 应用。

    将请求转发到 Streamlit CLI，使用项目配置。
    """
    # 获取 app.py 的完整路径
    app_path = PROJECT_ROOT / "src" / "observability" / "dashboard" / "app.py"

    # 构造 streamlit 运行命令
    # 使用 -m streamlit 代替直接调用 streamlit，确保使用当前 Python 环境
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        # Streamlit 配置
        "--server.headless", "false",  # 显示浏览器
        "--server.port", "8501",  # 默认端口
        "--browser.gatherUsageStats", "false",  # 禁用使用统计
        "--logger.level", "info",  # 日志级别
    ]

    # 打印启动信息
    print("=" * 60)
    print("🎛️  Starting RAG Dashboard...")
    print("=" * 60)
    print(f"App path: {app_path}")
    print(f"Command: {' '.join(cmd)}")
    print("=" * 60)

    # 启动 Streamlit
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to start dashboard: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n👋 Dashboard stopped by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
