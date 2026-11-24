"""v0.6.0 Amazon AWD 标签识别、可选脱敏、100×150mm 双尺寸落版、PO 跨文件配对与合规检查单测。"""

from __future__ import annotations

import base64
import io
import zipfile

import pymupdf
from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas

from app.config import mm_to_pt
from app.engines.code128 import draw_barcode1d_on_reportlab
from app.engines.fba_processor import detect_box_label_type, process_fba_pdf
from app.engines.font_manager import ensure_reportlab_font
from app.engines.pdf_engine import PyMuPDFEngine
from app.main import app
from app.models.schemas import FbaRedactionOptions
from app.printers.simulator import scan_barcodes_from_image


def _build_synthetic_awd_pdf(
    shipment_id: str = "STAR-DEMOAWD0001",
    warehouse: str = "IUTL",
    po_id: str = "DMPO0001",
    sku: str = "DEMO-AWD-SKU1",
    fnsku: str = "X000AWDDM1",
    total_boxes: int = 2,
    weight_text: str = "38 lbs",
    units_count: int = 4,
    mixed_sku: bool = False,
) -> bytes:
    """生成 100% 虚构的高保真 4×6 英寸 Amazon AWD 外箱标签（含 FNSKU 与 SSCC 双矢量 Code128 条码）。"""
    buf = io.BytesIO()
    w_mm, h_mm = 101.6, 152.4
    c = Canvas(buf, pagesize=(mm_to_pt(w_mm), mm_to_pt(h_mm)))
    font_reg = ensure_reportlab_font(prefer_cjk=False, bold=False)
    font_bold = ensure_reportlab_font(prefer_cjk=False, bold=True)
    font_zh = ensure_reportlab_font(prefer_cjk=True, bold=False)

    for box_no in range(1, total_boxes + 1):
        sscc = f"000000000000000{box_no:03d}"
        c.setLineWidth(1.2)
        c.rect(mm_to_pt(4), mm_to_pt(4), mm_to_pt(w_mm - 8), mm_to_pt(h_mm - 8))

        # 顶栏：黑底白字 AWD + Box X of N + 黑底白字重量
        c.setFillColorRGB(0, 0, 0)
        c.rect(mm_to_pt(4), mm_to_pt(h_mm - 18), mm_to_pt(24), mm_to_pt(14), stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont(font_bold, 14)
        c.drawString(mm_to_pt(8), mm_to_pt(h_mm - 13), "AWD")

        c.setFillColorRGB(0, 0, 0)
        c.setFont(font_bold, 10)
        c.drawCentredString(mm_to_pt(50), mm_to_pt(h_mm - 13), f"Box {box_no} of {total_boxes}")

        c.rect(mm_to_pt(72), mm_to_pt(h_mm - 18), mm_to_pt(25.6), mm_to_pt(14), stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont(font_bold, 10)
        c.drawString(mm_to_pt(76), mm_to_pt(h_mm - 13), weight_text)

        # 次顶栏 SKU / Units
        c.setFillColorRGB(0, 0, 0)
        c.setFont(font_reg, 8)
        sku_line = f"Mixed SKU ({sku})" if mixed_sku else f"SKU: {sku}"
        c.drawString(mm_to_pt(6), mm_to_pt(h_mm - 23.5), sku_line)
        c.setFont(font_bold, 8.5)
        c.drawRightString(mm_to_pt(95), mm_to_pt(h_mm - 23.5), f"Units: {units_count}")

        # FNSKU 黑底反白条 + 上方 FNSKU Code128 条码
        c.rect(mm_to_pt(4), mm_to_pt(h_mm - 33), mm_to_pt(w_mm - 8), mm_to_pt(7.5), stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont(font_bold, 10)
        c.drawString(mm_to_pt(6), mm_to_pt(h_mm - 30.8), f"FNSKU: {fnsku}")
        c.setFillColorRGB(0, 0, 0)

        draw_barcode1d_on_reportlab(
            c=c,
            code=fnsku,
            x_mm=12.0,
            y_top_mm=36.0,
            w_mm=77.0,
            h_mm=16.0,
            page_h_mm=h_mm,
            show_text=False,
        )

        # 日期 + 右侧大写仓点代码
        c.setFont(font_reg, 7.5)
        c.drawString(mm_to_pt(44), mm_to_pt(h_mm - 59), "Created: 11/24/2026")
        c.setFont(font_bold, 11)
        c.drawString(mm_to_pt(79), mm_to_pt(h_mm - 59), warehouse)

        # 左栏发货地 / 右栏目的地
        c.setFont(font_zh, 7.5)
        c.drawString(mm_to_pt(7), mm_to_pt(h_mm - 65), "发货地:")
        c.drawString(mm_to_pt(7), mm_to_pt(h_mm - 69.5), "演示市虚构科技有限公司")
        c.drawString(mm_to_pt(7), mm_to_pt(h_mm - 74), "Example Province - Demo City - 000000")
        c.drawString(mm_to_pt(7), mm_to_pt(h_mm - 78.5), "中国")

        c.drawString(mm_to_pt(50), mm_to_pt(h_mm - 65), "目的地:")
        c.setFont(font_bold, 7.2)
        c.drawString(mm_to_pt(50), mm_to_pt(h_mm - 69.5), "AWD Fictional Brand Co")
        c.setFont(font_reg, 7.0)
        c.drawString(mm_to_pt(50), mm_to_pt(h_mm - 74), f"{warehouse}- AWD 3PL (Demo Park, US)")
        c.drawString(mm_to_pt(50), mm_to_pt(h_mm - 78.5), "200 Demo Ave, Demo State 00000")
        c.drawString(mm_to_pt(50), mm_to_pt(h_mm - 83), "US")

        # 下方 SSCC Code128 长条码 + 黑底 SSCC 文案
        draw_barcode1d_on_reportlab(
            c=c,
            code=sscc,
            x_mm=10.0,
            y_top_mm=94.0,
            w_mm=81.0,
            h_mm=24.0,
            page_h_mm=h_mm,
            show_text=False,
        )
        c.setFillColorRGB(0, 0, 0)
        c.rect(mm_to_pt(4), mm_to_pt(h_mm - 131), mm_to_pt(w_mm - 8), mm_to_pt(8), stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont(font_bold, 10)
        c.drawCentredString(mm_to_pt(w_mm / 2), mm_to_pt(h_mm - 128.5), f"SSCC: {sscc}")

        # 底部 PO / STAR / AWD 单标声明
        c.setFillColorRGB(0, 0, 0)
        c.setFont(font_zh, 7.5)
        c.drawCentredString(mm_to_pt(w_mm / 2), mm_to_pt(h_mm - 138), f"采购订单 (PO) ID: {po_id}, 货物 ID: {shipment_id}")
        c.setFont(font_reg, 7.0)
        c.drawCentredString(mm_to_pt(w_mm / 2), mm_to_pt(h_mm - 143), "This label must not be covered. Only one label per box.")
        c.showPage()

    c.save()
    return buf.getvalue()


def _build_po_only_carrier_pdf(po_id: str = "DMPO0001", warehouse: str = "IUTL", total_boxes: int = 2) -> bytes:
    """生成仅印有 PO ID、不含 STAR- 编号的 100% 虚构 AWD 货代箱唛。"""
    buf = io.BytesIO()
    w_mm, h_mm = 110.0, 115.0
    c = Canvas(buf, pagesize=(mm_to_pt(w_mm), mm_to_pt(h_mm)))
    font_bold = ensure_reportlab_font(prefer_cjk=False, bold=True)
    font_reg = ensure_reportlab_font(prefer_cjk=False, bold=False)

    for ctn in range(1, total_boxes + 1):
        trk = f"AWDTRK{ctn:04d}"
        c.setLineWidth(1.4)
        c.rect(mm_to_pt(7), mm_to_pt(10), mm_to_pt(96), mm_to_pt(96))
        c.line(mm_to_pt(7), mm_to_pt(h_mm - 48), mm_to_pt(103), mm_to_pt(h_mm - 48))
        c.setFont(font_bold, 16)
        c.drawCentredString(mm_to_pt(55), mm_to_pt(h_mm - 26), warehouse)
        c.setFont(font_bold, 11)
        c.drawString(mm_to_pt(13), mm_to_pt(h_mm - 41), f"CTNS:{ctn}/{total_boxes}")
        c.setFont(font_bold, 12)
        c.drawCentredString(mm_to_pt(55), mm_to_pt(h_mm - 60), f"PO ID: {po_id}")
        c.setFont(font_reg, 9)
        c.drawCentredString(mm_to_pt(55), mm_to_pt(h_mm - 70), "MADE IN CHINA")
        draw_barcode1d_on_reportlab(
            c=c,
            code=trk,
            x_mm=18.0,
            y_top_mm=75.0,
            w_mm=74.0,
            h_mm=16.0,
            page_h_mm=h_mm,
            show_text=True,
            font_size_pt=8.0,
        )
        c.showPage()

    c.save()
    return buf.getvalue()


def test_awd_detection_metadata_compliance_and_default_preserve() -> None:
    pdf_bytes = _build_synthetic_awd_pdf(
        shipment_id="STAR-DEMOAWD0001",
        warehouse="IUTL",
        po_id="DMPO0001",
        sku="DEMO-AWD-SKU1",
        fnsku="X000AWDDM1",
        total_boxes=2,
        weight_text="55 lbs",
        units_count=180,
        mixed_sku=True,
    )

    # 默认参数：AWD 原样保真不删公司名，纸张 100×150mm 清晰出纸
    boxes_150, out_150 = process_fba_pdf(
        pdf_bytes,
        file_id="awd_150",
        file_name="STAR-DEMOAWD0001_IUTL.pdf",
        options=FbaRedactionOptions(paper_size="100x150"),
    )
    assert len(boxes_150) == 2
    b0 = boxes_150[0]
    assert b0.label_type == "awd"
    assert b0.shipment_id == "STAR-DEMOAWD0001"
    assert b0.po_id == "DMPO0001"
    assert b0.sscc_code == "000000000000000001"
    assert b0.fnsku == "X000AWDDM1"
    assert b0.warehouse_code == "IUTL"
    assert b0.qty == 180
    assert b0.weight_text == "55 lbs"
    assert b0.redacted_regions_count == 0
    assert b0.mic_auto_added is False

    # 超重(>50 lbs)、超件(>150)、混箱(Mixed SKU)合规预警
    warn_joined = " | ".join(b0.compliance_warnings)
    assert "50 lbs" in warn_joined
    assert "150" in warn_joined
    assert "Mixed SKU" in warn_joined

    eng = PyMuPDFEngine()
    dims_150 = eng.get_page_dimensions_pt(out_150)
    for w_pt, h_pt in dims_150:
        assert abs(w_pt - mm_to_pt(100.0)) < 0.08
        assert abs(h_pt - mm_to_pt(150.0)) < 0.08

    # 原样保真下公司名和地址均保留，且 203dpi 双条码均可被 zxing-cpp 扫出
    with pymupdf.open(stream=out_150, filetype="pdf") as doc:
        txt0 = doc[0].get_text("text")
        assert "演示市虚构科技有限公司" in txt0
        assert "AWD Fictional Brand Co" in txt0
        assert "200 Demo Ave" in txt0

    img_150 = eng.render_page_to_1bit(out_150, page_index=0, dpi=203)
    decoded_150 = {item["text"] for item in scan_barcodes_from_image(img_150)}
    assert "X000AWDDM1" in decoded_150
    assert "000000000000000001" in decoded_150

    # 切到 100×100mm 时输出精确正方形页面
    boxes_100, out_100 = process_fba_pdf(
        pdf_bytes,
        file_id="awd_100",
        file_name="STAR-DEMOAWD0001_IUTL.pdf",
        options=FbaRedactionOptions(paper_size="100x100"),
    )
    assert len(boxes_100) == 2
    dims_100 = eng.get_page_dimensions_pt(out_100)
    for w_pt, h_pt in dims_100:
        assert abs(w_pt - mm_to_pt(100.0)) < 0.08
        assert abs(h_pt - mm_to_pt(100.0)) < 0.08


def test_awd_optional_redaction_preserves_dual_barcodes_and_203dpi_scan() -> None:
    pdf_bytes = _build_synthetic_awd_pdf(
        shipment_id="STAR-DEMOAWD0002",
        warehouse="IUSJ",
        po_id="DMPO0002",
        sku="DEMO-AWD-SKU2",
        fnsku="X000AWDDM2",
        total_boxes=1,
        weight_text="36 lbs",
        units_count=12,
        mixed_sku=False,
    )
    boxes, out_pdf = process_fba_pdf(
        pdf_bytes,
        file_id="awd_red",
        file_name="STAR-DEMOAWD0002_IUSJ.pdf",
        options=FbaRedactionOptions(
            redact_ship_from=True,
            redact_fba_company=True,
            awd_apply_redaction=True,
            auto_add_mic=True,
            paper_size="100x150",
        ),
    )
    assert len(boxes) == 1
    assert boxes[0].redacted_regions_count >= 2
    assert boxes[0].compliance_warnings == []

    with pymupdf.open(stream=out_pdf, filetype="pdf") as doc:
        txt = doc[0].get_text("text")
        assert "演示市虚构科技有限公司" not in txt
        assert "AWD Fictional Brand Co" not in txt
        assert "IUSJ- AWD 3PL" in txt
        assert "200 Demo Ave" in txt
        assert "STAR-DEMOAWD0002" in txt
        assert "000000000000000001" in txt

    img_1bit = PyMuPDFEngine().render_page_to_1bit(out_pdf, page_index=0, dpi=203)
    decoded = {item["text"] for item in scan_barcodes_from_image(img_1bit)}
    assert "X000AWDDM2" in decoded
    assert "000000000000000001" in decoded


def test_awd_carrier_po_id_auto_pairing_and_merged_100x150_export() -> None:
    client = TestClient(app)
    awd_bytes = _build_synthetic_awd_pdf(
        shipment_id="STAR-DEMOAWD0003",
        warehouse="IUTL",
        po_id="DMPO0003",
        sku="DEMO-AWD-SKU3",
        fnsku="X000AWDDM3",
        total_boxes=2,
    )
    car_bytes = _build_po_only_carrier_pdf(po_id="DMPO0003", warehouse="IUTL", total_boxes=2)

    r_fba = client.post(
        "/api/box/process-fba",
        files={"file": ("STAR-DEMOAWD0003.pdf", awd_bytes, "application/pdf")},
        data={"paper_size": "100x150", "awd_apply_redaction": "false"},
    )
    assert r_fba.status_code == 200
    fba_json = r_fba.json()
    assert fba_json["label_type"] == "awd"
    assert fba_json["paper_size"] == "100x150"
    assert fba_json["boxes"][0]["po_id"] == "DMPO0003"

    r_car = client.post(
        "/api/box/process-carrier",
        files={"file": ("PO_DMPO0003_Carrier.pdf", car_bytes, "application/pdf")},
        data={"paper_size": "100x150"},
    )
    assert r_car.status_code == 200
    car_json = r_car.json()
    assert car_json["paper_size"] == "100x150"
    assert car_json["items"][0]["po_id"] == "DMPO0003"
    assert car_json["items"][0]["shipment_id"] is None

    r_pair = client.post(
        "/api/box/pair",
        json={
            "fba_boxes": fba_json["boxes"],
            "carrier_boxes": car_json["items"],
            "work_mode": "paired",
            "order_mode": "interleave",
            "group_by": "shipment",
            "default_fba_copies": 1,
            "default_carrier_copies": 1,
            "insert_separator_pages": False,
        },
    )
    assert r_pair.status_code == 200
    pair_json = r_pair.json()
    assert len(pair_json["groups"]) == 1
    grp = pair_json["groups"][0]
    assert grp["shipment_id"] == "STAR-DEMOAWD0003"
    assert grp["has_awd"] is True
    assert grp["status"] == "matched"
    assert len(grp["pairs"]) == 2
    assert grp["pairs"][0]["carrier_box"] is not None

    r_exp = client.post(
        "/api/box/export-merged-pdf",
        json={
            "fba_pdfs_b64": {fba_json["file_id"]: fba_json["pdf_b64"]},
            "carrier_pdfs_b64": {car_json["file_id"]: car_json["pdf_b64"]},
            "queue": pair_json["queue"],
            "overlay_elements": [],
            "paper_size": "100x150",
        },
    )
    assert r_exp.status_code == 200
    exp_bytes = base64.b64decode(r_exp.json()["pdf_b64"])
    dims = PyMuPDFEngine().get_page_dimensions_pt(exp_bytes)
    assert len(dims) == 4
    for w_pt, h_pt in dims:
        assert abs(w_pt - mm_to_pt(100.0)) < 0.08
        assert abs(h_pt - mm_to_pt(150.0)) < 0.08

    # SKU 模式带分隔页 ZIP 导出也应全页为 100×150mm
    r_pair_sku = client.post(
        "/api/box/pair",
        json={
            "fba_boxes": fba_json["boxes"],
            "carrier_boxes": car_json["items"],
            "work_mode": "paired",
            "order_mode": "interleave",
            "group_by": "sku",
            "default_fba_copies": 1,
            "default_carrier_copies": 1,
            "insert_separator_pages": True,
        },
    )
    assert r_pair_sku.status_code == 200
    r_zip = client.post(
        "/api/box/export-sku-zip",
        json={
            "fba_pdfs_b64": {fba_json["file_id"]: fba_json["pdf_b64"]},
            "carrier_pdfs_b64": {car_json["file_id"]: car_json["pdf_b64"]},
            "groups": r_pair_sku.json()["groups"],
            "group_by": "sku",
            "work_mode": "paired",
            "order_mode": "per_box_group",
            "insert_separator_pages": True,
            "paper_size": "100x150",
        },
    )
    assert r_zip.status_code == 200
    zip_bytes = base64.b64decode(r_zip.json()["zip_b64"])
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        pdf_names = [n for n in zf.namelist() if n.endswith(".pdf")]
        assert len(pdf_names) == 1
        pdf_in_zip = zf.read(pdf_names[0])
        zip_dims = PyMuPDFEngine().get_page_dimensions_pt(pdf_in_zip)
        assert len(zip_dims) == 5  # 1 分隔页 + 4 标签页
        for w_pt, h_pt in zip_dims:
            assert abs(w_pt - mm_to_pt(100.0)) < 0.08
            assert abs(h_pt - mm_to_pt(150.0)) < 0.08


def test_v060_box_preferences_paper_size_and_awd_redaction_persistence() -> None:
    client = TestClient(app)
    r0 = client.get("/api/box/preferences")
    assert r0.status_code == 200
    d0 = r0.json()
    assert d0["box_paper_size"] == "100x100"
    assert d0["awd_apply_redaction"] is False

    payload = {
        **d0,
        "box_paper_size": "100x150",
        "awd_apply_redaction": True,
        "fba_copies": 1,
        "carrier_copies": 1,
    }
    r1 = client.put("/api/box/preferences", json=payload)
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["box_paper_size"] == "100x150"
    assert d1["awd_apply_redaction"] is True

    r2 = client.get("/api/box/preferences")
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["box_paper_size"] == "100x150"
    assert d2["awd_apply_redaction"] is True


def test_fba_with_awd_named_sku_stays_fba() -> None:
    sample_txt = "FBA\nBox 1 of 2 - 20lb\nSHIP FROM:\nDemo Co\nSHIP TO:\nFBA: Seller\nFBA STA (DEMO) - DMO1\nSingle SKU: DEMO-AWD-01"
    assert detect_box_label_type(sample_txt) == "fba"
