"""兼容性别名：脱敏批次服务的常见命名。

真实实现位于 ``app.services.reread``；这里仅按基准仓库的命名习惯再暴露
一份 ``MaskBatchService``，方便按模块名查找的调用方/测试导入。
"""
from __future__ import annotations

from app.services.reread import (  # noqa: F401
    RereadService as MaskBatchService,
    detect_watermark,
    reread_service as mask_batch_service,
    reread_service,
)

__all__ = ["MaskBatchService", "mask_batch_service", "reread_service", "detect_watermark"]
