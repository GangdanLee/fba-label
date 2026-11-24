"""v0.3.0 批量生产力闭环（CSV 多 SKU 批量套打、自定义纸卷规格校准卡、货代解析规则与试跑器）回归测试。"""

from __future__ import annotations

import base64
import io

from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas

from app.config import mm_to_pt
from app.engines.font_manager import ensure_reportlab_font
from app.engines.pdf_engine import PyMuPDFEngine, detect_non_white_bbox
from app.main import app
from app.printers.simulator import scan_barcodes_from_image


def _build_synthetic_carrier_pdf(lines: list[str]) -> bytes:
    """生成 100% 虚构的自定义版式货代箱唛 PDF。"""
    buf = io.BytesIO()
    w_mm, h_mm = 100.0, 100.0
    c = Canvas(buf, pagesize=(mm_to_pt(w_mm), mm_to_pt(h_mm)))
    font_b = ensure_reportlab_font(prefer_cjk=True, bold=True)
    c.setFont(font_b, 11)
    for idx, line in enumerate(lines):
        c.drawString(mm_to_pt(10), mm_to_pt(h_mm - 18 - idx * 10), line)
    c.showPage()
    c.save()
    return buf.getvalue()


def test_csv_template_and_multi_encoding_parse_with_warnings() -> None:
    client = TestClient(app)

    # 1. 下载 UTF-8-BOM CSV 模板
    tpl_resp = client.get("/api/fnsku/csv-template")
    assert tpl_resp.status_code == 200
    assert tpl_resp.content.startswith(b"\xef\xbb\xbf")
    tpl_text = tpl_resp.content.decode("utf-8-sig")
    assert "sku,fnsku,title,qty" in tpl_text

    # 2. UTF-8-BOM 含中文成色与异常行告警（缺 FNSKU / 非法数量跳过，空数量兜底 1）
    csv_utf8 = (
        "\ufeff"
        "SKU,FNSKU,商品名称,数量\n"
        "SKU-DEMO-A,X000BAT101,新品：防滑硅胶厨具垫，黑色大号,3\n"
        "SKU-NO-FNSKU,,缺少条码的行应告警并跳过,5\n"
        "SKU-BAD-QTY,X000BAT102,二手-测试水壶(黑色),abc\n"
        "SKU-EMPTY-QTY,X000BAT103,二手-测试水壶(黑色),\n"
    ).encode("utf-8")
    r1 = client.post("/api/fnsku/parse-csv", files={"file": ("batch_utf8.csv", csv_utf8, "text/csv")})
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert b1["total_skus"] == 2
    assert b1["total_labels"] == 4  # 3 + 空数量兜底 1
    assert b1["items"][0]["fnsku"] == "X000BAT101"
    assert b1["items"][0]["title"].startswith("New - ")
    assert "，" not in b1["items"][0]["title"]
    assert b1["items"][1]["fnsku"] == "X000BAT103"
    assert b1["items"][1]["qty"] == 1
    assert len(b1["warnings"]) >= 2

    # 3. GB18030 编码 + 中文列别名校验
    csv_gb = (
        "货号,条码,标题,打印张数\n"
        "SKU-GB-01,X000GB1803,新品：折叠桌面收纳盒（白色）,6\n"
    ).encode("gb18030")
    r2 = client.post("/api/fnsku/parse-csv", files={"file": ("batch_gb.csv", csv_gb, "text/csv")})
    assert r2.status_code == 200, r2.text
    b2 = r2.json()
    assert b2["total_skus"] == 1
    assert b2["total_labels"] == 6
    assert b2["items"][0]["fnsku"] == "X000GB1803"
    assert b2["items"][0]["title"].startswith("New - ")

    # 4. TSV 制表符分隔校验
    tsv_bytes = "sku\tfnsku\ttitle\tqty\nTSV-01\tX000TSV999\tDemo TSV Bottle\t2\n".encode("utf-8")
    r3 = client.post("/api/fnsku/parse-csv", files={"file": ("batch.tsv", tsv_bytes, "text/tab-separated-values")})
    assert r3.status_code == 200, r3.text
    assert r3.json()["items"][0] == {
        "sku": "TSV-01",
        "fnsku": "X000TSV999",
        "title": "Demo TSV Bottle",
        "qty": 2,
    }


def test_render_batch_double_row_page_break_and_continuous_zxing() -> None:
    client = TestClient(app)
    template_elements = [
        {
            "id": "el_bc",
            "type": "barcode1d",
            "name": "主条码",
            "x": 3.0,
            "y": 1.5,
            "w": 44.0,
            "h": 14.0,
            "code": "X000ORIGIN",
            "show_text": True,
            "font_size": 8.0,
        },
        {
            "id": "el_qr",
            "type": "qrcode",
            "name": "溯源二维码",
            "x": 40.0,
            "y": 17.0,
            "w": 8.0,
            "h": 8.0,
            "code": "X000ORIGIN",
        },
        {
            "id": "el_title",
            "type": "text",
            "name": "商品名称",
            "x": 3.0,
            "y": 16.5,
            "w": 35.0,
            "h": 7.5,
            "text": "Original Title",
            "font_size": 7.0,
        },
        {
            "id": "el_mic",
            "type": "text",
            "name": "产地合规标",
            "x": 3.0,
            "y": 25.0,
            "w": 26.0,
            "h": 3.6,
            "text": "Made in China",
            "font_size": 7.0,
            "bold": True,
        },
    ]
    items = [
        {"sku": "SKU-A", "fnsku": "X000BAT001", "title": "New - Silicone Spatula Red", "qty": 3},
        {"sku": "SKU-B", "fnsku": "X000BAT002", "title": "New - Silicone Spatula Blue", "qty": 2},
    ]

    # A. pageBreakBetweenSkus=True: SKU A(3张->2页，P2右栏留白防错贴) + SKU B(2张->1页) = 3页
    resp_break = client.post(
        "/api/fnsku/render-batch",
        json={
            "templateElements": template_elements,
            "items": items,
            "widthMm": 50.0,
            "heightMm": 30.0,
            "layoutType": "double",
            "colGapMm": 2.0,
            "offsetXMm": 0.0,
            "offsetYMm": 0.0,
            "dpi": 203,
            "pageBreakBetweenSkus": True,
        },
    )
    assert resp_break.status_code == 200, resp_break.text
    jb = resp_break.json()
    assert jb["page_count"] == 3
    assert jb["total_labels"] == 5
    assert jb["total_skus"] == 2

    pdf_break = base64.b64decode(jb["pdf_b64"])
    eng = PyMuPDFEngine()
    dims = eng.get_page_dimensions_pt(pdf_break)
    assert len(dims) == 3

    # P1: 左右栏均为 X000BAT001，条码与同步 QR 码均已替换且 Made in China 文本保留
    text_p0 = eng.extract_text_per_page(pdf_break)[0]
    assert "Made in China" in text_p0
    assert "Silicone Spatula Red" in text_p0
    img_p0 = eng.render_page_to_1bit(pdf_break, page_index=0, dpi=203)
    p0_left_codes = [r["text"] for r in scan_barcodes_from_image(img_p0.crop((0, 0, 400, 240)))]
    p0_right_codes = [r["text"] for r in scan_barcodes_from_image(img_p0.crop((416, 0, 816, 240)))]
    assert p0_left_codes.count("X000BAT001") >= 2, f"P1 左栏应含同步替换的条码+QR: {p0_left_codes}"
    assert p0_right_codes.count("X000BAT001") >= 2, f"P1 右栏应含同步替换的条码+QR: {p0_right_codes}"
    assert "X000ORIGIN" not in p0_left_codes + p0_right_codes

    # P2: 左栏 X000BAT001，右栏必须完全留白
    img_p1 = eng.render_page_to_1bit(pdf_break, page_index=1, dpi=203)
    p1_left_codes = [r["text"] for r in scan_barcodes_from_image(img_p1.crop((0, 0, 400, 240)))]
    assert p1_left_codes.count("X000BAT001") >= 2
    assert "X000ORIGIN" not in p1_left_codes
    assert detect_non_white_bbox(img_p1.crop((416, 0, 816, 240)).convert("L"), pad_px=0) is None

    # P3: 左右栏均为 X000BAT002
    img_p2 = eng.render_page_to_1bit(pdf_break, page_index=2, dpi=203)
    p2_left_codes = [r["text"] for r in scan_barcodes_from_image(img_p2.crop((0, 0, 400, 240)))]
    p2_right_codes = [r["text"] for r in scan_barcodes_from_image(img_p2.crop((416, 0, 816, 240)))]
    assert p2_left_codes.count("X000BAT002") >= 2, f"P3 左栏应含同步替换的条码+QR: {p2_left_codes}"
    assert p2_right_codes.count("X000BAT002") >= 2, f"P3 右栏应含同步替换的条码+QR: {p2_right_codes}"
    assert "X000ORIGIN" not in p2_left_codes + p2_right_codes

    # B. pageBreakBetweenSkus=False: 连续排布 P2 左为 SKU A 右为 SKU B，P3 左为 SKU B 右留白
    resp_cont = client.post(
        "/api/fnsku/render-batch",
        json={
            "templateElements": template_elements,
            "items": items,
            "widthMm": 50.0,
            "heightMm": 30.0,
            "layoutType": "double",
            "colGapMm": 2.0,
            "offsetXMm": 0.0,
            "offsetYMm": 0.0,
            "dpi": 203,
            "pageBreakBetweenSkus": False,
        },
    )
    assert resp_cont.status_code == 200, resp_cont.text
    jc = resp_cont.json()
    assert jc["page_count"] == 3
    pdf_cont = base64.b64decode(jc["pdf_b64"])
    img_c1 = eng.render_page_to_1bit(pdf_cont, page_index=1, dpi=203)
    assert "X000BAT001" in [r["text"] for r in scan_barcodes_from_image(img_c1.crop((0, 0, 400, 240)))]
    assert "X000BAT002" in [r["text"] for r in scan_barcodes_from_image(img_c1.crop((416, 0, 816, 240)))]
    img_c2 = eng.render_page_to_1bit(pdf_cont, page_index=2, dpi=203)
    assert "X000BAT002" in [r["text"] for r in scan_barcodes_from_image(img_c2.crop((0, 0, 400, 240)))]
    assert detect_non_white_bbox(img_c2.crop((416, 0, 816, 240)).convert("L"), pad_px=0) is None


def test_custom_calibration_profiles_card_zxing_and_builtin_guard() -> None:
    client = TestClient(app)
    eng = PyMuPDFEngine()

    custom_specs = [
        {
            "spec_key": "40x30_double",
            "label_width_mm": 40.0,
            "label_height_mm": 30.0,
            "cols": 2,
            "col_gap_mm": 2.0,
            "row_gap_mm": 2.0,
            "safe_width_mm": 36.0,
            "safe_height_mm": 26.0,
            "offset_x_mm": 0.0,
            "offset_y_mm": 0.0,
            "darkness": 8,
            "print_speed": 4,
            "preferred_channel": "tspl_raw",
            "printer_name": "",
            "protocol": "tspl",
            "dpi": 203,
            "connection_type": "os_queue",
            "network_host": "",
            "network_port": 9100,
        },
        {
            "spec_key": "100x150_single",
            "label_width_mm": 100.0,
            "label_height_mm": 150.0,
            "cols": 1,
            "col_gap_mm": 0.0,
            "row_gap_mm": 2.0,
            "safe_width_mm": 96.0,
            "safe_height_mm": 146.0,
            "offset_x_mm": 0.0,
            "offset_y_mm": 0.0,
            "darkness": 10,
            "print_speed": 4,
            "preferred_channel": "tspl_raw",
            "printer_name": "",
            "protocol": "zpl",
            "dpi": 300,
            "connection_type": "os_queue",
            "network_host": "",
            "network_port": 9100,
        },
    ]

    for prof in custom_specs:
        r_create = client.post("/api/hardware/profiles", json=prof)
        assert r_create.status_code == 200, r_create.text
        assert r_create.json()["spec_key"] == prof["spec_key"]

    keys = [p["spec_key"] for p in client.get("/api/hardware/profiles").json()]
    assert "40x30_double" in keys
    assert "100x150_single" in keys

    # 验证 40x30 双排校准卡：总宽 82x30mm，203dpi 下左右双栏均能被 zxing 扫码
    c1 = client.post("/api/hardware/calibration-card", json={"spec_key": "40x30_double"})
    assert c1.status_code == 200, c1.text
    pdf_4030 = base64.b64decode(c1.json()["pdf_b64"])
    w40, h30 = eng.get_page_dimensions_pt(pdf_4030)[0]
    assert abs(w40 - mm_to_pt(82.0)) < 0.2
    assert abs(h30 - mm_to_pt(30.0)) < 0.2
    img_4030 = eng.render_page_to_1bit(pdf_4030, page_index=0, dpi=203)
    mid = img_4030.width // 2
    left_codes = [r["text"] for r in scan_barcodes_from_image(img_4030.crop((0, 0, mid, img_4030.height)))]
    right_codes = [r["text"] for r in scan_barcodes_from_image(img_4030.crop((mid, 0, img_4030.width, img_4030.height)))]
    assert any(code.startswith("CAL") for code in left_codes), f"40x30 双排左栏校准卡扫码失败: {left_codes}"
    assert any(code.startswith("CAL") for code in right_codes), f"40x30 双排右栏校准卡扫码失败: {right_codes}"

    # 验证 100x150 单排 300dpi ZPL 校准卡可扫码且不越界
    c2 = client.post("/api/hardware/calibration-card", json={"spec_key": "100x150_single"})
    assert c2.status_code == 200, c2.text
    assert c2.json()["dpi"] == 300
    assert c2.json()["protocol"] == "zpl"
    pdf_100150 = base64.b64decode(c2.json()["pdf_b64"])
    w100, h150 = eng.get_page_dimensions_pt(pdf_100150)[0]
    assert abs(w100 - mm_to_pt(100.0)) < 0.2
    assert abs(h150 - mm_to_pt(150.0)) < 0.2
    img_100150 = eng.render_page_to_1bit(pdf_100150, page_index=0, dpi=300)
    assert "CAL100DEMO" in [r["text"] for r in scan_barcodes_from_image(img_100150)]

    # 内置档必须被保护返回 400
    assert client.delete("/api/hardware/profiles/50x30_double").status_code == 400
    assert client.delete("/api/hardware/profiles/100x100_single").status_code == 400

    # 自定义档可正常删除
    assert client.delete("/api/hardware/profiles/40x30_double").status_code == 200
    assert client.delete("/api/hardware/profiles/100x150_single").status_code == 200
    keys_after = [p["spec_key"] for p in client.get("/api/hardware/profiles").json()]
    assert "40x30_double" not in keys_after
    assert "100x150_single" not in keys_after


def test_carrier_rules_crud_test_runner_and_real_pdf_priority() -> None:
    client = TestClient(app)

    # 1. 默认列表包含 rule_default 且禁止删除
    rules = client.get("/api/box/carrier-rules").json()
    assert any(r["id"] == "rule_default" for r in rules)
    assert client.delete("/api/box/carrier-rules/rule_default").status_code == 400

    # 2. 坏正则必须返回 400
    bad_resp = client.post(
        "/api/box/carrier-rules",
        json={
            "id": "",
            "name": "坏正则规则",
            "shipment_regex": "[unclosed(",
            "warehouse_regex": "",
            "ctn_regex": "",
            "default_rotate": 0,
            "enabled": True,
        },
    )
    assert bad_resp.status_code == 400

    # 3. 保存高优先级自定义货代正则
    save_resp = client.post(
        "/api/box/carrier-rules",
        json={
            "id": "",
            "name": "海运专线箱唛定制规则",
            "shipment_regex": r"CUST_JOB[:：\s]*(FBA[A-Z0-9]{6,12})",
            "warehouse_regex": r"HUB[:：\s]*([A-Z]{3}\d)",
            "ctn_regex": r"PKG\s*(\d+)\s*/\s*(\d+)",
            "default_rotate": 0,
            "enabled": True,
        },
    )
    assert save_resp.status_code == 200, save_resp.text
    saved = save_resp.json()
    rule_id = saved["id"]
    assert rule_id and rule_id != "rule_default"

    # 4. 在线试跑器校验提取结果
    test_resp = client.post(
        "/api/box/carrier-rules/test",
        json={
            "sample_text": "CUST_JOB: FBA88CUST9\nHUB: ONT8\nPKG 2 / 4",
            "file_name": "carrier_custom.pdf",
        },
    )
    assert test_resp.status_code == 200, test_resp.text
    assert test_resp.json() == {
        "shipment_id": "FBA88CUST9",
        "warehouse_code": "ONT8",
        "box_index": 2,
        "total_boxes": 4,
    }

    # 5. 上传真实合成 PDF 至 /api/box/process-carrier，确认自动应用该自定义规则
    car_pdf = _build_synthetic_carrier_pdf(["CUST_JOB: FBA88CUST9", "HUB: ONT8", "PKG 3 / 4"])
    proc_resp = client.post(
        "/api/box/process-carrier",
        files={"file": ("carrier_demo.pdf", car_pdf, "application/pdf")},
        data={"offset_x_mm": "0", "offset_y_mm": "0"},
    )
    assert proc_resp.status_code == 200, proc_resp.text
    item0 = proc_resp.json()["items"][0]
    assert item0["shipment_id"] == "FBA88CUST9"
    assert item0["warehouse_code"] == "ONT8"
    assert item0["box_index"] == 3
    assert item0["total_boxes"] == 4

    # 6. 删除自定义规则
    del_resp = client.delete(f"/api/box/carrier-rules/{rule_id}")
    assert del_resp.status_code == 200
    assert all(r["id"] != rule_id for r in client.get("/api/box/carrier-rules").json())
