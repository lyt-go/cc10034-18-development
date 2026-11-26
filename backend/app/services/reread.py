"""脱敏批次「复读」领域服务。

业务背景
--------
脱敏规则页完成一次处理（得到一个脱敏批次的确切输出）后，交付前还需要一步
「复读」：把这批输出样本原样交给服务端做水印检测，确认嵌入的水印仍然可辨认，
并生成绑定该批样本与处理版本的复读回执。水印页依据回执判断这一版能否正式交付。

核心不变量（也是 E2E 核对点）
----------------------------
1. 回执必须能识别 ``sample_code``（样本）、``version``（处理版本）和
   ``batch_id``（确切批次）；
2. 交付资格只认绑定到同一 ``batch_id`` 的通过回执——某一批通过不能替另一批解锁；
3. 检测针对提交时快照的 ``exact_output``（确切输出），样本随后被重处理
   （产生新批次/新版本）不会改写旧批次与旧回执；
4. 迟到的旧回执永远指向它自己的旧批次，页面据此说明「早先结果还能用于哪次交付」；
5. 没有可读水印（缺少水印必需字段）的批次不具备交付资格，交付下载在服务端同样被拦截。

本服务使用独立内存仓库，不写入通用 ``store`` 的 18 张模块表，避免改变
``/api/overview`` 的模块计数等既有契约。
"""
from __future__ import annotations

import csv
import io
import json
import re
import threading
from datetime import datetime
from typing import Any

# ———————————— 水印字段约定 ————————————

# 水印身份字段（说明这是哪一枚水印），存在与否只影响信息完整度。
WATERMARK_IDENTITY_KEYS = (
    "水印编号", "水印ID", "水印id", "水印标识",
    "watermark_id", "watermark_no", "watermark_code",
)

# 水印载体字段：输出里必须至少有一个字段携带非空、可辨认的水印标记，
# 否则服务端判定「没有可读水印」。
WATERMARK_MARKER_KEYS = (
    "水印标记", "水印签名", "水印内容", "水印码", "水印串", "水印值", "水印列",
    "watermark_token", "watermark_marker", "watermark_mark", "watermark_value",
    "watermark", "wm_token", "wm_mark", "wm_marker", "marker",
)

# 页面/接口统一展示的「水印必需字段」。去掉其中任意一个关键载体字段，
# 复读就会判定水印不可读。
WATERMARK_REQUIRED_FIELDS = ["水印编号", "水印标记"]

_MARKER_PATTERN = re.compile(r"(?:WM|WATE)[-_A-Z0-9]{3,}", re.IGNORECASE)
# 强水印令牌：至少两段（如 WM-WATE-0001-7F3A9C21），避免把样本编号
# SAMPLE-WM-001 这类普通业务串误判成水印。
_STRONG_MARKER_PATTERN = re.compile(r"WM-[A-Z0-9]{2,}(?:-[A-Z0-9]{3,}){1,}", re.IGNORECASE)
# 显式水印载体标签（纯文本/未走结构化解析的 CSV 场景）。
_LABELED_MARKER_PATTERN = re.compile(
    r"(?:水印标记|水印签名|水印内容|水印码|水印串|watermark(?:[_\-]?(?:token|marker|value|code))?)"
    r"\s*[:=：]\s*([A-Za-z0-9*#_\-.]{4,})",
    re.IGNORECASE,
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _norm_key(key: Any) -> str:
    if key is None:
        return ""
    return str(key).strip().casefold().replace("-", "_")


def _alias_match(key: str, aliases: tuple[str, ...]) -> bool:
    normalized = _norm_key(key)
    return any(normalized == _norm_key(alias) for alias in aliases)


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _find_marker(payload: Any) -> tuple[str, str] | None:
    """在任意 JSON 结构里递归寻找水印载体字段的非空值，返回 (字段路径, 值)。"""
    found: tuple[str, str] | None = None

    def walk(node: Any, path: str) -> None:
        nonlocal found
        if found is not None:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                child_path = f"{path}.{key}" if path else str(key)
                if _alias_match(key, WATERMARK_MARKER_KEYS) and not _is_blank(value):
                    found = (child_path, str(value).strip())
                    return
                walk(value, child_path)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]")

    walk(payload, "")
    return found


def _find_identity(payload: Any) -> str:
    identity = ""

    def walk(node: Any) -> None:
        nonlocal identity
        if identity:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if _alias_match(key, WATERMARK_IDENTITY_KEYS) and not _is_blank(value):
                    identity = str(value).strip()
                    return
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return identity


def _parse_output(raw: Any) -> tuple[Any, str, list[str]]:
    """把提交进来的确切输出归一化为 (结构化对象, 文本形态, 解析备注)。"""
    notes: list[str] = []
    if isinstance(raw, (dict, list)):
        try:
            text = json.dumps(raw, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            text = str(raw)
        return raw, text, notes
    if raw is None:
        return None, "", ["未提供输出内容"]

    text = str(raw)
    stripped = text.strip()
    if not stripped:
        return None, "", ["输出内容为空"]

    # 先尝试 JSON。
    if stripped[0] in "{[":
        try:
            parsed = json.loads(stripped)
            return parsed, json.dumps(parsed, ensure_ascii=False, indent=2), notes
        except (json.JSONDecodeError, ValueError):
            notes.append("输出不是合法 JSON，按纯文本检测")

    # 再尝试 CSV（带表头）。
    if "," in stripped.splitlines()[0] if stripped.splitlines() else False:
        try:
            reader = csv.DictReader(io.StringIO(stripped))
            rows = [dict(row) for row in reader]
            if rows:
                return rows, text, notes
        except csv.Error:
            pass

    return stripped, text, notes


def detect_watermark(raw_output: Any, expected_watermark_no: str | None = None) -> dict[str, Any]:
    """对一批次的确切输出执行服务端水印检测。

    该函数必须是纯函数式的：同样的 ``raw_output`` 永远得到同样的结论，
    这样交错返回两次真实复读结果时，批次与结论的对应关系只由批次身份决定。
    """
    payload, text, parse_notes = _parse_output(raw_output)
    marker_hit = _find_marker(payload) if payload is not None else None
    identity = _find_identity(payload) if payload is not None else ""
    if not identity and expected_watermark_no:
        identity = str(expected_watermark_no).strip()

    matched_fields: list[str] = []
    missing_fields: list[str] = []

    if marker_hit is not None:
        field_path, marker_value = marker_hit
        matched_fields.append(field_path)
        recognizable = bool(marker_value) and (
            len(marker_value) >= 3 or bool(_MARKER_PATTERN.search(marker_value))
        )
        if recognizable:
            if identity:
                matched_fields.insert(0, "水印编号")
            else:
                missing_fields.append("水印编号")
            confidence = 0.97 if _MARKER_PATTERN.search(marker_value) else 0.86
            return {
                "readable": True,
                "result": "通过",
                "detected": True,
                "confidence": confidence,
                "watermark_no": identity,
                "matched_fields": matched_fields,
                "missing_fields": missing_fields,
                "required_fields": list(WATERMARK_REQUIRED_FIELDS),
                "parse_notes": parse_notes,
                "message": (
                    f"复读通过：该批次确切输出中水印仍可辨认"
                    f"（命中载体字段 {field_path}，置信度 {confidence:.2f}）。"
                ),
            }

    # 结构化字段没找到时，再对文本做一次严格检测（CSV/纯文本场景）：
    # 只认带显式水印标签的值或多段强令牌，不能因样本编号里恰好含 “WM-001” 就误判。
    text = text or ""
    labeled = _LABELED_MARKER_PATTERN.search(text)
    strong = _STRONG_MARKER_PATTERN.search(text)
    text_token = ""
    text_field = ""
    if labeled and labeled.group(1):
        text_token = labeled.group(1)
        text_field = "文本中的水印标签"
    elif strong:
        text_token = strong.group(0)
        text_field = "文本中的水印令牌"
    if text_token:
        return {
            "readable": True,
            "result": "通过",
            "detected": True,
            "confidence": 0.8,
            "watermark_no": identity,
            "matched_fields": [text_field],
            "missing_fields": [] if identity else ["水印编号"],
            "required_fields": list(WATERMARK_REQUIRED_FIELDS),
            "parse_notes": parse_notes,
            "message": f"复读通过：在输出文本中读出水印标记 {text_token}，水印仍可辨认。",
        }

    missing_fields = ["水印标记"]
    if not identity:
        missing_fields.insert(0, "水印编号")
    return {
        "readable": False,
        "result": "未通过",
        "detected": False,
        "confidence": 0.0,
        "watermark_no": identity,
        "matched_fields": [],
        "missing_fields": missing_fields,
        "required_fields": list(WATERMARK_REQUIRED_FIELDS),
        "parse_notes": parse_notes,
        "message": (
            "复读未通过：该批次确切输出中没有可读水印，"
            f"缺少水印必需字段：{'、'.join(missing_fields)}；不得作为正式交付下载。"
        ),
    }


# ———————————— 仓库与业务服务 ————————————


class RereadService:
    """脱敏批次、复读回执、交付资格的内存仓库。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.batches: list[dict[str, Any]] = []
        self.receipts: list[dict[str, Any]] = []
        self._batch_seq = 0
        self._receipt_seq = 0

    # ---------- 查询 ----------

    def list_batches(self, sample_code: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = [dict(batch) for batch in self.batches]
        if sample_code:
            target = sample_code.strip().casefold()
            rows = [b for b in rows if str(b.get("sample_code", "")).casefold() == target]
        for batch in rows:
            self._attach_eligibility(batch)
        return rows

    def get_batch(self, batch_id: int) -> dict[str, Any] | None:
        with self._lock:
            batch = self._find_batch(batch_id)
            if batch is None:
                return None
            snapshot = dict(batch)
        self._attach_eligibility(snapshot)
        return snapshot

    def _find_batch(self, batch_id: int) -> dict[str, Any] | None:
        for batch in self.batches:
            if int(batch.get("id", 0)) == int(batch_id):
                return batch
        return None

    def list_receipts(self, sample_code: str | None = None,
                      batch_id: int | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = [dict(receipt) for receipt in self.receipts]
        if sample_code:
            target = sample_code.strip().casefold()
            rows = [r for r in rows if str(r.get("sample_code", "")).casefold() == target]
        if batch_id is not None:
            rows = [r for r in rows if int(r.get("batch_id", -1)) == int(batch_id)]
        return rows

    def get_receipt(self, receipt_id: int) -> dict[str, Any] | None:
        with self._lock:
            for receipt in self.receipts:
                if int(receipt.get("id", 0)) == int(receipt_id):
                    return dict(receipt)
        return None

    def state(self) -> dict[str, Any]:
        """一次性给出批次（含资格）、回执历史与按样本分组的引用关系。"""
        batches = self.list_batches()
        receipts = self.list_receipts()
        return {
            "batches": batches,
            "items": batches,  # 兼容 PageResult.items 风格的消费方
            "receipts": receipts,
            "total": len(batches),
            "receipt_total": len(receipts),
            "sample_groups": self.sample_groups(),
        }

    def sample_groups(self) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for batch in self.list_batches():
            groups.setdefault(str(batch["sample_code"]), []).append(batch)
        result: list[dict[str, Any]] = []
        for sample_code, batches in groups.items():
            ordered = sorted(batches, key=lambda b: int(b["id"]))
            latest = ordered[-1]
            result.append({
                "sample_code": sample_code,
                "latest_batch_id": latest["id"],
                "latest_version": latest.get("version", ""),
                "batch_ids": [b["id"] for b in ordered],
                "deliverable_batch_ids": [b["id"] for b in ordered if b.get("eligible")],
            })
        return result

    # ---------- 写入：提交脱敏批次 ----------

    def create_batch(self, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        values = payload or {}

        sample_code = str(self._pick(
            values, "sample_code", "sample", "sample_no", "样本编号", "样本",
            default="",
        ) or "").strip()
        version = str(self._pick(
            values, "version", "process_version", "processing_version", "处理版本", "版本",
            default="",
        ) or "").strip()

        raw_output = self._pick(
            values, "exact_output", "output", "output_sample", "output_content",
            "result", "payload", "输出样本", "确切输出", "输出内容", "处理结果",
            default=None,
        )

        with self._lock:
            if not sample_code:
                sample_code = f"SAMPLE-{datetime.now():%Y%m%d}-{self._batch_seq + 1:03d}"
            if not version:
                same_sample = [
                    b for b in self.batches
                    if str(b.get("sample_code", "")).casefold() == sample_code.casefold()
                ]
                version = f"v{len(same_sample) + 1}"

            missing: list[str] = []
            if raw_output is None or (isinstance(raw_output, str) and not raw_output.strip()):
                # 允许不传 output：落一个空输出，复读时会如实判为不可读。
                raw_output = {}

            self._batch_seq += 1
            batch_id = int(values.get("id") or self._batch_seq)
            # 防止外部指定 id 撞号。
            if self._find_batch(batch_id) is not None:
                self._batch_seq += 1
                batch_id = self._batch_seq

            output_obj, output_text, _ = _parse_output(raw_output)
            batch_no = str(self._pick(
                values, "batch_no", "batch_code", "批次编号", "批次号",
                default=f"BATCH-{batch_id:04d}",
            ) or f"BATCH-{batch_id:04d}").strip()

            batch: dict[str, Any] = {
                "id": batch_id,
                "batch_no": batch_no,
                "batch_code": batch_no,
                "sample_code": sample_code,
                "sample": sample_code,
                "sample_name": str(self._pick(
                    values, "sample_name", "样本名称", default="",
                ) or "").strip(),
                "version": version,
                "process_version": version,
                "rule_id": self._pick(values, "rule_id", "mask_rule_id", default=None),
                "rule_no": str(self._pick(
                    values, "rule_no", "rule_code", "规则编号", default="",
                ) or "").strip(),
                "rule_version": str(self._pick(
                    values, "rule_version", "规则版本", default="",
                ) or "").strip(),
                "watermark_no": str(self._pick(
                    values, "watermark_no", "watermark_id", "水印编号", "watermark_code",
                    default="",
                ) or "").strip(),
                "exact_output": output_obj if output_obj is not None else output_text,
                "output_text": output_text,
                "submitted_at": _now(),
                "status": "待复读",
                "reread_status": "pending",
                "latest_receipt_id": None,
            }
            self.batches.append(batch)
            snapshot = dict(batch)

        self._attach_eligibility(snapshot)
        return snapshot, missing

    # ---------- 复读：服务端检测确切输出并生成回执 ----------

    def run_reread(self, batch_id: int) -> tuple[dict[str, Any] | None, str]:
        with self._lock:
            batch = self._find_batch(batch_id)
            if batch is None:
                return None, f"脱敏批次 {batch_id} 不存在，无法复读"
            # 关键：检测的是提交时快照的确切输出，而不是任何“当前版本”。
            detection = detect_watermark(batch.get("exact_output"), batch.get("watermark_no"))

            self._receipt_seq += 1
            receipt_id = self._receipt_seq
            receipt_no = f"RR-{receipt_id:04d}"
            receipt: dict[str, Any] = {
                "id": receipt_id,
                "receipt_no": receipt_no,
                "receipt_code": receipt_no,
                "batch_id": int(batch["id"]),
                "batch_no": batch["batch_no"],
                "sample_code": batch["sample_code"],
                "sample": batch["sample_code"],
                "version": batch["version"],
                "process_version": batch["version"],
                "watermark_no": detection.get("watermark_no") or batch.get("watermark_no", ""),
                "readable": detection["readable"],
                "result": detection["result"],
                "detected": detection["detected"],
                "confidence": detection["confidence"],
                "matched_fields": detection["matched_fields"],
                "missing_fields": detection["missing_fields"],
                "required_fields": detection["required_fields"],
                "message": detection["message"],
                "detector": "server-exact-output-watermark-reread",
                "created_at": _now(),
                # 显式的适用对象：迟到的凭据也只能引用这一次交付。
                "applies_to": {
                    "batch_id": int(batch["id"]),
                    "batch_no": batch["batch_no"],
                    "sample_code": batch["sample_code"],
                    "version": batch["version"],
                },
                "delivery": "allowed" if detection["readable"] else "blocked",
                "eligible": bool(detection["readable"]),
            }
            self.receipts.append(receipt)

            batch["latest_receipt_id"] = receipt_id
            batch["status"] = "复读通过" if detection["readable"] else "复读未通过"
            batch["reread_status"] = "passed" if detection["readable"] else "failed"
            result = dict(receipt)

        return result, detection["message"]

    # ---------- 交付资格与交付物 ----------

    def delivery_gate(self, batch_id: int) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str]:
        """返回 (batch, passing_receipt, error_message)。"""
        batch = self.get_batch(batch_id)
        if batch is None:
            return None, None, f"脱敏批次 {batch_id} 不存在或已归档"
        passing = [
            r for r in self.list_receipts(batch_id=batch_id)
            if r.get("readable") and int(r.get("batch_id", -1)) == int(batch_id)
        ]
        if not passing:
            latest = self.list_receipts(batch_id=batch_id)
            if latest:
                return batch, None, (
                    f"批次 {batch['batch_no']}（{batch['sample_code']} / {batch['version']}）"
                    "的复读回执未检出水印，交付已锁定。"
                )
            return batch, None, (
                f"批次 {batch['batch_no']}（{batch['sample_code']} / {batch['version']}）"
                "尚未取得复读回执，不能作为正式交付下载。"
            )
        return batch, passing[-1], ""

    def delivery_document(self, batch_id: int) -> tuple[dict[str, Any] | None, str, str]:
        """构造正式交付文件内容；无资格时返回错误信息。"""
        batch, receipt, error = self.delivery_gate(batch_id)
        if batch is None:
            return None, "", error
        if receipt is None:
            return None, "", error
        document = {
            "document_type": "official_masked_delivery",
            "delivery_name": f"正式交付-{batch['batch_no']}-{batch['version']}",
            "batch": {
                "batch_id": batch["id"],
                "batch_no": batch["batch_no"],
                "sample_code": batch["sample_code"],
                "version": batch["version"],
                "rule_no": batch.get("rule_no", ""),
                "rule_version": batch.get("rule_version", ""),
                "submitted_at": batch.get("submitted_at", ""),
            },
            "reread_receipt": {
                "receipt_id": receipt["id"],
                "receipt_no": receipt["receipt_no"],
                "result": receipt["result"],
                "message": receipt["message"],
                "created_at": receipt["created_at"],
                "applies_to": receipt["applies_to"],
            },
            # 交付的是该批次提交时的确切输出快照。
            "output": batch.get("exact_output"),
        }
        filename = f"official-delivery-batch-{batch['id']}.json"
        return document, filename, ""

    # ---------- 组装辅助 ----------

    def _attach_eligibility(self, batch: dict[str, Any]) -> None:
        batch_id = int(batch["id"])
        receipts = self.list_receipts(batch_id=batch_id)
        passing = [r for r in receipts if r.get("readable")]
        latest = receipts[-1] if receipts else None
        eligible = bool(passing)
        batch["receipts"] = receipts
        batch["receipt_count"] = len(receipts)
        batch["passing_receipt_id"] = passing[-1]["id"] if passing else None
        batch["latest_receipt"] = latest
        batch["eligible"] = eligible
        batch["deliverable"] = eligible
        batch["delivery_status"] = "可正式交付" if eligible else (
            "复读未通过·禁止正式交付" if latest else "待复读·交付未解锁"
        )
        if eligible:
            bound = passing[-1]
            batch["eligibility_message"] = (
                f"复读回执 {bound['receipt_no']} 仅绑定本批次 "
                f"{batch['batch_no']}（样本 {batch['sample_code']} / "
                f"处理版本 {batch['version']}），本版可以正式交付下载；"
                "该通过结果不能替其他批次解锁。"
            )
        elif latest is not None:
            batch["eligibility_message"] = (
                f"最新复读回执 {latest['receipt_no']} 未在本批次确切输出中读到水印，"
                "本版不具备交付资格，正式交付下载已锁定。"
            )
        else:
            batch["eligibility_message"] = "本批次尚未复读，交付资格未解锁。"

    @staticmethod
    def _pick(values: dict[str, Any], *keys: str, default: Any = None) -> Any:
        for key in keys:
            if key in values and values[key] is not None:
                return values[key]
        # 再做一次大小写/连字符不敏感匹配。
        normalized = {_norm_key(k): v for k, v in values.items()}
        for key in keys:
            if _norm_key(key) in normalized and normalized[_norm_key(key)] is not None:
                return normalized[_norm_key(key)]
        return default


reread_service = RereadService()
