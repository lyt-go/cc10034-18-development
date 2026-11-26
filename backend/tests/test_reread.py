"""脱敏批次复读 / 回执绑定 / 交付闸门测试。

运行：cd backend && python3 -m pytest tests/ -v
"""
from __future__ import annotations

import pytest

from app.services.reread import RereadService, detect_watermark


VALID_OUTPUT = {
    "样本编号": "SAMPLE-X",
    "处理版本": "v1",
    "水印编号": "WATE-0009",
    "水印标记": "WM-WATE-0009-DEADBEEF",
    "rows": [{"name": "张*", "wm": "WM-WATE-0009-DEADBEEF"}],
}

STRIPPED_OUTPUT = {
    "样本编号": "SAMPLE-X",
    "处理版本": "v2",
    "rows": [{"name": "李*"}],
}


@pytest.fixture()
def svc() -> RereadService:
    # 每个测试一个全新的内存仓库，避免用例间状态串扰。
    return RereadService()


def _batch(svc: RereadService, sample="SAMPLE-X", version="v1", output=VALID_OUTPUT):
    batch, missing = svc.create_batch({
        "sample_code": sample, "version": version, "output": output,
    })
    assert missing == []
    assert batch is not None
    return batch


class TestDetection:
    def test_detect_valid_watermark(self):
        result = detect_watermark(VALID_OUTPUT)
        assert result["readable"] is True
        assert result["result"] == "通过"

    def test_detect_missing_required_fields(self):
        result = detect_watermark(STRIPPED_OUTPUT)
        assert result["readable"] is False
        assert "水印标记" in result["missing_fields"]

    def test_detect_on_json_string_is_exact_output(self):
        # 服务端必须能直接吃提交时快照的 JSON 文本。
        result = detect_watermark('{"水印标记": "WM-ABCDEF123"}')
        assert result["readable"] is True

    def test_detect_empty_output_unreadable(self):
        assert detect_watermark("")["readable"] is False
        assert detect_watermark({})["readable"] is False

    def test_sample_code_with_wm_fragment_is_not_watermark(self):
        # 样本编号 SAMPLE-WM-001 里的 WM-001 片段不能被误判成可读水印；
        # 去掉水印必需字段后必须判定不可读。
        stripped_like_ui = {
            "样本编号": "SAMPLE-WM-001",
            "处理版本": "v2",
            "水印算法": "LSB最低位替换",
            "records": [{"姓名": "张*", "手机号": "138****1234"}],
        }
        result = detect_watermark(stripped_like_ui)
        assert result["readable"] is False
        assert "水印标记" in result["missing_fields"]

    def test_strong_text_token_detected(self):
        result = detect_watermark("masked row,token=WM-WATE-0001-7F3A9C21,end")
        assert result["readable"] is True


class TestReceiptIdentity:
    def test_receipt_identifies_sample_version_batch(self, svc: RereadService):
        batch = _batch(svc)
        receipt, _ = svc.run_reread(batch["id"])
        assert receipt is not None
        assert receipt["batch_id"] == batch["id"]
        assert receipt["sample_code"] == "SAMPLE-X"
        assert receipt["version"] == "v1"
        applies = receipt["applies_to"]
        assert applies["batch_id"] == batch["id"]
        assert applies["sample_code"] == "SAMPLE-X"
        assert applies["version"] == "v1"

    def test_one_passing_batch_does_not_unlock_other(self, svc: RereadService):
        b1 = _batch(svc, version="v1", output=VALID_OUTPUT)
        b2 = _batch(svc, version="v2", output=STRIPPED_OUTPUT)
        r1, _ = svc.run_reread(b1["id"])
        assert r1["readable"] is True

        # b2 没有自己的通过回执：即使同样本的 b1 已通过，b2 仍不可交付。
        b2_view = svc.get_batch(b2["id"])
        assert b2_view is not None
        assert b2_view["eligible"] is False

        r2, _ = svc.run_reread(b2["id"])
        assert r2["readable"] is False
        assert svc.get_batch(b1["id"])["eligible"] is True
        assert svc.get_batch(b2["id"])["eligible"] is False

    def test_interleaved_results_stay_bound_to_batches(self, svc: RereadService):
        """模拟两次复读交错返回：先落 b2 结果、再落 b1 结果，身份不能串。"""
        b1 = _batch(svc, version="v1", output=VALID_OUTPUT)
        b2 = _batch(svc, version="v2", output=STRIPPED_OUTPUT)

        # 调换落库顺序，等价于网络响应交错到达。
        r2, _ = svc.run_reread(b2["id"])
        r1, _ = svc.run_reread(b1["id"])

        assert r1["batch_id"] == b1["id"] and r1["readable"] is True
        assert r2["batch_id"] == b2["id"] and r2["readable"] is False
        assert svc.get_batch(b1["id"])["passing_receipt_id"] == r1["id"]
        # b2 最新回执是失败回执，且不存在通过回执。
        assert svc.get_batch(b2["id"])["passing_receipt_id"] is None

    def test_reprocess_keeps_old_receipt_delivery_scope(self, svc: RereadService):
        """样本重处理后，早先通过回执仍只适用于旧批次那次交付。"""
        b1 = _batch(svc, version="v1", output=VALID_OUTPUT)
        old_receipt, _ = svc.run_reread(b1["id"])

        # 同一样本重处理得到 v2（新批次），尚未复读。
        b2 = _batch(svc, version="v2", output=VALID_OUTPUT)
        assert b2["id"] != b1["id"]

        groups = {g["sample_code"]: g for g in svc.sample_groups()}
        group = groups["SAMPLE-X"]
        assert group["latest_batch_id"] == b2["id"]
        assert group["deliverable_batch_ids"] == [b1["id"]]

        # 旧凭据的适用对象仍然明确指向旧批次。
        assert old_receipt["applies_to"]["batch_id"] == b1["id"]


class TestDeliveryGate:
    def test_delivery_allowed_only_for_bound_passing_batch(self, svc: RereadService):
        b1 = _batch(svc, output=VALID_OUTPUT)
        b2 = _batch(svc, version="v2", output=STRIPPED_OUTPUT)

        doc, filename, err = svc.delivery_document(b1["id"])
        assert doc is None and "尚未取得复读回执" in err

        svc.run_reread(b1["id"])
        doc, filename, err = svc.delivery_document(b1["id"])
        assert err == "" and doc is not None
        assert filename.endswith(f"batch-{b1['id']}.json")
        assert doc["reread_receipt"]["applies_to"]["batch_id"] == b1["id"]

        doc2, _, err2 = svc.delivery_document(b2["id"])
        assert doc2 is None and "尚未取得复读回执" in err2

        svc.run_reread(b2["id"])
        doc2, _, err2 = svc.delivery_document(b2["id"])
        assert doc2 is None and "水印" in err2

    def test_delivery_unknown_batch(self, svc: RereadService):
        doc, receipt, err = svc.delivery_gate(9999)
        assert doc is None and receipt is None and "不存在" in err
