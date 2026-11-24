"""v0.5.1 业务逻辑深度审计修复专项验证单测。"""

from __future__ import annotations

import base64
import io
import zipfile
from pathlib import Path
from unittest.mock import patch

import pymupdf
from fastapi.testclient import TestClient

from app import db
from app.api.box_labels import _build_separator_page_pdf
from app.engines.amazon_fc_codes import extract_amazon_fc_code
from app.engines.fba_processor import _extract_sku_info
from app.main import app
from app.models.schemas import CanvasElement, PrintQueueItem
from tests.conftest import build_synthetic_carrier_pdf, build_synthetic_fba_en_pdf


def _sample_single_page_pdf_b64() -> str:
    pdf_bytes = build_synthetic_fba_en_pdf("FBA00AUDIT01", "ONT8", 1)
    return base64.b64encode(pdf_bytes).decode("ascii")


def test_execute_print_real_failure_raises_502_and_skips_batch(isolated_data_dir: Path) -> None:
    client = TestClient(app)
    pdf_b64 = _sample_single_page_pdf_b64()

    class FailingAdapter:
        def send_raw_tspl(self, printer_name: str, payload: bytes) -> dict[str, object]:
            return {
                "ok": False,
                "mode": "tspl_raw",
                "printer": printer_name,
                "stderr": "unsupported document-format application/octet-stream",
                "hint": "当前 CUPS 队列不支持 RAW 裸流，请切换系统原生驱动",
            }

        def send_raw(self, printer_name: str, payload: bytes, protocol: str = "tspl") -> dict[str, object]:
            return self.send_raw_tspl(printer_name, payload)

        def print_pdf(self, printer_name: str, pdf_bytes: bytes, title: str = "FBA_Label") -> dict[str, object]:
            return {"ok": False, "mode": "os_driver", "error": "printer offline"}

    # 1. tspl_raw 真实发送失败必须返回 HTTP 502 且不能写 print_batches
    with patch("app.api.hardware.get_printer_adapter", return_value=FailingAdapter()):
        resp_fail = client.post(
            "/api/hardware/execute-print",
            json={
                "pdf_b64": pdf_b64,
                "spec_key": "100x100_single",
                "channel": "tspl_raw",
                "printer_name": "MOCK_TTP_244",
                "dry_run": False,
                "batch": {
                    "batch_type": "box_paired",
                    "shipment_id": "FBA00FAIL01",
                    "warehouse_code": "ONT8",
                    "spec_key": "100x100_single",
                    "total_units_or_boxes": 1,
                    "copies_per_box": 1,
                    "order_mode": "per_box_group",
                    "channel": "tspl_raw",
                    "summary": "fail test",
                },
            },
        )
    assert resp_fail.status_code == 502
    assert "RAW" in resp_fail.json()["detail"]
    assert db.list_print_batches() == []

    # 2. os_driver 真实发送失败同样返回 502 且不写库
    with patch("app.api.hardware.get_printer_adapter", return_value=FailingAdapter()):
        resp_os_fail = client.post(
            "/api/hardware/execute-print",
            json={
                "pdf_b64": pdf_b64,
                "spec_key": "100x100_single",
                "channel": "os_driver",
                "printer_name": "MOCK_TTP_244",
                "dry_run": False,
                "batch": {
                    "batch_type": "box_paired",
                    "shipment_id": "FBA00FAIL02",
                    "warehouse_code": "ONT8",
                    "spec_key": "100x100_single",
                    "total_units_or_boxes": 1,
                    "copies_per_box": 1,
                    "order_mode": "per_box_group",
                    "channel": "os_driver",
                    "summary": "os fail test",
                },
            },
        )
    assert resp_os_fail.status_code == 502
    assert "printer offline" in resp_os_fail.json()["detail"]
    assert db.list_print_batches() == []


def test_os_driver_success_and_batch_reprint_exact_page_count(isolated_data_dir: Path) -> None:
    client = TestClient(app)

    # 双排 50x30 渲染 5 张标签 -> 物理 PDF 实际为 3 页
    r_render = client.post(
        "/api/fnsku/render-preview",
        json={
            "elements": [
                CanvasElement(
                    id="bc1", type="barcode1d", x=3, y=2, w=44, h=14, code="X000AUDIT5", showText=True
                ).model_dump(by_alias=True)
            ],
            "widthMm": 50.0,
            "heightMm": 30.0,
            "layoutType": "double",
            "colGapMm": 2.0,
            "offsetXMm": 0.0,
            "offsetYMm": 0.0,
            "qty": 5,
            "dpi": 203,
        },
    )
    assert r_render.status_code == 200
    assert r_render.json()["page_count"] == 3
    pdf_b64 = r_render.json()["pdf_b64"]

    class OkOsAdapter:
        def print_pdf(self, printer_name: str, pdf_bytes: bytes, title: str = "FBA_Label") -> dict[str, object]:
            return {"ok": True, "mode": "os_driver", "printer": printer_name}

    with patch("app.api.hardware.get_printer_adapter", return_value=OkOsAdapter()):
        resp_ok = client.post(
            "/api/hardware/execute-print",
            json={
                "pdf_b64": pdf_b64,
                "spec_key": "50x30_double",
                "channel": "os_driver",
                "printer_name": "MOCK_OFFICE_PRN",
                "dry_run": False,
                "batch": {
                    "batch_type": "fnsku",
                    "shipment_id": "AUDIT-SKU-5PCS",
                    "warehouse_code": "-",
                    "spec_key": "50x30_double",
                    "total_units_or_boxes": 5,
                    "copies_per_box": 1,
                    "order_mode": "double",
                    "channel": "os_driver",
                    "summary": "AUDIT-SKU-5PCS · 5 张",
                },
            },
        )
    assert resp_ok.status_code == 200
    data = resp_ok.json()
    assert data["page_count"] == 3
    batch_id = data["batch"]["id"]

    # 快照取回 API 必须返回真实物理页数 3（而非 5*1=5）
    r_snap = client.get(f"/api/batches/{batch_id}/pdf")
    assert r_snap.status_code == 200
    assert r_snap.json()["page_count"] == 3


def test_sku_zip_skips_mismatch_groups_and_uses_shipment_filename() -> None:
    client = TestClient(app)

    # 1 票完整配对 (FBA00OK001) + 1 票缺货代箱唛的异常票 (FBA00MISS2)
    f_ok = build_synthetic_fba_en_pdf("FBA00OK001", "ONT8", 1)
    c_ok = build_synthetic_carrier_pdf("FBA00OK001", "ONT8", 1)
    f_miss = build_synthetic_fba_en_pdf("FBA00MISS2", "LAX9", 1)

    rf_ok = client.post("/api/box/process-fba", files={"file": ("ok_fba.pdf", f_ok, "application/pdf")}).json()
    rc_ok = client.post("/api/box/process-carrier", files={"file": ("ok_car.pdf", c_ok, "application/pdf")}).json()
    rf_miss = client.post("/api/box/process-fba", files={"file": ("miss_fba.pdf", f_miss, "application/pdf")}).json()

    paired = client.post(
        "/api/box/pair",
        json={
            "fba_boxes": [*rf_ok["boxes"], *rf_miss["boxes"]],
            "carrier_boxes": rc_ok["items"],
            "group_by": "shipment",
            "work_mode": "paired",
            "order_mode": "per_box_group",
            "default_fba_copies": 2,
            "default_carrier_copies": 1,
            "active_shipment_id": "FBA00OK001",
        },
    ).json()

    r_zip = client.post(
        "/api/box/export-sku-zip",
        json={
            "fba_pdfs_b64": {rf_ok["file_id"]: rf_ok["pdf_b64"], rf_miss["file_id"]: rf_miss["pdf_b64"]},
            "carrier_pdfs_b64": {rc_ok["file_id"]: rc_ok["pdf_b64"]},
            "groups": paired["groups"],
            "group_by": "shipment",
            "work_mode": "paired",
            "order_mode": "per_box_group",
            "insert_separator_pages": False,
            "force_unlocked": False,
        },
    )
    assert r_zip.status_code == 200
    info = r_zip.json()
    assert info["group_by"] == "shipment"
    assert info["filename"].startswith("FBA_Label_按货件分组_1票_")
    assert info["file_count"] == 1
    assert info["skipped_groups"] == ["FBA00MISS2"]

    with zipfile.ZipFile(io.BytesIO(base64.b64decode(info["zip_b64"])), "r") as zf:
        names = zf.namelist()
        assert "FBA00OK001_3pages.pdf" in names
        assert not any("FBA00MISS2" in n for n in names)


def test_four_letter_fc_code_non_sku_filters_and_long_separator_fit() -> None:
    # 4 字母白名单仓点 IUSB / VJNA 命中，且无 SKU 时不被箱重与日期误判
    assert extract_amazon_fc_code("SHIP TO: Amazon FC IUSB US") == "IUSB"
    assert extract_amazon_fc_code("Dest Hub VJNA JP") == "VJNA"
    assert _extract_sku_info("Single SKU\n28LB\nPlease Leave Uncovered") == (None, False)
    assert _extract_sku_info("Single SKU\n2026-11-24\nQty 10") == (None, False)
    assert _extract_sku_info("SKU: 123456\nBox 1 of 2") == (None, False)

    # 超长 SKU 与货件详情渲染分隔提示页不报错、保持 100x100mm 单页且含清晰 SKU 前缀
    sep_item = PrintQueueItem(
        seq=1,
        kind="fba",
        shipment_id="FBA00VERYLONGSHIPMENT999",
        box_index=1,
        copy_no=0,
        page_index=-1,
        label="分隔·IUSB",
        file_id="",
        warehouse_code="IUSB",
        sku_text="SUPER-LONG-SKU-NAME-WITH-MANY-SEGMENTS-VARIANT-XL-2026-BLACK",
        is_separator=True,
        separator_title="仓库切换 · IUSB",
        separator_detail="SKU: SUPER-LONG-SKU-NAME-WITH-MANY-SEGMENTS-VARIANT-XL-2026-BLACK | 货件: FBA00VERYLONGSHIPMENT999",
    )
    sep_pdf = _build_separator_page_pdf(sep_item)
    with pymupdf.open(stream=sep_pdf, filetype="pdf") as doc:
        assert len(doc) == 1
        assert abs(doc[0].rect.width * 25.4 / 72.0 - 100.0) < 0.2
        txt = doc[0].get_text("text")
        assert "IUSB" in txt
        assert "SUPER-LONG-SKU" in txt


def test_backup_replace_empty_batches_clears_target_and_restores_snapshots(isolated_data_dir: Path) -> None:
    client = TestClient(app)

    # 1. A 机执行一次带快照干跑打印（产生 1 条打印批次 + PDF 快照），导出「含快照」备份 ZIP
    pdf_b64 = _sample_single_page_pdf_b64()
    r_print = client.post(
        "/api/hardware/execute-print",
        json={
            "pdf_b64": pdf_b64,
            "spec_key": "100x100_single",
            "channel": "tspl_raw",
            "printer_name": "",
            "dry_run": True,
            "batch": {
                "batch_type": "box_paired",
                "shipment_id": "FBA00SNAPMIG",
                "warehouse_code": "ONT8",
                "spec_key": "100x100_single",
                "total_units_or_boxes": 1,
                "copies_per_box": 1,
                "order_mode": "per_box_group",
                "channel": "tspl_raw",
                "summary": "snapshot migration check",
            },
        },
    )
    assert r_print.status_code == 200
    batch_id = r_print.json()["batch"]["id"]

    r_exp_full = client.post("/api/system/backup/export", json={"include_snapshots": True})
    assert r_exp_full.status_code == 200
    full_zip = base64.b64decode(r_exp_full.json()["zip_b64"])

    # 2. 删除 A 机该批次后，用 include_snapshots=True（但此时 0 批次）导出一份含空批次标志的 replace 包
    assert client.delete(f"/api/batches/{batch_id}").status_code == 200
    r_exp_empty_batches = client.post("/api/system/backup/export", json={"include_snapshots": True})
    assert r_exp_empty_batches.status_code == 200
    empty_batches_zip = base64.b64decode(r_exp_empty_batches.json()["zip_b64"])

    # 先用 full_zip 恢复回那 1 条历史批次，验证跨路径迁移后 PDF 快照可下载与取回页数
    r_imp_full = client.post(
        "/api/system/backup/import",
        files={"file": ("full.zip", full_zip, "application/zip")},
        data={"mode": "replace"},
    )
    assert r_imp_full.status_code == 200
    assert r_imp_full.json()["snapshots_restored"] == 1
    assert len(client.get("/api/batches").json()) == 1
    r_dl = client.get(f"/api/batches/{batch_id}/pdf")
    assert r_dl.status_code == 200
    assert r_dl.json()["page_count"] == 1

    # 再用 0 批次的 replace 包导入，必须能清空目标库既有批次（修复 include_batches 缺失缺陷）
    r_imp_clear = client.post(
        "/api/system/backup/import",
        files={"file": ("empty_batches.zip", empty_batches_zip, "application/zip")},
        data={"mode": "replace"},
    )
    assert r_imp_clear.status_code == 200
    assert client.get("/api/batches").json() == []
