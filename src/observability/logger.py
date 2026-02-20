"""结构化日志模块。

提供 get_logger 函数，输出到 stderr。后续阶段（F2）会扩展为 JSON Lines 格式。
"""

from __future__ import annotations

import logging
import sys


def get_logger(name: str) -> logging.Logger:
    """获取配置好的 Logger 实例。

    日志输出到 stderr，避免污染 stdout（MCP 协议要求 stdout 仅用于协议消息）。

    Args:
        name: Logger 名称，通常使用 ``__name__``。

    Returns:
        配置好的 Logger 实例。
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    return logger
