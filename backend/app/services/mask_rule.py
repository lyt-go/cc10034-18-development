"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.services.reread import reread_service


class MaskRuleService(BaseModuleService):
    MODULE = "mask_rule"
    ENTITY = "脱敏规则"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["规则编号", "目标字段", "脱敏算法", "保留位数", "掩码字符", "规则版本", "适用场景", "生效时间"]
    REQUIRED_FIELDS = ["规则编号", "目标字段", "脱敏算法"]
    STATUS_ORDER = ["草稿", "待验证", "已生效", "已废弃"]
    ACTION_RULES = {"提交验证": "待验证", "标记生效": "已生效", "标记废弃": "已废弃"}
    NEGATIVE_ACTIONS = []

    # ———————————— 脱敏批次 / 输出复读 / 交付闸门 ————————————
    # 真正的状态与不变量在 RereadService；这里保留按“脱敏规则服务”入口调用的习惯。

    def submit_batch(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        return reread_service.create_batch(values or {})

    create_batch = submit_batch  # 同义入口

    def list_batches(self, sample_code: str | None = None) -> list[dict[str, Any]]:
        return reread_service.list_batches(sample_code=sample_code)

    def run_reread(self, batch_id: int) -> tuple[dict[str, Any] | None, str]:
        return reread_service.run_reread(batch_id)

    reread_batch = run_reread  # 同义入口

    def delivery_gate(self, batch_id: int):
        return reread_service.delivery_gate(batch_id)
