"""兼容性别名：复读回执服务的常见命名。"""
from __future__ import annotations

from app.services.reread import (  # noqa: F401
    RereadService as RereadReceiptService,
    reread_service as reread_receipt_service,
    reread_service,
)

__all__ = ["RereadReceiptService", "reread_receipt_service", "reread_service"]
