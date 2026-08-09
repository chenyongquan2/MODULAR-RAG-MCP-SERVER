"""文本处理共享工具。

本包存放**查询端与索引端共用**的文本处理实现。放在 ``src/core/`` 而非
``src/libs/`` 是刻意的:``src/libs/<component>/`` 是 provider 实现的位置
(base + factory 模式),把非可插拔的工具模块放进去会误导后来者以为它是
可替换组件。
"""
