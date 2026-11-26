"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.services.reread import reread_service


class WatermarkService(BaseModuleService):
    MODULE = "watermark"
    ENTITY = "水印记录"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["水印编号", "目标数据集", "水印算法", "嵌入强度", "可检测性", "鲁棒性评分", "嵌入时间", "检测结果"]
    REQUIRED_FIELDS = ["水印编号", "目标数据集", "水印算法"]
    STATUS_ORDER = ["已嵌入", "已检测", "疑似泄露", "已溯源"]
    ACTION_RULES = {"发起检测": "已检测", "标记泄露": "疑似泄露", "标记溯源": "已溯源"}
    NEGATIVE_ACTIONS = []

    # ———————————— 复读回执与交付确认 ————————————

    def list_reread_receipts(self, sample_code: str | None = None,
                             batch_id: int | None = None) -> list[dict[str, Any]]:
        return reread_service.list_receipts(sample_code=sample_code, batch_id=batch_id)

    def delivery_overview(self) -> dict[str, Any]:
        return reread_service.state()

    def confirm_delivery(self, batch_id: int):
        return reread_service.delivery_gate(batch_id)
