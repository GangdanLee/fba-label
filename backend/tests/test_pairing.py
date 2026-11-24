"""M1 测试套件 2：货代箱唛裁切扫码、多票 FBA 号隔离、异常拦截与人工归属兜底。"""

from __future__ import annotations

import base64

from fastapi.testclient import TestClient
import fitz

from app.config import mm_to_pt
from app.engines.carrier_parser import process_carrier_pdf
from app.engines.fba_processor import process_fba_pdf
from app.engines.pairing_engine import pair_and_validate
from app.engines.pdf_engine import PyMuPDFEngine
from app.main import app
from app.models.schemas import CanvasElement, PairingRequest
from app.printers.simulator import scan_barcodes_from_image
from tests.conftest import build_synthetic_carrier_pdf, build_synthetic_fba_en_pdf


def test_carrier_crop_and_zxing_barcode_roundtrip() -> None:
    car_pdf = build_synthetic_carrier_pdf(shipment_id="FBA00DEMO01", warehouse="DMO1", total_boxes=2)
    items, out_pdf = process_carrier_pdf(
        car_pdf,
        file_id="car_1",
        file_name="FBA00DEMO01_示例快运_DMO1_2件.pdf",
    )

    assert len(items) == 2
    assert items[0].shipment_id == "FBA00DEMO01"
    assert items[0].warehouse_code == "DMO1"
    assert items[0].box_index == 1 and items[1].box_index == 2

    eng = PyMuPDFEngine()
    expected_pt = mm_to_pt(100.0)
    for w_pt, h_pt in eng.get_page_dimensions_pt(out_pdf):
        assert abs(w_pt - expected_pt) < 0.05
        assert abs(h_pt - expected_pt) < 0.05

    img_1bit = eng.render_page_to_1bit(out_pdf, page_index=0, dpi=203)
    decoded = [item["text"] for item in scan_barcodes_from_image(img_1bit)]
    assert "TRK00DEMO01" in decoded
    assert "FBA00DEMO01-CTN1" in decoded


def test_pairing_isolation_and_queue_ordering() -> None:
    fba1, _ = process_fba_pdf(build_synthetic_fba_en_pdf("FBA00DEMO01", "DMO1", 2), "f1", "f1.pdf")
    fba2, _ = process_fba_pdf(build_synthetic_fba_en_pdf("FBA00DEMO02", "DMO2", 2), "f2", "f2.pdf")
    car1, _ = process_carrier_pdf(build_synthetic_carrier_pdf("FBA00DEMO01", "DMO1", 2), "c1", "c1.pdf")
    car2, _ = process_carrier_pdf(build_synthetic_carrier_pdf("FBA00DEMO02", "DMO2", 2), "c2", "c2.pdf")

    # 1. interleave（贴面交替）
    res_int = pair_and_validate(
        PairingRequest(
            fba_boxes=fba1 + fba2,
            carrier_boxes=car1 + car2,
            default_copies=2,
            order_mode="interleave",
        )
    )
    assert len(res_int.groups) == 2
    assert all(g.status == "matched" for g in res_int.groups)
    assert res_int.can_print is True
    assert [q.label for q in res_int.queue] == ["F1", "M1", "F1", "M1", "F2", "M2", "F2", "M2"]

    # 2. per_box_group（同箱紧邻）
    res_box = pair_and_validate(
        PairingRequest(fba_boxes=fba1, carrier_boxes=car1, default_copies=2, order_mode="per_box_group")
    )
    assert [q.label for q in res_box.queue] == ["F1", "F1", "M1", "M1", "F2", "F2", "M2", "M2"]

    # 3. split_all（分组先后）
    res_split = pair_and_validate(
        PairingRequest(fba_boxes=fba1, carrier_boxes=car1, default_copies=2, order_mode="split_all")
    )
    assert [q.label for q in res_split.queue] == ["F1", "F1", "F2", "F2", "M1", "M1", "M2", "M2"]


def test_pairing_conflict_blocking_and_manual_assignment() -> None:
    fba1, _ = process_fba_pdf(build_synthetic_fba_en_pdf("FBA00DEMO01", "DMO1", 2), "f1", "f1.pdf")

    # 1. 仓点冲突与箱数缺箱拦截
    car_bad, _ = process_carrier_pdf(build_synthetic_carrier_pdf("FBA00DEMO01", "DMO9", 1), "cbad", "cbad.pdf")
    res_bad = pair_and_validate(PairingRequest(fba_boxes=fba1, carrier_boxes=car_bad, work_mode="paired"))
    assert res_bad.can_print is False
    assert res_bad.groups[0].status == "mismatch_detail"
    assert any("仓点冲突" in msg for msg in res_bad.issues)

    # 单边模式仅打外箱仍可放行
    res_fba_only = pair_and_validate(PairingRequest(fba_boxes=fba1, carrier_boxes=car_bad, work_mode="fba_only", default_copies=1))
    assert res_fba_only.can_print is True
    assert [q.label for q in res_fba_only.queue] == ["F1", "F2"]

    # 2. 无 FBA 编号箱唛 -> 待归属 -> 人工绑定后立即配对成功
    car_noid, _ = process_carrier_pdf(
        build_synthetic_carrier_pdf(shipment_id=None, warehouse="DMO1", total_boxes=2),
        file_id="cnoid",
        file_name="no_shipment_mark.pdf",
    )
    res_unassigned = pair_and_validate(PairingRequest(fba_boxes=fba1, carrier_boxes=car_noid))
    assert len(res_unassigned.unassigned_carriers) == 2
    assert res_unassigned.can_print is False

    res_assigned = pair_and_validate(
        PairingRequest(
            fba_boxes=fba1,
            carrier_boxes=car_noid,
            manual_assignments={"cnoid": "FBA00DEMO01"},
            default_copies=1,
        )
    )
    assert len(res_assigned.unassigned_carriers) == 0
    assert res_assigned.groups[0].status == "matched"
    assert res_assigned.can_print is True
    assert [q.label for q in res_assigned.queue] == ["F1", "M1", "F2", "M2"]


def test_pairing_active_shipment_switching_and_fallback() -> None:
    fba1, _ = process_fba_pdf(build_synthetic_fba_en_pdf("FBA00DEMO01", "DMO1", 2), "f1", "f1.pdf")
    fba2, _ = process_fba_pdf(build_synthetic_fba_en_pdf("FBA00DEMO02", "DMO2", 1), "f2", "f2.pdf")
    car1, _ = process_carrier_pdf(build_synthetic_carrier_pdf("FBA00DEMO01", "DMO1", 2), "c1", "c1.pdf")
    car2, _ = process_carrier_pdf(build_synthetic_carrier_pdf("FBA00DEMO02", "DMO2", 1), "c2", "c2.pdf")

    # 1. 指定 active_shipment_id="FBA00DEMO02" 时队列应完全同步至第 2 票
    res_second = pair_and_validate(
        PairingRequest(
            fba_boxes=fba1 + fba2,
            carrier_boxes=car1 + car2,
            default_copies=3,
            order_mode="interleave",
            active_shipment_id="fba00demo02",
        )
    )
    assert res_second.active_shipment_id == "FBA00DEMO02"
    assert res_second.can_print is True
    assert res_second.total_sheets == 6
    assert all(q.shipment_id == "FBA00DEMO02" for q in res_second.queue)
    assert [q.label for q in res_second.queue] == ["F1", "M1", "F1", "M1", "F1", "M1"]

    # 2. 当第 2 票缺少箱唛而切换到第 2 票时，必须阻止打印而非回落至第 1 票队列
    res_missing = pair_and_validate(
        PairingRequest(
            fba_boxes=fba1 + fba2,
            carrier_boxes=car1,
            default_copies=2,
            active_shipment_id="FBA00DEMO02",
        )
    )
    assert res_missing.active_shipment_id == "FBA00DEMO02"
    assert res_missing.can_print is False
    assert res_missing.queue == []
    assert res_missing.total_sheets == 0

    # 3. 传入不存在的 active_shipment_id 时回退到首个 matched 分组
    res_fallback = pair_and_validate(
        PairingRequest(
            fba_boxes=fba1 + fba2,
            carrier_boxes=car1,
            default_copies=1,
            active_shipment_id="FBA_NOT_EXIST",
        )
    )
    assert res_fallback.active_shipment_id == "FBA00DEMO01"
    assert res_fallback.can_print is True
    assert res_fallback.total_sheets == 4


def test_shipment_id_containing_letter_u_and_multi_u_pairing() -> None:
    fba_u1, _ = process_fba_pdf(build_synthetic_fba_en_pdf("FBA00AUD01", "DMO1", 2), "fu1", "FBA00AUD01.pdf")
    fba_u2, _ = process_fba_pdf(build_synthetic_fba_en_pdf("FBAU12U34", "DMO2", 2), "fu2", "FBAU12U34.pdf")
    car_u1, _ = process_carrier_pdf(
        build_synthetic_carrier_pdf("FBA00AUD01", "DMO1", 2),
        "cu1",
        "FBA00AUD01_测试物流_DMO1.pdf",
    )
    car_u2, _ = process_carrier_pdf(
        build_synthetic_carrier_pdf("FBAU12U34", "DMO2", 2),
        "cu2",
        "FBAU12U34_测试物流_DMO2.pdf",
    )

    assert all(b.shipment_id == "FBA00AUD01" for b in fba_u1)
    assert all(b.shipment_id == "FBAU12U34" for b in fba_u2)
    assert all(c.shipment_id == "FBA00AUD01" for c in car_u1)
    assert all(c.shipment_id == "FBAU12U34" for c in car_u2)

    for sid in ("FBA00AUD01", "FBAU12U34"):
        res = pair_and_validate(
            PairingRequest(
                fba_boxes=fba_u1 + fba_u2,
                carrier_boxes=car_u1 + car_u2,
                default_copies=1,
                active_shipment_id=sid,
            )
        )
        assert {g.shipment_id for g in res.groups} == {"FBA00AUD01", "FBAU12U34"}
        assert all(g.status == "matched" for g in res.groups)
        assert res.active_shipment_id == sid
        assert res.can_print is True
        assert res.total_sheets == 4


def test_merged_box_pdf_overlay_elements_vector_layer() -> None:
    client = TestClient(app)
    fba_bytes = build_synthetic_fba_en_pdf("FBA00AUD01", "DMO1", 2)
    car_bytes = build_synthetic_carrier_pdf("FBA00AUD01", "DMO1", 2)

    fba_json = client.post("/api/box/process-fba", files={"file": ("FBA00AUD01.pdf", fba_bytes, "application/pdf")}).json()
    car_json = client.post("/api/box/process-carrier", files={"file": ("FBA00AUD01_car.pdf", car_bytes, "application/pdf")}).json()
    pair_json = client.post(
        "/api/box/pair",
        json={
            "fba_boxes": fba_json["boxes"],
            "carrier_boxes": car_json["items"],
            "default_copies": 1,
            "order_mode": "interleave",
        },
    ).json()
    assert pair_json["can_print"] is True

    ov = CanvasElement(
        id="ov_txt_1",
        type="text",
        x=10.0,
        y=10.0,
        w=60.0,
        h=10.0,
        text="DO NOT STACK",
        font_size=12.0,
        bold=True,
    )
    r_merge = client.post(
        "/api/box/export-merged-pdf",
        json={
            "fba_pdfs_b64": {fba_json["file_id"]: fba_json["pdf_b64"]},
            "carrier_pdfs_b64": {car_json["file_id"]: car_json["pdf_b64"]},
            "queue": pair_json["queue"],
            "overlay_elements": [ov.model_dump(by_alias=True)],
        },
    )
    assert r_merge.status_code == 200
    merged_bytes = base64.b64decode(r_merge.json()["pdf_b64"])
    doc = fitz.open(stream=merged_bytes, filetype="pdf")
    assert len(doc) == 4
    # interleave 顺序：0=fba, 1=carrier, 2=fba, 3=carrier
    assert "DO NOT STACK" in doc[0].get_text()
    assert "FBA00AUD01U000001" in doc[0].get_text()
    assert "DO NOT STACK" not in doc[1].get_text()
    assert "DO NOT STACK" in doc[2].get_text()
    assert "DO NOT STACK" not in doc[3].get_text()
