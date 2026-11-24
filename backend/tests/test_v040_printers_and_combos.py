"""v0.4.0 芯烨 420B / 佳博兼容、独立 FBA/箱唛张数配比与默认偏好持久化回归测试。"""

from __future__ import annotations

import base64
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import ImageOps

from app import db
from app.engines.fba_processor import process_fba_pdf
from app.engines.pairing_engine import pair_and_validate
from app.main import app
from app.models.schemas import CalibrationProfile, CarrierBoxMeta, FbaBoxMeta, PairingRequest
from app.printers.registry import infer_printer_brand_note, infer_printer_hints
from app.printers.simulator import scan_barcodes_from_image
from app.printers.tspl_encoder import encode_pdf_pages_to_tspl, parse_and_decode_tspl
from tests.conftest import build_synthetic_fba_en_pdf


def test_xprinter_gprinter_brand_dpi_and_note_hints() -> None:
    cases = [
        ("芯烨420B", ("tspl", 203, True), "芯烨"),
        ("Xprinter XP-420B", ("tspl", 203, True), "芯烨"),
        ("Xprinter XP420B", ("tspl", 203, True), "芯烨"),
        ("XP-TT437B", ("tspl", 300, True), "芯烨"),
        ("4BARCODE 4B-2054A", ("tspl", 203, True), "4BARCODE"),
        ("佳博 GP-1324D", ("tspl", 203, True), "佳博"),
        ("佳博 GP-1134T", ("tspl", 300, True), "佳博"),
        ("Gprinter GP-3120TU", ("tspl", 203, True), "佳博"),
        ("Gainscha GS-3405T", ("tspl", 300, True), "佳博"),
    ]
    for name, expected_hints, expected_brand in cases:
        assert infer_printer_hints(name) == expected_hints, f"协议/DPI识别错误: {name}"
        brand_label, usage_tip = infer_printer_brand_note(name)
        assert expected_brand in brand_label, f"品牌简称识别缺失: {name} -> {brand_label}"
        assert usage_tip, f"适配排错提示不应为空: {name}"


def test_tspl_negative_offset_reset_header_and_invert_bitmap() -> None:
    _, fba_pdf = process_fba_pdf(build_synthetic_fba_en_pdf("FBA00NEG01", "DMO1", 1), "neg1", "neg1.pdf")

    # 1. 负偏移应转为画布像素平移而保持 BITMAP 坐标非负，并携带 REFERENCE 0,0 与 SET TEAR ON
    raw_neg = encode_pdf_pages_to_tspl(
        fba_pdf,
        width_mm=100.0,
        height_mm=100.0,
        dpi=203,
        offset_x_mm=-1.5,
        offset_y_mm=-1.0,
        direction=0,
        invert_bitmap=False,
    )
    assert b"REFERENCE 0,0\r\n" in raw_neg
    assert b"SET TEAR ON\r\n" in raw_neg
    dec_neg = parse_and_decode_tspl(raw_neg)
    assert len(dec_neg) == 1
    assert dec_neg[0].bitmap_x == 0
    assert dec_neg[0].bitmap_y == 0
    assert dec_neg[0].direction == 0
    codes_neg = [r["text"] for r in scan_barcodes_from_image(dec_neg[0].image)]
    assert "FBA00NEG01U000001" in codes_neg, f"负偏移画布平移后无法扫码: {codes_neg}"

    # 2. 非 8 像素整除宽度 (40.5mm -> 324 dots) 下标准极性与反色位图精确按位取反且补白无黑边
    raw_norm = encode_pdf_pages_to_tspl(
        fba_pdf,
        width_mm=40.5,
        height_mm=30.0,
        dpi=203,
        invert_bitmap=False,
    )
    raw_inv = encode_pdf_pages_to_tspl(
        fba_pdf,
        width_mm=40.5,
        height_mm=30.0,
        dpi=203,
        invert_bitmap=True,
    )
    dec_norm = parse_and_decode_tspl(raw_norm)[0]
    dec_inv = parse_and_decode_tspl(raw_inv)[0]
    assert dec_inv.bitmap_payload == bytes(b ^ 0xFF for b in dec_norm.bitmap_payload)
    # 末尾补白位 324..328 在反色模式下必须全为 0（不打印点），取最后 4 个 bit 应均为空白(0)
    last_byte_row0 = dec_inv.bitmap_payload[dec_inv.width_bytes - 1]
    assert (last_byte_row0 & 0x0F) == 0


def test_asymmetric_fba_and_carrier_copy_combos_and_single_box_override() -> None:
    fba_boxes = [
        FbaBoxMeta(file_id="f1", file_name="f.pdf", page_index=0, box_index=1, total_boxes=2, shipment_id="FBA88CMB01", warehouse_code="ONT8"),
        FbaBoxMeta(file_id="f1", file_name="f.pdf", page_index=1, box_index=2, total_boxes=2, shipment_id="FBA88CMB01", warehouse_code="ONT8"),
    ]
    car_boxes = [
        CarrierBoxMeta(file_id="c1", file_name="c.pdf", page_index=0, box_index=1, total_boxes=2, shipment_id="FBA88CMB01", warehouse_code="ONT8"),
        CarrierBoxMeta(file_id="c1", file_name="c.pdf", page_index=1, box_index=2, total_boxes=2, shipment_id="FBA88CMB01", warehouse_code="ONT8"),
    ]

    # A. FBA 2 + 箱唛 1：按箱成组 / 轮流交替 / 分组先后
    r_group = pair_and_validate(
        PairingRequest(
            fba_boxes=fba_boxes,
            carrier_boxes=car_boxes,
            work_mode="paired",
            order_mode="per_box_group",
            default_fba_copies=2,
            default_carrier_copies=1,
        )
    )
    assert r_group.can_print is True
    assert [(q.kind, q.box_index) for q in r_group.queue] == [
        ("fba", 1), ("fba", 1), ("carrier", 1),
        ("fba", 2), ("fba", 2), ("carrier", 2),
    ]

    r_inter = pair_and_validate(
        PairingRequest(
            fba_boxes=fba_boxes,
            carrier_boxes=car_boxes,
            work_mode="paired",
            order_mode="interleave",
            default_fba_copies=2,
            default_carrier_copies=1,
        )
    )
    assert [(q.kind, q.box_index) for q in r_inter.queue] == [
        ("fba", 1), ("carrier", 1), ("fba", 1),
        ("fba", 2), ("carrier", 2), ("fba", 2),
    ]

    r_split = pair_and_validate(
        PairingRequest(
            fba_boxes=fba_boxes,
            carrier_boxes=car_boxes,
            work_mode="paired",
            order_mode="split_all",
            default_fba_copies=2,
            default_carrier_copies=1,
        )
    )
    assert [(q.kind, q.box_index) for q in r_split.queue] == [
        ("fba", 1), ("fba", 1), ("fba", 2), ("fba", 2),
        ("carrier", 1), ("carrier", 2),
    ]

    # B. 全局 4+2 + 第 2 箱自定义 FBA=1, 箱唛=0
    r_ov = pair_and_validate(
        PairingRequest(
            fba_boxes=fba_boxes,
            carrier_boxes=car_boxes,
            work_mode="paired",
            order_mode="per_box_group",
            default_fba_copies=4,
            default_carrier_copies=2,
            box_fba_copies={"FBA88CMB01:2": 1},
            box_carrier_copies={"FBA88CMB01:2": 0},
        )
    )
    assert r_ov.total_sheets == 7
    assert [q.label for q in r_ov.queue] == ["F1", "F1", "F1", "F1", "M1", "M1", "F2"]

    # C. 箱唛设为 0 时，carrier_only 应拦截，paired 仍可出 FBA
    r_zero_car = pair_and_validate(
        PairingRequest(
            fba_boxes=fba_boxes,
            carrier_boxes=car_boxes,
            work_mode="carrier_only",
            default_fba_copies=2,
            default_carrier_copies=0,
        )
    )
    assert r_zero_car.can_print is False


def test_box_preferences_persistence_and_v030_sqlite_migration(tmp_path: Path) -> None:
    client = TestClient(app)

    # 1. 默认外箱偏好应为 FBA 2 + 箱唛 1（按箱成组）
    r_def = client.get("/api/box/preferences")
    assert r_def.status_code == 200
    assert r_def.json()["default_fba_copies"] == 2
    assert r_def.json()["default_carrier_copies"] == 1
    assert r_def.json()["order_mode"] == "per_box_group"

    # 2. 双 0 校验返回 400
    r_bad = client.put(
        "/api/box/preferences",
        json={
            "default_fba_copies": 0,
            "default_carrier_copies": 0,
            "order_mode": "per_box_group",
            "work_mode": "paired",
            "redact_ship_from": True,
            "redact_fba_company": True,
            "redact_headers": False,
            "auto_add_mic": True,
        },
    )
    assert r_bad.status_code == 400

    # 3. 保存新组合后重新获取（跨连接）持久化留存
    new_prefs = {
        "default_fba_copies": 3,
        "default_carrier_copies": 1,
        "order_mode": "interleave",
        "work_mode": "paired",
        "redact_ship_from": True,
        "redact_fba_company": False,
        "redact_headers": True,
        "auto_add_mic": False,
    }
    assert client.put("/api/box/preferences", json=new_prefs).status_code == 200
    client2 = TestClient(app)
    r_after = client2.get("/api/box/preferences")
    assert r_after.status_code == 200
    data_after = r_after.json()
    for k, v in new_prefs.items():
        assert data_after[k] == v
    assert data_after["group_by"] == "shipment"
    assert data_after["insert_separator_pages"] is False
    assert data_after["box_paper_size"] == "100x100"
    assert data_after["awd_apply_redaction"] is False

    # 4. 模拟 v0.3.0 旧表无 tspl_direction / invert_bitmap 列时自动迁移并支持 /execute-print 透传
    legacy_db = tmp_path / "legacy_v030.db"
    conn = sqlite3.connect(str(legacy_db))
    conn.executescript(
        """
        CREATE TABLE calibration_profiles (
            spec_key TEXT PRIMARY KEY,
            label_width_mm REAL NOT NULL,
            label_height_mm REAL NOT NULL,
            cols INTEGER NOT NULL DEFAULT 1,
            col_gap_mm REAL NOT NULL DEFAULT 0.0,
            row_gap_mm REAL NOT NULL DEFAULT 2.0,
            safe_width_mm REAL NOT NULL DEFAULT 98.0,
            safe_height_mm REAL NOT NULL DEFAULT 98.0,
            offset_x_mm REAL NOT NULL DEFAULT 0.0,
            offset_y_mm REAL NOT NULL DEFAULT 0.0,
            darkness INTEGER NOT NULL DEFAULT 8,
            print_speed INTEGER NOT NULL DEFAULT 4,
            preferred_channel TEXT NOT NULL DEFAULT 'tspl_raw',
            printer_name TEXT NOT NULL DEFAULT '',
            protocol TEXT NOT NULL DEFAULT 'tspl',
            dpi INTEGER NOT NULL DEFAULT 203,
            connection_type TEXT NOT NULL DEFAULT 'os_queue',
            network_host TEXT NOT NULL DEFAULT '',
            network_port INTEGER NOT NULL DEFAULT 9100
        );
        INSERT INTO calibration_profiles (
            spec_key, label_width_mm, label_height_mm, printer_name
        ) VALUES ('100x100_single', 100.0, 100.0, 'Xprinter XP-420B');
        """
    )
    conn.commit()
    conn.close()

    db.init_db(legacy_db)
    migrated = {p.spec_key: p for p in db.list_calibration_profiles(legacy_db)}
    p100 = migrated["100x100_single"]
    assert p100.printer_name == "Xprinter XP-420B"
    assert p100.tspl_direction == 1
    assert p100.invert_bitmap is False

    # 保存 direction=0 / invert_bitmap=True 并经由 /execute-print 干跑确认生效
    updated = CalibrationProfile(**{**p100.model_dump(), "tspl_direction": 0, "invert_bitmap": True})
    assert client.put("/api/hardware/profiles/100x100_single", json=updated.model_dump()).status_code == 200
    _, fba_pdf = process_fba_pdf(build_synthetic_fba_en_pdf("FBA00XP420", "DMO1", 1), "xp", "xp.pdf")
    exec_resp = client.post(
        "/api/hardware/execute-print",
        json={
            "pdf_b64": base64.b64encode(fba_pdf).decode("ascii"),
            "spec_key": "100x100_single",
            "channel": "tspl_raw",
            "printer_name": "Xprinter XP-420B",
            "dry_run": True,
            "batch": {
                "batch_type": "box_paired",
                "shipment_id": "FBA00XP420",
                "warehouse_code": "DMO1",
                "spec_key": "100x100_single",
                "total_units_or_boxes": 1,
                "copies_per_box": 2,
                "order_mode": "per_box_group",
                "channel": "tspl_raw",
                "summary": "XP-420B 干跑校验",
            },
        },
    )
    assert exec_resp.status_code == 200, exec_resp.text
    assert exec_resp.json()["printer_result"]["offline_dryrun"] is True
