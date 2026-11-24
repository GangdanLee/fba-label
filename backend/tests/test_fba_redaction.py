"""M1 测试套件 1：FBA 外箱中英文物理真脱敏、尺寸精度、安全框边界与扫码回归。"""

from __future__ import annotations

import pymupdf

from app.config import mm_to_pt
from app.engines.fba_processor import process_fba_pdf
from app.engines.pdf_engine import PyMuPDFEngine, detect_non_white_bbox
from app.models.schemas import FbaRedactionOptions
from app.printers.simulator import scan_barcodes_from_image
from tests.conftest import build_synthetic_fba_en_pdf, build_synthetic_fba_zh_4x6_pdf


def test_fba_en_physical_redaction_and_zxing_roundtrip() -> None:
    src_pdf = build_synthetic_fba_en_pdf(shipment_id="FBA00DEMO01", warehouse="DMO1", total_boxes=2, include_mic=True)
    boxes, out_pdf = process_fba_pdf(
        src_pdf,
        file_id="f_en",
        file_name="FBA00DEMO01_demo_en.pdf",
        options=FbaRedactionOptions(redact_ship_from=True, redact_fba_company=True, auto_add_mic=True),
    )

    assert len(boxes) == 2
    assert boxes[0].shipment_id == "FBA00DEMO01"
    assert boxes[0].warehouse_code == "DMO1"
    assert boxes[0].lang == "en"
    assert boxes[0].has_made_in_china is True
    assert boxes[0].mic_auto_added is False

    eng = PyMuPDFEngine()
    dims = eng.get_page_dimensions_pt(out_pdf)
    expected_pt = mm_to_pt(100.0)
    for w_pt, h_pt in dims:
        assert abs(w_pt - expected_pt) < 0.05
        assert abs(h_pt - expected_pt) < 0.05

    texts = eng.extract_text_per_page(out_pdf)
    for idx, page_txt in enumerate(texts):
        # 底层文本流绝不可检索到发件人与公司名
        assert "Demo Sender" not in page_txt
        assert "88 Fictional Road" not in page_txt
        assert "Example Fictional Seller" not in page_txt
        # 必须保留 FBA 标头及美国收货仓库地址
        assert "FBA:" in page_txt
        assert "Amazon Demo FC" in page_txt
        assert "100 Mock Ave" in page_txt

        # 203dpi 位图安全框边界检查（800×800 px 下有效内容不贴死 0 或 800 边缘）
        img_1bit = eng.render_page_to_1bit(out_pdf, page_index=idx, dpi=203)
        assert img_1bit.size == (800, 800)
        bbox = detect_non_white_bbox(img_1bit.convert("L"), pad_px=0)
        assert bbox is not None
        l, t, r, b = bbox
        assert l >= 4 and t >= 4 and r <= 796 and b <= 796

        # zxing-cpp 自动扫码：必须扫出精确箱码
        decoded = [item["text"] for item in scan_barcodes_from_image(img_1bit)]
        expected_box_id = f"FBA00DEMO01U{idx + 1:06d}"
        assert expected_box_id in decoded


def test_fba_zh_4x6_crop_redaction_and_auto_made_in_china() -> None:
    src_pdf = build_synthetic_fba_zh_4x6_pdf(shipment_id="FBA00DEMO02", warehouse="DMO2", total_boxes=2)
    boxes, out_pdf = process_fba_pdf(
        src_pdf,
        file_id="f_zh",
        file_name="FBA00DEMO02_demo_zh.pdf",
        options=FbaRedactionOptions(redact_ship_from=True, redact_fba_company=True, auto_add_mic=True),
    )

    assert len(boxes) == 2
    assert boxes[0].lang == "zh"
    assert boxes[0].warehouse_code == "DMO2"
    assert boxes[0].has_made_in_china is False
    assert boxes[0].mic_auto_added is True

    eng = PyMuPDFEngine()
    dims = eng.get_page_dimensions_pt(out_pdf)
    expected_pt = mm_to_pt(100.0)
    for w_pt, h_pt in dims:
        assert abs(w_pt - expected_pt) < 0.05
        assert abs(h_pt - expected_pt) < 0.05

    with pymupdf.open(stream=out_pdf, filetype="pdf") as doc:
        for idx, page in enumerate(doc):
            txt = page.get_text("text")
            assert "虚构测试商贸公司" not in txt
            assert "演示市模拟路88号" not in txt
            assert "虚构跨境卖家有限公司" not in txt
            assert "Amazon Mock FC" in txt
            assert "Made In China" in txt

            img_1bit = eng.render_page_to_1bit(out_pdf, page_index=idx, dpi=203)
            decoded = [item["text"] for item in scan_barcodes_from_image(img_1bit)]
            assert f"FBA00DEMO02U{idx + 1:06d}" in decoded
