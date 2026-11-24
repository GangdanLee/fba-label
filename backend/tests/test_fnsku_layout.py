"""M1 测试套件 3：50×30mm 双排拼版、一体化 barcode1d、可读性分级与双栏扫码回归。"""

from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image
from reportlab.pdfgen.canvas import Canvas

from app.config import mm_to_pt
from app.engines.code128 import evaluate_barcode_readability
from app.engines.fnsku_engine import _wrap_text_to_width, parse_amazon_product_pdf, render_fnsku_elements_pdf
from app.engines.pdf_engine import PyMuPDFEngine, detect_non_white_bbox
from app.main import app
from app.models.schemas import CanvasElement, FnskuRenderRequest
from app.printers.simulator import scan_barcodes_from_image
from tests.conftest import build_synthetic_product_pdf


def test_parse_amazon_product_pdf_and_clean_title() -> None:
    pdf_bytes = build_synthetic_product_pdf(fnsku="X009DEMO01", title="新品：演示硅胶地垫，大号灰色")
    parsed = parse_amazon_product_pdf(pdf_bytes)
    assert parsed["fnsku"] == "X009DEMO01"
    assert parsed["title_clean"].startswith("New - ")
    assert "，" not in parsed["title_clean"]


def test_barcode_readability_thresholds() -> None:
    narrow = evaluate_barcode_readability("X009DEMO01", width_mm=18.0)
    assert narrow.level == "danger"
    standard = evaluate_barcode_readability("X009DEMO01", width_mm=44.0)
    assert standard.level == "safe"
    assert standard.min_dots_per_module >= 2


def test_fnsku_double_row_layout_and_independent_dual_column_zxing() -> None:
    elements = [
        CanvasElement(
            id="el_bc",
            type="barcode1d",
            name="FNSKU 条码",
            x=3.0,
            y=1.5,
            w=44.0,
            h=14.0,
            code="X009NEW777",
            show_text=True,
            font_size=8.0,
        ),
        CanvasElement(
            id="el_title",
            type="text",
            name="商品名称",
            x=3.0,
            y=16.5,
            w=44.0,
            h=8.0,
            text="New - 演示硅胶垫 (DEMO-SKU-01)",
            font_size=7.0,
        ),
        CanvasElement(
            id="el_mic",
            type="text",
            name="产地标识",
            x=3.0,
            y=25.2,
            w=24.0,
            h=3.6,
            text="Made in China",
            font_size=7.0,
            bold=True,
        ),
    ]

    # 3 张双排 -> 应产出 2 页 (102×30mm)，第 2 页右栏空白
    req = FnskuRenderRequest(
        elements=elements,
        width_mm=50.0,
        height_mm=30.0,
        layout_type="double",
        col_gap_mm=2.0,
        qty=3,
    )
    pdf_bytes = render_fnsku_elements_pdf(req)
    eng = PyMuPDFEngine()
    dims = eng.get_page_dimensions_pt(pdf_bytes)
    assert len(dims) == 2

    exp_w = mm_to_pt(102.0)
    exp_h = mm_to_pt(30.0)
    for w_pt, h_pt in dims:
        assert abs(w_pt - exp_w) < 0.05
        assert abs(h_pt - exp_h) < 0.05

    # 第 1 页 203dpi 仿真：总尺寸 816×240，左栏 0..400 与右栏 416..816 各自均可独立扫出 X009NEW777
    img_p0 = eng.render_page_to_1bit(pdf_bytes, page_index=0, dpi=203)
    assert img_p0.size == (816, 240)
    left_crop = img_p0.crop((0, 0, 400, 240))
    right_crop = img_p0.crop((416, 0, 816, 240))
    assert "X009NEW777" in [r["text"] for r in scan_barcodes_from_image(left_crop)]
    assert "X009NEW777" in [r["text"] for r in scan_barcodes_from_image(right_crop)]

    # 第 2 页：左栏有条码可扫出，右栏全白无有效非白内容
    img_p1 = eng.render_page_to_1bit(pdf_bytes, page_index=1, dpi=203)
    p1_left = img_p1.crop((0, 0, 400, 240))
    p1_right = img_p1.crop((416, 0, 816, 240))
    assert "X009NEW777" in [r["text"] for r in scan_barcodes_from_image(p1_left)]
    assert detect_non_white_bbox(p1_right.convert("L"), pad_px=0) is None


def test_40x30_and_50x30_double_row_203dpi_zxing_with_offset() -> None:
    eng = PyMuPDFEngine()
    cases = [
        (40.0, 34.0, 1.0, -0.5),
        (40.0, 35.2, 1.0, -0.5),
        (40.0, 37.0, 1.0, -0.5),
        (50.0, 44.0, 0.8, -0.4),
    ]
    for label_w, bc_w, ox, oy in cases:
        margin_x = round((label_w - bc_w) / 2.0, 2)
        req = FnskuRenderRequest(
            elements=[
                CanvasElement(
                    id=f"bc_{label_w}_{bc_w}",
                    type="barcode1d",
                    x=margin_x,
                    y=2.0,
                    w=bc_w,
                    h=14.0,
                    code="X000SYNC99",
                    show_text=True,
                    font_size=8.0,
                )
            ],
            width_mm=label_w,
            height_mm=30.0,
            layout_type="double",
            col_gap_mm=2.0,
            offset_x_mm=ox,
            offset_y_mm=oy,
            qty=2,
        )
        pdf_bytes = render_fnsku_elements_pdf(req)
        img = eng.render_page_to_1bit(pdf_bytes, page_index=0, dpi=203)
        mid = img.width // 2
        left_codes = [r["text"] for r in scan_barcodes_from_image(img.crop((0, 0, mid + 2, img.height)))]
        right_codes = [r["text"] for r in scan_barcodes_from_image(img.crop((mid - 2, 0, img.width, img.height)))]
        assert "X000SYNC99" in left_codes, f"左栏未能解码: label_w={label_w}, bc_w={bc_w}, got={left_codes}"
        assert "X000SYNC99" in right_codes, f"右栏未能解码: label_w={label_w}, bc_w={bc_w}, got={right_codes}"


def test_wrap_text_respects_english_word_boundaries() -> None:
    c = Canvas(io.BytesIO())
    sample = "Silicone Kitchen Countertop Mat Protector Large"
    lines = _wrap_text_to_width(c, sample, mm_to_pt(42.0), "Helvetica", 7.0)
    assert len(lines) >= 2
    for word in sample.split():
        assert any(word in line.split() for line in lines), f"英文单词被错误截断: {word} not intact in {lines}"


def test_qrcode_preview_endpoint_scannable() -> None:
    client = TestClient(app)
    resp = client.get("/api/fnsku/qrcode-preview", params={"code": "QR_TEST_V012"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")
    img = Image.open(io.BytesIO(resp.content))
    decoded = [r["text"] for r in scan_barcodes_from_image(img)]
    assert "QR_TEST_V012" in decoded
