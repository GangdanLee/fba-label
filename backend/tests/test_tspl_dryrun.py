"""M1 测试套件 4：TSPL 裸流逆向解码与扫码闭环 + FastAPI TestClient 端到端接口校验。"""

from __future__ import annotations

import base64
import io
from pathlib import Path
import subprocess
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from app.config import get_snapshots_dir
from app.engines.fba_processor import process_fba_pdf
from app.engines.fnsku_engine import render_fnsku_elements_pdf
from app.engines.pdf_engine import PyMuPDFEngine
from app.main import app
from app.models.schemas import CanvasElement, FnskuRenderRequest
from app.printers.macos_cups import MacOSCupsAdapter
from app.printers.simulator import scan_barcodes_from_image
from app.printers.tspl_encoder import encode_pdf_pages_to_tspl, parse_and_decode_tspl
from tests.conftest import build_synthetic_carrier_pdf, build_synthetic_fba_en_pdf


def test_tspl_100x100_and_50x30_reverse_decode_and_zxing() -> None:
    # 1. 100×100mm 外箱标 TSPL 逆向解码与扫码
    _, fba_pdf = process_fba_pdf(build_synthetic_fba_en_pdf("FBA00DEMO01", "DMO1", 1), "f1", "f1.pdf")
    tspl_box = encode_pdf_pages_to_tspl(fba_pdf, width_mm=100.0, height_mm=100.0, gap_mm=2.0, copies_per_page=3)
    decoded_box = parse_and_decode_tspl(tspl_box)
    assert len(decoded_box) == 1
    cmd = decoded_box[0]
    assert cmd.size_mm == (100.0, 100.0)
    assert cmd.gap_mm == (2.0, 0.0)
    assert cmd.direction == 1
    assert cmd.width_bytes == 100
    assert cmd.height_dots == 800
    assert len(cmd.bitmap_payload) == 100 * 800
    assert cmd.copies == 3

    box_barcodes = [r["text"] for r in scan_barcodes_from_image(cmd.image)]
    assert "FBA00DEMO01U000001" in box_barcodes

    # 2. 50×30mm 双排 (总宽 102mm) TSPL 逆向解码与左右双码同时识别
    fnsku_pdf = render_fnsku_elements_pdf(
        FnskuRenderRequest(
            elements=[
                CanvasElement(
                    id="bc1",
                    type="barcode1d",
                    x=3.0,
                    y=2.0,
                    w=44.0,
                    h=15.0,
                    code="X009TSPL01",
                    show_text=True,
                )
            ],
            width_mm=50.0,
            height_mm=30.0,
            layout_type="double",
            col_gap_mm=2.0,
            qty=2,
        )
    )
    tspl_fnsku = encode_pdf_pages_to_tspl(fnsku_pdf, width_mm=102.0, height_mm=30.0, gap_mm=2.0, copies_per_page=1)
    decoded_fnsku = parse_and_decode_tspl(tspl_fnsku)
    assert len(decoded_fnsku) == 1
    f_cmd = decoded_fnsku[0]
    assert f_cmd.size_mm == (102.0, 30.0)
    assert f_cmd.width_bytes == 102
    assert f_cmd.height_dots == 240
    assert len(f_cmd.bitmap_payload) == 102 * 240

    img = f_cmd.image
    assert "X009TSPL01" in [r["text"] for r in scan_barcodes_from_image(img.crop((0, 0, 400, 240)))]
    assert "X009TSPL01" in [r["text"] for r in scan_barcodes_from_image(img.crop((416, 0, 816, 240)))]


def test_fastapi_endpoints_smoke() -> None:
    client = TestClient(app)

    assert client.get("/api/health").json()["ok"] is True

    # 校准档与纸卷规格记忆状态
    profiles = client.get("/api/hardware/profiles").json()
    assert {p["spec_key"] for p in profiles} >= {"100x100_single", "50x30_double"}
    assert client.get("/api/hardware/spec-state").json()["last_printed_spec"] == "100x100_single"
    client.put("/api/hardware/spec-state", json={"last_printed_spec": "50x30_double"})
    assert client.get("/api/hardware/spec-state").json()["last_printed_spec"] == "50x30_double"

    # 模板库初始严格为空，保存后再读再删
    assert client.get("/api/fnsku/templates").json() == []
    saved = client.post(
        "/api/fnsku/templates",
        json={
            "sku": "DEMO-API-01",
            "fnsku": "X009API001",
            "title_clean": "New - Demo Item",
            "widthMm": 50,
            "heightMm": 30,
            "layoutType": "double",
            "elements": [
                {"id": "e1", "type": "barcode1d", "x": 3, "y": 2, "w": 44, "h": 14, "code": "X009API001", "showText": True}
            ],
        },
    )
    assert saved.status_code == 200
    tpl_id = saved.json()["id"]
    assert len(client.get("/api/fnsku/templates").json()) == 1
    assert client.delete(f"/api/fnsku/templates/{tpl_id}").status_code == 200

    # FBA 上传处理 + 箱唛上传 + 配对 + TSPL 干跑
    fba_bytes = build_synthetic_fba_en_pdf("FBA00API001", "DMO1", 2)
    car_bytes = build_synthetic_carrier_pdf("FBA00API001", "DMO1", 2)
    r_fba = client.post("/api/box/process-fba", files={"file": ("FBA00API001.pdf", fba_bytes, "application/pdf")})
    assert r_fba.status_code == 200
    fba_json = r_fba.json()
    assert fba_json["shipment_id"] == "FBA00API001"

    r_car = client.post("/api/box/process-carrier", files={"file": ("car.pdf", car_bytes, "application/pdf")})
    assert r_car.status_code == 200
    car_json = r_car.json()

    r_pair = client.post(
        "/api/box/pair",
        json={"fba_boxes": fba_json["boxes"], "carrier_boxes": car_json["items"], "default_copies": 2},
    )
    assert r_pair.status_code == 200
    assert r_pair.json()["can_print"] is True
    # 2 箱 × 每箱 2 套 × 成对 2 张 = 8 张
    assert r_pair.json()["total_sheets"] == 8

    # 产品标预览与批次保存烟雾校验
    r_prev = client.post(
        "/api/fnsku/render-preview",
        json={
            "widthMm": 50,
            "heightMm": 30,
            "layoutType": "double",
            "qty": 2,
            "elements": [{"id": "e1", "type": "barcode1d", "x": 3, "y": 2, "w": 44, "h": 14, "code": "X009API001", "showText": True}],
        },
    )
    assert r_prev.status_code == 200
    assert r_prev.json()["page_count"] == 1
    assert r_prev.json()["preview_203dpi_b64"].startswith("data:image/png;base64,")

    r_batch = client.post(
        "/api/batches",
        json={
            "batch_type": "box_paired",
            "shipment_id": "FBA00API001",
            "warehouse_code": "DMO1",
            "spec_key": "100x100_single",
            "total_units_or_boxes": 2,
            "copies_per_box": 2,
            "order_mode": "interleave",
            "channel": "tspl_raw",
            "summary": "FBA00API001 (2箱×2套)",
        },
    )
    assert r_batch.status_code == 200
    assert len(client.get("/api/batches").json()) == 1

    r_dry = client.post(
        "/api/hardware/dryrun-tspl",
        json={"pdf_b64": fba_json["pdf_b64"], "width_mm": 100.0, "height_mm": 100.0},
    )
    assert r_dry.status_code == 200
    assert r_dry.json()["commands_count"] == 2
    assert base64.b64decode(fba_json["pdf_b64"]).startswith(b"%PDF")

    # 校验新增预览图、合并 PDF 导出、校准卡及统一执行打印接口
    assert fba_json["boxes"][0]["clean_preview_b64"].startswith("data:image/png;base64,")
    assert fba_json["boxes"][0]["raw_preview_b64"].startswith("data:image/png;base64,")
    assert fba_json["boxes"][0]["full_page_b64"].startswith("data:image/png;base64,")
    assert car_json["items"][0]["preview_b64"].startswith("data:image/png;base64,")

    r_merge = client.post(
        "/api/box/export-merged-pdf",
        json={
            "fba_pdfs_b64": {fba_json["file_id"]: fba_json["pdf_b64"]},
            "carrier_pdfs_b64": {car_json["file_id"]: car_json["pdf_b64"]},
            "queue": r_pair.json()["queue"],
        },
    )
    assert r_merge.status_code == 200
    assert r_merge.json()["page_count"] == 8

    r_cal = client.post("/api/hardware/calibration-card", json={"spec_key": "50x30_double"})
    assert r_cal.status_code == 200
    assert r_cal.json()["preview_203dpi_b64"].startswith("data:image/png;base64,")

    r_exec = client.post(
        "/api/hardware/execute-print",
        json={
            "pdf_b64": r_merge.json()["pdf_b64"],
            "spec_key": "100x100_single",
            "channel": "tspl_raw",
            "printer_name": "",
            "batch": {
                "batch_type": "box_paired",
                "shipment_id": "FBA00API001",
                "warehouse_code": "DMO1",
                "spec_key": "100x100_single",
                "total_units_or_boxes": 2,
                "copies_per_box": 2,
                "order_mode": "interleave",
                "channel": "tspl_raw",
                "summary": "FBA00API001 执行打印测试",
            },
        },
    )
    assert r_exec.status_code == 200
    exec_json = r_exec.json()
    assert exec_json["ok"] is True
    assert exec_json["tspl_commands"] == 8
    assert exec_json["tspl_bytes_len"] > 600000
    assert len(client.get("/api/batches").json()) == 2


def test_calibration_cards_zxing_decoding_100x100_and_50x30() -> None:
    client = TestClient(app)
    eng = PyMuPDFEngine()

    # 1. 100x100mm 单排校准卡：十字准星不贯穿条码区，203dpi 必解出 CAL100DEMO
    r_100 = client.post("/api/hardware/calibration-card", json={"spec_key": "100x100_single"})
    assert r_100.status_code == 200
    j_100 = r_100.json()
    pdf_100 = base64.b64decode(j_100["pdf_b64"])
    img_100_pdf = eng.render_page_to_1bit(pdf_100, page_index=0, dpi=203)
    codes_100 = [item["text"] for item in scan_barcodes_from_image(img_100_pdf)]
    assert "CAL100DEMO" in codes_100

    # 同时验证接口直接返回的 203dpi PNG 预览图也可被 zxingcpp 100% 解码
    b64_png_100 = j_100["preview_203dpi_b64"].split(",", 1)[1]
    img_100_preview = Image.open(io.BytesIO(base64.b64decode(b64_png_100)))
    assert "CAL100DEMO" in [item["text"] for item in scan_barcodes_from_image(img_100_preview)]

    # 2. 50x30mm 双排校准卡：左右双列均应可被 zxingcpp 解码
    r_50 = client.post("/api/hardware/calibration-card", json={"spec_key": "50x30_double"})
    assert r_50.status_code == 200
    j_50 = r_50.json()
    pdf_50 = base64.b64decode(j_50["pdf_b64"])
    img_50 = eng.render_page_to_1bit(pdf_50, page_index=0, dpi=203)
    left_codes = [item["text"] for item in scan_barcodes_from_image(img_50.crop((0, 0, 400, 240)))]
    right_codes = [item["text"] for item in scan_barcodes_from_image(img_50.crop((416, 0, 816, 240)))]
    assert "CAL50C1" in left_codes
    assert "CAL50C2" in right_codes


def test_macos_cups_multiline_offline_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    lpstat_p_out = (
        "printer EPSON_L4260_Series is idle.  enabled since Sat Nov 21 04:34:30 2026\n"
        "printer TSC_TTP_244_Pro now printing TSC_TTP_244_Pro-738.  enabled since Mon Nov 23 03:56:07 2026\n"
        "\tThe printer is offline.\n"
        "printer Backup_Thermal is idle.\n"
        "\tPaused\n"
        "printer USB_Printer disabled since Mon Nov 23 01:00:00 2026 -\n"
        "\tUnplugged or not connected\n"
    )

    def fake_run(cmd: list[str], **_kwargs: object) -> SimpleNamespace:
        if cmd == ["lpstat", "-d"]:
            return SimpleNamespace(returncode=0, stdout="system default destination: EPSON_L4260_Series\n", stderr="")
        if cmd == ["lpstat", "-p"]:
            return SimpleNamespace(returncode=0, stdout=lpstat_p_out, stderr="")
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr("app.printers.macos_cups.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(subprocess, "run", fake_run)

    devices = {d.name: d for d in MacOSCupsAdapter().list_printers()}
    assert devices["EPSON_L4260_Series"].status == "ready"
    assert devices["EPSON_L4260_Series"].is_default is True
    assert devices["EPSON_L4260_Series"].status_detail == ""

    assert devices["TSC_TTP_244_Pro"].status == "offline"
    assert devices["TSC_TTP_244_Pro"].is_recommended is True
    assert devices["TSC_TTP_244_Pro"].status_detail == "The printer is offline."

    assert devices["Backup_Thermal"].status == "disabled"
    assert devices["Backup_Thermal"].status_detail == "Paused"

    assert devices["USB_Printer"].status == "offline"
    assert devices["USB_Printer"].status_detail == "Unplugged or not connected"


def test_dryrun_command_headers_and_execute_print_dry_run_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(app)
    _, fba_pdf = process_fba_pdf(build_synthetic_fba_en_pdf("FBA00GUARD1", "DMO1", 2), "fg1", "fg1.pdf")
    pdf_b64 = base64.b64encode(fba_pdf).decode("ascii")

    # 1. /dryrun-tspl 必须返回可读 command_headers
    r_dry = client.post(
        "/api/hardware/dryrun-tspl",
        json={"pdf_b64": pdf_b64, "width_mm": 100.0, "height_mm": 100.0, "copies_per_page": 2},
    )
    assert r_dry.status_code == 200
    headers = r_dry.json()["command_headers"]
    assert isinstance(headers, list) and len(headers) == 2
    assert "SIZE 100.0 mm, 100.0 mm" in headers[0]
    assert "GAP 2.0 mm, 0.0 mm" in headers[0]
    assert "BITMAP 0,0,100,800,0,<80000 bytes>" in headers[0]
    assert "PRINT 1,2" in headers[0]

    # 2. execute-print 在 dry_run=True 时即使传了 printer_name，也绝不能调用 send_raw_tspl 或 print_pdf
    class GuardAdapter:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def send_raw_tspl(self, printer_name: str, payload: bytes) -> dict[str, object]:
            self.calls.append(f"raw:{printer_name}")
            raise AssertionError("dry_run=True 时严禁调用 send_raw_tspl")

        def print_pdf(self, printer_name: str, pdf_bytes: bytes, title: str = "FBA_Label") -> dict[str, object]:
            self.calls.append(f"pdf:{printer_name}")
            raise AssertionError("dry_run=True 时严禁调用 print_pdf")

    guard = GuardAdapter()
    monkeypatch.setattr("app.api.hardware.get_printer_adapter", lambda: guard)

    for ch in ("tspl_raw", "os_driver"):
        r_exec = client.post(
            "/api/hardware/execute-print",
            json={
                "pdf_b64": pdf_b64,
                "spec_key": "100x100_single",
                "channel": ch,
                "printer_name": "TSC_TTP_244_Pro",
                "dry_run": True,
                "batch": {
                    "batch_type": "box_fba_only",
                    "shipment_id": "FBA00GUARD1",
                    "warehouse_code": "DMO1",
                    "spec_key": "100x100_single",
                    "total_units_or_boxes": 2,
                    "copies_per_box": 1,
                    "order_mode": "interleave",
                    "channel": ch,
                    "summary": f"干跑守卫测试-{ch}",
                },
            },
        )
        assert r_exec.status_code == 200
        body = r_exec.json()
        assert body["ok"] is True
        assert body["printer_result"] == {"ok": True, "mode": ch, "offline_dryrun": True}
        assert body["tspl_commands"] == 2
        assert body["tspl_bytes_len"] > 100000
        assert len(body["command_headers"]) == 2
    assert guard.calls == []


def test_pdf_export_snapshot_download_and_delete_batch() -> None:
    client = TestClient(app)
    _, fba_pdf = process_fba_pdf(build_synthetic_fba_en_pdf("FBA00PDFEXP", "DMO1", 2), "fp1", "fp1.pdf")
    pdf_b64 = base64.b64encode(fba_pdf).decode("ascii")

    r_exec = client.post(
        "/api/hardware/execute-print",
        json={
            "pdf_b64": pdf_b64,
            "spec_key": "100x100_single",
            "channel": "pdf_export",
            "printer_name": "",
            "dry_run": False,
            "batch": {
                "batch_type": "box_fba_only",
                "shipment_id": "FBA00PDFEXP",
                "warehouse_code": "DMO1",
                "spec_key": "100x100_single",
                "total_units_or_boxes": 2,
                "copies_per_box": 1,
                "order_mode": "interleave",
                "channel": "pdf_export",
                "summary": "PDF导出与快照测试",
            },
        },
    )
    assert r_exec.status_code == 200
    body = r_exec.json()
    assert body["ok"] is True
    assert body["tspl_commands"] == 0
    assert body["printer_result"] == {"ok": True, "mode": "pdf_export", "offline_dryrun": False}

    batches = client.get("/api/batches").json()
    assert len(batches) == 1
    batch = batches[0]
    batch_id = batch["id"]
    snap_path = Path(batch["snapshot_dir"])
    assert snap_path.is_file()
    assert snap_path.parent == get_snapshots_dir()

    r_snap = client.get(f"/api/batches/{batch_id}/pdf")
    assert r_snap.status_code == 200
    snap_json = r_snap.json()
    assert snap_json["batch_id"] == batch_id
    snap_pdf = base64.b64decode(snap_json["pdf_b64"])
    assert snap_pdf.startswith(b"%PDF")
    assert len(PyMuPDFEngine().get_page_dimensions_pt(snap_pdf)) == 2

    r_del = client.delete(f"/api/batches/{batch_id}")
    assert r_del.status_code == 200
    assert r_del.json() == {"ok": True}
    assert not snap_path.exists()
    assert client.get("/api/batches").json() == []
    assert client.get(f"/api/batches/{batch_id}/pdf").status_code == 404
