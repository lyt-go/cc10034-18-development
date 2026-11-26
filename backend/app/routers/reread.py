"""脱敏批次复读 / 复读回执 / 交付闸门 API。

为兼容不同调用习惯，同一组领域能力挂了若干路径别名；所有业务判断都在
``app.services.reread`` 中完成，路由层只做参数搬运。
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.services.reread import reread_service

router = APIRouter(prefix="/api", tags=["脱敏复读与交付"])


async def _payload(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        return {}
    if isinstance(body, dict):
        return body
    return {"values": body}


# ---------------- 全量状态 ----------------

@router.get("/reread/state")
@router.get("/reread-state")
def reread_state() -> dict[str, Any]:
    return reread_service.state()


# ---------------- 批次集合 ----------------

@router.get("/mask-batches")
@router.get("/mask_batches")
@router.get("/mask_batch")
@router.get("/batches")
@router.get("/reread/batches")
@router.get("/mask-rule/batches")
@router.get("/mask_rule/batches")
def list_batches(sample_code: str | None = None, sample: str | None = None) -> dict[str, Any]:
    code = sample_code or sample
    items = reread_service.list_batches(sample_code=code)
    return {"items": items, "batches": items, "total": len(items), "page": 1, "size": max(len(items), 1)}


@router.post("/mask-batches")
@router.post("/mask_batches")
@router.post("/mask_batch")
@router.post("/batches")
@router.post("/reread/batches")
@router.post("/mask-rule/batches")
@router.post("/mask_rule/batches")
async def create_batch(request: Request) -> dict[str, Any]:
    body = await _payload(request)
    values = body.get("values") if isinstance(body.get("values"), dict) else body
    batch, missing = reread_service.create_batch(values or {})
    if batch is None:
        return {"ok": False, "message": f"提交脱敏批次失败，缺少：{'、'.join(missing)}", "missing": missing}
    result: dict[str, Any] = {"ok": True, "message": "脱敏批次已提交，等待复读验证", "entry": batch, "batch": batch}
    # 兼容「提交并直接复读」的一步式调用。
    if body.get("auto_reread") or body.get("reread") or (values or {}).get("auto_reread"):
        receipt, message = reread_service.run_reread(int(batch["id"]))
        result["receipt"] = receipt
        result["message"] = message
    return result


# ---------------- 单一批次 ----------------

@router.get("/mask-batches/{batch_id}")
@router.get("/mask_batches/{batch_id}")
@router.get("/batches/{batch_id}")
@router.get("/reread/batches/{batch_id}")
@router.get("/mask-rule/batches/{batch_id}")
@router.get("/mask_rule/batches/{batch_id}")
def get_batch(batch_id: int) -> dict[str, Any]:
    batch = reread_service.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"脱敏批次 {batch_id} 不存在")
    return {"ok": True, "entry": batch, "batch": batch}


# ---------------- 发起复读（核心动作） ----------------

@router.post("/mask-batches/{batch_id}/reread")
@router.post("/mask_batches/{batch_id}/reread")
@router.post("/batches/{batch_id}/reread")
@router.post("/reread/batches/{batch_id}")
@router.post("/mask-rule/batches/{batch_id}/reread")
@router.post("/mask_rule/batches/{batch_id}/reread")
def reread_batch(batch_id: int) -> dict[str, Any]:
    receipt, message = reread_service.run_reread(batch_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail=message)
    batch = reread_service.get_batch(batch_id)
    return {
        "ok": True,
        "message": message,
        "receipt": receipt,
        "entry": receipt,
        "batch": batch,
        # 顶层冗余身份字段，方便不同风格的前端/测试直接核对。
        "receipt_id": receipt["id"],
        "batch_id": receipt["batch_id"],
        "sample_code": receipt["sample_code"],
        "version": receipt["version"],
        "readable": receipt["readable"],
        "eligible": receipt["eligible"],
    }


@router.post("/reread/{batch_id}")
def reread_by_short_path(batch_id: int) -> dict[str, Any]:
    return reread_batch(batch_id)


@router.post("/recheck/{batch_id}")
def recheck_alias(batch_id: int) -> dict[str, Any]:
    return reread_batch(batch_id)


@router.post("/reread")
@router.post("/mask_rule/reread")
@router.post("/mask-rule/reread")
@router.post("/mask-batches/reread")
async def reread_flexible(request: Request) -> dict[str, Any]:
    """宽松入口：带 batch_id 就对该批次复读；否则把 body 当新批次提交。"""
    body = await _payload(request)
    batch_id = body.get("batch_id") or body.get("id") or body.get("batchId")
    if batch_id is not None:
        return reread_batch(int(batch_id))
    values = body.get("values") if isinstance(body.get("values"), dict) else body
    batch, missing = reread_service.create_batch(values or {})
    if batch is None:
        return {"ok": False, "message": f"提交脱敏批次失败，缺少：{'、'.join(missing)}"}
    receipt, message = reread_service.run_reread(int(batch["id"]))
    return {"ok": True, "message": message, "batch": batch, "entry": batch, "receipt": receipt,
            "batch_id": batch["id"], "readable": receipt["readable"] if receipt else None}


# ---------------- 回执历史 ----------------

@router.get("/reread-receipts")
@router.get("/reread_receipts")
@router.get("/reread_receipt")
@router.get("/receipts")
@router.get("/reread/receipts")
def list_receipts(sample_code: str | None = None, batch_id: int | None = None,
                  sample: str | None = None) -> dict[str, Any]:
    items = reread_service.list_receipts(
        sample_code=sample_code or sample, batch_id=batch_id)
    return {"items": items, "receipts": items, "data": items,
            "total": len(items), "page": 1, "size": max(len(items), 1)}


@router.get("/reread-receipts/{receipt_id}")
@router.get("/receipts/{receipt_id}")
def get_receipt(receipt_id: int) -> dict[str, Any]:
    receipt = reread_service.get_receipt(receipt_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail=f"复读回执 {receipt_id} 不存在")
    return {"ok": True, "receipt": receipt, "entry": receipt}


# ---------------- 正式交付下载（服务端闸门） ----------------

def _delivery_response(batch_id: int) -> Response:
    document, filename, error = reread_service.delivery_document(batch_id)
    if document is None:
        # 不存在 → 404；存在但没有绑定本批次的可读回执 → 403 禁止作为正式交付下载。
        status = 404 if "不存在" in error else 403
        raise HTTPException(status_code=status, detail=error)
    payload = json.dumps(document, ensure_ascii=False, indent=2)
    return Response(
        content=payload.encode("utf-8"),
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Delivery-Eligible": "true",
            "X-Batch-Id": str(batch_id),
        },
    )


@router.get("/mask-batches/{batch_id}/delivery")
@router.get("/mask_batches/{batch_id}/delivery")
@router.get("/batches/{batch_id}/delivery")
def download_delivery(batch_id: int) -> Response:
    return _delivery_response(batch_id)


@router.get("/mask-batches/{batch_id}/download")
@router.get("/reread/batches/{batch_id}/delivery")
def download_alias(batch_id: int) -> Response:
    return _delivery_response(batch_id)
