"""v0.5.0 跨仓按 SKU 归集、分隔页/CSV/ZIP 导出、仓点词典及本机 ZIP 备份迁移全链单测。"""

from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

import pymupdf
import zxingcpp
from fastapi.testclient import TestClient
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from app import db
from app.config import get_data_dir, mm_to_pt
from app.engines.amazon_fc_codes import extract_amazon_fc_code
from app.engines.code128 import draw_barcode1d_on_reportlab, generate_qrcode_pil
from app.engines.fba_processor import _extract_sku_info
from app.engines.font_manager import ensure_reportlab_font
from app.main import app
from tests.conftest import build_synthetic_carrier_pdf


def _build_multi_sku_fba_pdf(
    shipment_id: str,
    warehouse: str,
    box_specs: list[tuple[int, str, bool]],
) -> bytes:
    """生成含 Single SKU 与 Mixed SKU 的 100% 虚构 FBA PDF。"""
    buf = io.BytesIO()
    w_mm, h_mm = 100.0, 100.0
    total_boxes = len(box_specs)
    c = Canvas(buf, pagesize=(mm_to_pt(w_mm), mm_to_pt(h_mm)))
    font_reg = ensure_reportlab_font(prefer_cjk=False, bold=False)
    font_bold = ensure_reportlab_font(prefer_cjk=False, bold=True)

    for box_no, sku_label, is_mixed in box_specs:
        box_id = f"{shipment_id}U{box_no:06d}"
        c.setFont(font_bold, 13)
        c.drawString(mm_to_pt(4), mm_to_pt(h_mm - 8), "FBA")
        c.setFont(font_bold, 9)
        c.drawRightString(mm_to_pt(96), mm_to_pt(h_mm - 8), f"Box {box_no} of {total_boxes} - 28lb")
        c.line(mm_to_pt(4), mm_to_pt(h_mm - 10), mm_to_pt(96), mm_to_pt(h_mm - 10))

        c.setFont(font_bold, 7.5)
        c.drawString(mm_to_pt(4), mm_to_pt(h_mm - 14.5), "SHIP FROM:")
        c.setFont(font_reg, 7.0)
        c.drawString(mm_to_pt(4), mm_to_pt(h_mm - 18.5), "Demo Sender Warehouse")
        c.drawString(mm_to_pt(4), mm_to_pt(h_mm - 22.0), "88 Mock Street, Demo City")

        c.setFont(font_bold, 7.5)
        c.drawString(mm_to_pt(52), mm_to_pt(h_mm - 14.5), "SHIP TO:")
        c.setFont(font_bold, 6.8)
        c.drawString(mm_to_pt(52), mm_to_pt(h_mm - 18.5), "FBA: Fictional Seller Co")
        c.setFont(font_reg, 7.0)
        c.drawString(mm_to_pt(52), mm_to_pt(h_mm - 22.0), "Amazon FC")
        c.drawString(mm_to_pt(52), mm_to_pt(h_mm - 25.5), f"Demo Hub {warehouse} US")

        c.setFillColorRGB(0, 0, 0)
        c.rect(mm_to_pt(4), mm_to_pt(h_mm - 32.5), mm_to_pt(92), mm_to_pt(4.5), stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont(font_bold, 6.5)
        c.drawString(mm_to_pt(5.5), mm_to_pt(h_mm - 31.2), f"FBA STA (DEMO) - {warehouse}")

        c.setFillColorRGB(0, 0, 0)
        draw_barcode1d_on_reportlab(
            c=c,
            code=box_id,
            x_mm=4.0,
            y_top_mm=36.0,
            w_mm=66.0,
            h_mm=28.0,
            page_h_mm=h_mm,
            show_text=True,
            font_size_pt=7.5,
        )
        qr_img = generate_qrcode_pil(box_id, scale=4)
        c.drawImage(
            ImageReader(qr_img),
            mm_to_pt(73.0),
            mm_to_pt(h_mm - 62.0),
            width=mm_to_pt(22.0),
            height=mm_to_pt(22.0),
            preserveAspectRatio=True,
        )

        c.setFont(font_bold, 8)
        c.drawString(mm_to_pt(6), mm_to_pt(h_mm - 76.0), "Made In China")
        if is_mixed:
            c.drawRightString(mm_to_pt(94), mm_to_pt(h_mm - 76.0), "Mixed SKU - Qty 40")
        else:
            c.drawRightString(mm_to_pt(94), mm_to_pt(h_mm - 76.0), f"Single SKU: {sku_label}")
        c.drawCentredString(mm_to_pt(50), mm_to_pt(h_mm - 92.0), "PLEASE LEAVE THIS LABEL UNCOVERED")
        c.showPage()

    c.save()
    return buf.getvalue()


def test_fc_dictionary_noise_filtering_and_sku_extraction() -> None:
    # 仓点词典应跳过 BOX1/CTN2/QTY5 等三字母+数字干扰词，命中高频真实仓点 ONT8
    assert extract_amazon_fc_code("BOX1 CTN2 QTY5 PKG9 Ship To: ONT8 USA") == "ONT8"
    # 测试虚拟仓点 DMO1 不被噪声名单误杀
    assert extract_amazon_fc_code("Ship To: DMO1 Mock Center") == "DMO1"

    assert _extract_sku_info("Header\nSingle SKU\nSKU-ALPHA-01\nQty 50") == ("SKU-ALPHA-01", False)
    assert _extract_sku_info("SKU: DEMO-BETA-02 | Qty 20") == ("DEMO-BETA-02", False)
    assert _extract_sku_info("DEMO-GAMMA-03 · Qty 100") == ("DEMO-GAMMA-03", False)
    assert _extract_sku_info("Mixed SKUs\nPlease inspect") == (None, True)


def test_cross_warehouse_sku_grouping_separators_csv_and_zip() -> None:
    client = TestClient(app)

    # 跨两仓混排：ONT8 含共享款+独有款，SCK4 含共享款+混装箱
    fba_ont8 = _build_multi_sku_fba_pdf(
        "FBA00SKU01",
        "ONT8",
        [(1, "SKU-SHARE-01", False), (2, "SKU-ONLY-A", False)],
    )
    fba_sck4 = _build_multi_sku_fba_pdf(
        "FBA00SKU02",
        "SCK4",
        [(1, "SKU-SHARE-01", False), (2, "", True)],
    )
    car_ont8 = build_synthetic_carrier_pdf("FBA00SKU01", "ONT8", 2)
    car_sck4 = build_synthetic_carrier_pdf("FBA00SKU02", "SCK4", 2)

    r_f1 = client.post("/api/box/process-fba", files={"file": ("ONT8_box.pdf", fba_ont8, "application/pdf")}).json()
    r_f2 = client.post("/api/box/process-fba", files={"file": ("SCK4_box.pdf", fba_sck4, "application/pdf")}).json()
    r_c1 = client.post("/api/box/process-carrier", files={"file": ("ONT8_car.pdf", car_ont8, "application/pdf")}).json()
    r_c2 = client.post("/api/box/process-carrier", files={"file": ("SCK4_car.pdf", car_sck4, "application/pdf")}).json()

    r_pair = client.post(
        "/api/box/pair",
        json={
            "fba_boxes": [*r_f1["boxes"], *r_f2["boxes"]],
            "carrier_boxes": [*r_c1["items"], *r_c2["items"]],
            "group_by": "sku",
            "insert_separator_pages": True,
            "work_mode": "paired",
            "order_mode": "per_box_group",
            "default_fba_copies": 2,
            "default_carrier_copies": 1,
            "active_shipment_id": "SKU-SHARE-01",
        },
    )
    assert r_pair.status_code == 200
    paired = r_pair.json()
    assert paired["group_by"] == "sku"
    group_ids = [g["shipment_id"] for g in paired["groups"]]
    assert set(group_ids) == {"SKU-SHARE-01", "SKU-ONLY-A", "__MIXED_SKU__"}

    share_grp = next(g for g in paired["groups"] if g["shipment_id"] == "SKU-SHARE-01")
    assert share_grp["warehouses"] == ["ONT8", "SCK4"]
    assert len(share_grp["pairs"]) == 2
    assert share_grp["pairs"][0]["warehouse_code"] == "ONT8"
    assert share_grp["pairs"][1]["warehouse_code"] == "SCK4"

    # 队列：2 张分隔提示页 + 6 张标签页 = 8 页
    queue = paired["queue"]
    assert len(queue) == 8
    assert queue[0]["is_separator"] is True and queue[0]["warehouse_code"] == "ONT8"
    assert queue[4]["is_separator"] is True and queue[4]["warehouse_code"] == "SCK4"
    assert [q["kind"] for q in queue if not q["is_separator"]] == ["fba", "fba", "carrier", "fba", "fba", "carrier"]

    # 1. 验证 UTF-8-BOM 核对明细 CSV
    r_csv = client.post("/api/box/export-manifest-csv", json={"queue": queue, "title": "SKU-SHARE-01"})
    assert r_csv.status_code == 200
    csv_bytes = base64.b64decode(r_csv.json()["csv_b64"])
    assert csv_bytes.startswith(b"\xef\xbb\xbf")
    csv_text = csv_bytes.decode("utf-8-sig")
    assert "ONT8_box.pdf" in csv_text and "SCK4_box.pdf" in csv_text
    assert "SKU-SHARE-01" in csv_text

    # 2. 验证按 SKU 拆分导出 ZIP + 内含分隔页与 zxing-cpp 条码可读
    r_zip = client.post(
        "/api/box/export-sku-zip",
        json={
            "fba_pdfs_b64": {r_f1["file_id"]: r_f1["pdf_b64"], r_f2["file_id"]: r_f2["pdf_b64"]},
            "carrier_pdfs_b64": {r_c1["file_id"]: r_c1["pdf_b64"], r_c2["file_id"]: r_c2["pdf_b64"]},
            "groups": paired["groups"],
            "work_mode": "paired",
            "order_mode": "per_box_group",
            "insert_separator_pages": True,
        },
    )
    assert r_zip.status_code == 200
    z_info = r_zip.json()
    assert z_info["file_count"] == 3
    zip_bytes = base64.b64decode(z_info["zip_b64"])

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        names = zf.namelist()
        assert "出纸核对明细.csv" in names
        share_pdf_name = next(n for n in names if n.startswith("SKU-SHARE-01_") and n.endswith(".pdf"))
        share_pdf = zf.read(share_pdf_name)

        with pymupdf.open(stream=share_pdf, filetype="pdf") as doc:
            assert len(doc) == 8
            # 验证分隔页渲染成功并包含对应仓点
            assert "ONT8" in doc[0].get_text("text")
            assert "SCK4" in doc[4].get_text("text")
            # 验证真实 FBA 页已擦除发件人且 zxing-cpp 扫码可识别
            for page_idx, expected_code in ((1, "FBA00SKU01U000001"), (5, "FBA00SKU02U000001")):
                page = doc[page_idx]
                txt = page.get_text("text")
                assert "Demo Sender Warehouse" not in txt
                assert "Fictional Seller Co" not in txt
                pix = page.get_pixmap(dpi=203, colorspace=pymupdf.csGRAY)
                img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
                codes = [b.text for b in zxingcpp.read_barcodes(img)]
                assert expected_code in codes, f"第 {page_idx+1} 页条码未扫出: {codes}"


def test_system_backup_export_zip_slip_guard_merge_and_replace() -> None:
    client = TestClient(app)

    # 创建自定义 SKU、货代规则与干跑快照
    r_sku = client.post(
        "/api/fnsku/templates",
        json={
            "sku": "BACKUP-SKU-01",
            "fnsku": "X000BACKUP1",
            "title_raw": "Backup Test Item",
            "title_clean": "Backup Test Item",
            "widthMm": 50.0,
            "heightMm": 30.0,
            "layoutType": "double",
            "elements": [],
            "defaultQty": 30,
        },
    )
    assert r_sku.status_code == 200
    sku_id = r_sku.json()["id"]

    r_rule = client.post(
        "/api/box/carrier-rules",
        json={
            "name": "备份校验规则",
            "shipment_regex": r"TEST_SHIP[:：]\s*([A-Z0-9]+)",
            "warehouse_regex": r"TEST_WH[:：]\s*([A-Z]{3}\d)",
            "ctn_regex": r"(\d+)/(\d+)",
            "default_rotate": 0,
            "enabled": True,
        },
    )
    assert r_rule.status_code == 200
    rule_id = r_rule.json()["id"]

    # 触发一次 PDF 导出批次生成快照
    r_prev = client.post(
        "/api/fnsku/render-preview",
        json={
            "elements": [
                {"id": "b1", "type": "barcode1d", "x": 3, "y": 2, "w": 44, "h": 14, "code": "X000BACKUP1", "showText": True, "fontSize": 8}
            ],
            "widthMm": 50.0,
            "heightMm": 30.0,
            "layoutType": "double",
            "colGapMm": 2.0,
            "offsetXMm": 0.0,
            "offsetYMm": 0.0,
            "qty": 2,
        },
    ).json()
    client.post(
        "/api/hardware/execute-print",
        json={
            "pdf_b64": r_prev["pdf_b64"],
            "spec_key": "50x30_double",
            "channel": "pdf_export",
            "dry_run": True,
            "batch": {
                "batch_type": "fnsku",
                "shipment_id": "BACKUP-SKU-01",
                "warehouse_code": "-",
                "spec_key": "50x30_double",
                "total_units_or_boxes": 2,
                "copies_per_box": 1,
                "order_mode": "double",
                "channel": "pdf_export",
                "summary": "备份快照",
                "source_files": ["BACKUP-SKU-01"],
            },
        },
    )

    r_sum = client.get("/api/system/backup/summary")
    assert r_sum.status_code == 200
    assert r_sum.json()["skus_count"] >= 1
    assert r_sum.json()["batches_count"] >= 1

    # 导出完整备份并核验不含本地绝对路径
    r_exp = client.post("/api/system/backup/export", json={"include_snapshots": True})
    assert r_exp.status_code == 200
    exp_zip = base64.b64decode(r_exp.json()["zip_b64"])
    with zipfile.ZipFile(io.BytesIO(exp_zip), "r") as zf:
        assert "manifest.json" in zf.namelist()
        assert "config_data.json" in zf.namelist()
        cfg_text = zf.read("config_data.json").decode("utf-8")
        assert "/Users/" not in cfg_text and "/private/" not in cfg_text
        assert any(n.startswith("snapshots/") and n.endswith(".pdf") for n in zf.namelist())
        cfg_obj = json.loads(cfg_text)
        assert cfg_obj["print_batches"][0]["snapshot_filename"].endswith(".pdf")

    # Zip Slip 路径穿越攻击拒绝
    evil_buf = io.BytesIO()
    with zipfile.ZipFile(evil_buf, "w") as zf:
        zf.writestr("../../evil.txt", b"bad")
        zf.writestr("config_data.json", b'{"skus": []}')
    r_evil = client.post(
        "/api/system/backup/import",
        data={"mode": "merge"},
        files={"file": ("evil.zip", evil_buf.getvalue(), "application/zip")},
    )
    assert r_evil.status_code == 400

    # 删除模板与规则后通过 merge 恢复，并校验 pre_import 备份留底
    assert client.delete(f"/api/fnsku/templates/{sku_id}").status_code == 200
    assert client.delete(f"/api/box/carrier-rules/{rule_id}").status_code == 200
    assert not any(t["sku"] == "BACKUP-SKU-01" for t in client.get("/api/fnsku/templates").json())

    r_merge = client.post(
        "/api/system/backup/import",
        data={"mode": "merge"},
        files={"file": ("backup.zip", exp_zip, "application/zip")},
    )
    assert r_merge.status_code == 200
    assert r_merge.json()["pre_import_backup_name"].startswith("pre_import_")
    assert (get_data_dir() / "backups" / r_merge.json()["pre_import_backup_name"]).is_file()
    assert any(t["sku"] == "BACKUP-SKU-01" for t in client.get("/api/fnsku/templates").json())
    assert any(r["name"] == "备份校验规则" for r in client.get("/api/box/carrier-rules").json())

    # 额外新增一条 SKU 后执行 replace 覆盖恢复，应清空多余数据并保留内置校准档
    client.post(
        "/api/fnsku/templates",
        json={
            "sku": "TEMP-EXTRA-ONLY",
            "fnsku": "X000EXTRA1",
            "title_raw": "Extra",
            "title_clean": "Extra",
            "widthMm": 50.0,
            "heightMm": 30.0,
            "layoutType": "double",
            "elements": [],
            "defaultQty": 10,
        },
    )
    r_rep = client.post(
        "/api/system/backup/import",
        data={"mode": "replace"},
        files={"file": ("backup.zip", exp_zip, "application/zip")},
    )
    assert r_rep.status_code == 200
    tpls_after = client.get("/api/fnsku/templates").json()
    assert not any(t["sku"] == "TEMP-EXTRA-ONLY" for t in tpls_after)
    assert any(t["sku"] == "BACKUP-SKU-01" for t in tpls_after)
    assert len(db.list_calibration_profiles()) >= 2


def test_v050_preferences_group_by_and_separator_persistence() -> None:
    client = TestClient(app)
    payload = {
        "default_fba_copies": 2,
        "default_carrier_copies": 1,
        "group_by": "sku",
        "insert_separator_pages": True,
        "order_mode": "per_box_group",
        "work_mode": "paired",
        "redact_ship_from": True,
        "redact_fba_company": True,
        "redact_headers": False,
        "auto_add_mic": True,
    }
    assert client.put("/api/box/preferences", json=payload).status_code == 200
    client2 = TestClient(app)
    r_get = client2.get("/api/box/preferences")
    assert r_get.status_code == 200
    assert r_get.json()["group_by"] == "sku"
    assert r_get.json()["insert_separator_pages"] is True
