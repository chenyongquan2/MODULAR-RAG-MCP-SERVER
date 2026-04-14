# 依赖管理工作流（uv）

本文档用于约束本仓库统一的 Python 依赖管理方式，目标是：环境可复现、协作一致、问题可排查。

## 1. 基本原则

- 使用 `pyproject.toml` 作为依赖声明文件。
- 使用 `uv.lock` 作为锁定文件，确保不同机器安装结果一致。
- 使用 `uv` 作为唯一依赖入口，不混用 `pip install ...` 做日常依赖变更。

## 2. 首次初始化（Windows PowerShell）

```powershell
cd C:\workspace\MODULAR-RAG-MCP-SERVER
python -m pip install uv
uv venv .venv
.\.venv\Scripts\Activate.ps1
uv lock
uv sync --extra dev
```

## 3. 日常开发命令

```powershell
# 每次拉代码后先同步
.\.venv\Scripts\Activate.ps1
uv sync --extra dev

# 运行测试 / 脚本
uv run pytest tests/unit -v
uv run python scripts/ingest.py --path .\tests\fixtures\sample_documents --collection default
uv run python scripts/query.py --query "北极星是什么？" --top-k 5 --collection default
```

## 4. 依赖变更操作

```powershell
# 新增运行时依赖
uv add <package>

# 新增开发依赖
uv add --dev <package>

# 删除依赖
uv remove <package>

# 刷新锁文件并同步
uv lock --refresh
uv sync --extra dev
```

## 5. 提交前检查

- 如果改了依赖，确认 `pyproject.toml` 与 `uv.lock` 都已更新。
- 至少执行一次：

```powershell
uv run pytest tests/unit -v
```

## 6. 常见问题

### 6.1 `uv sync` 报文件被占用（Windows）

现象：`failed to remove file ... 拒绝访问 (os error 5)`。

处理步骤：
1. 停止占用 `.venv` 的进程（如 `python main.py`、编辑器 Python LSP）。
2. 重新执行 `uv sync --extra dev`。
3. 仍失败时，先用临时环境验证依赖可安装：

```powershell
uv venv .venv_new
$env:UV_PROJECT_ENVIRONMENT = ".venv_new"
uv sync --extra dev
Remove-Item Env:UV_PROJECT_ENVIRONMENT
```

### 6.2 网络不稳定导致下载超时

- 可临时切换镜像后重试（例如阿里云镜像）：

```powershell
$env:UV_INDEX_URL = "https://mirrors.aliyun.com/pypi/simple"
uv lock
uv sync --extra dev
Remove-Item Env:UV_INDEX_URL
```
