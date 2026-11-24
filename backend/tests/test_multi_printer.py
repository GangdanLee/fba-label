"""v0.2.0 多协议打印机（TSPL / ZPL / 203 & 300dpi / TCP 9100 / Windows GDI / SQLite 迁移）回归测试套件。"""

from __future__ import annotations

import base64
import math
import socket
import sqlite3
import subprocess
import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from app import db
from app.engines.fba_processor import process_fba_pdf
from app.engines.fnsku_engine import render_fnsku_elements_pdf
from app.models.schemas import CanvasElement, FnskuRenderRequest
from app.printers.macos_cups import MacOSCupsAdapter
from app.printers.registry import infer_printer_hints
from app.printers.simulator import scan_barcodes_from_image
from app.printers.tspl_encoder import encode_pdf_pages_to_tspl, parse_and_decode_tspl
from app.printers.windows_raw import WindowsRawAdapter
from app.printers.zpl_encoder import encode_pdf_pages_to_zpl, parse_and_decode_zpl
from tests.conftest import build_synthetic_fba_en_pdf


def test_zpl_encoder_203_and_300dpi_box_and_double_row_zxing() -> None:
    # 1. 100×100mm 外箱标 203dpi 与 300dpi ZPL 编码与位图极性逆向解码
    _, fba_pdf = process_fba_pdf(build_synthetic_fba_en_pdf("FBA00ZPL01", "DMO1", 1), "fz1", "fz1.pdf")
    for dpi, expected_dots in ((203, 800), (300, 1181)):
        zpl_bytes = encode_pdf_pages_to_zpl(
            fba_pdf,
            width_mm=100.0,
            height_mm=100.0,
            dpi=dpi,
            copies_per_page=2,
            offset_x_mm=1.0,
            offset_y_mm=-0.5,
        )
        decoded = parse_and_decode_zpl(zpl_bytes)
        assert len(decoded) == 1
        cmd = decoded[0]
        assert cmd.pw_dots == expected_dots
        assert cmd.ll_dots == expected_dots
        assert cmd.copies == 2
        assert cmd.image.size == (expected_dots, expected_dots)
        codes = [r["text"] for r in scan_barcodes_from_image(cmd.image)]
        assert "FBA00ZPL01U000001" in codes, f"ZPL {dpi}dpi 外箱未能解码: {codes}"

    # 2. 50×30mm & 40×30mm 双排产品标在 203/300dpi 下左右双栏均可解码
    for dpi in (203, 300):
        for w_mm, bc_w in ((50.0, 44.0), (40.0, 35.2)):
            margin_x = round((w_mm - bc_w) / 2.0, 2)
            pdf_bytes = render_fnsku_elements_pdf(
                FnskuRenderRequest(
                    elements=[
                        CanvasElement(
                            id="bc1",
                            type="barcode1d",
                            x=margin_x,
                            y=2.0,
                            w=bc_w,
                            h=14.0,
                            code="X000ZPL300",
                            show_text=True,
                        )
                    ],
                    width_mm=w_mm,
                    height_mm=30.0,
                    layout_type="double",
                    col_gap_mm=2.0,
                    qty=2,
                    dpi=dpi,
                )
            )
            page_w_mm = w_mm * 2.0 + 2.0
            zpl_bytes = encode_pdf_pages_to_zpl(pdf_bytes, width_mm=page_w_mm, height_mm=30.0, dpi=dpi)
            decoded = parse_and_decode_zpl(zpl_bytes)
            assert len(decoded) == 1
            img = decoded[0].image
            mid = img.width // 2
            left_codes = [r["text"] for r in scan_barcodes_from_image(img.crop((0, 0, mid + 2, img.height)))]
            right_codes = [r["text"] for r in scan_barcodes_from_image(img.crop((mid - 2, 0, img.width, img.height)))]
            assert "X000ZPL300" in left_codes, f"ZPL {dpi}dpi {w_mm}mm 左栏解码失败: {left_codes}"
            assert "X000ZPL300" in right_codes, f"ZPL {dpi}dpi {w_mm}mm 右栏解码失败: {right_codes}"


def test_tspl_300dpi_double_row_reverse_decode_and_zxing() -> None:
    pdf_bytes = render_fnsku_elements_pdf(
        FnskuRenderRequest(
            elements=[
                CanvasElement(
                    id="bc1",
                    type="barcode1d",
                    x=3.0,
                    y=2.0,
                    w=44.0,
                    h=15.0,
                    code="X000TSPL300",
                    show_text=True,
                )
            ],
            width_mm=50.0,
            height_mm=30.0,
            layout_type="double",
            col_gap_mm=2.0,
            qty=2,
            dpi=300,
        )
    )
    tspl_bytes = encode_pdf_pages_to_tspl(pdf_bytes, width_mm=102.0, height_mm=30.0, dpi=300)
    decoded = parse_and_decode_tspl(tspl_bytes)
    assert len(decoded) == 1
    cmd = decoded[0]
    expected_w_dots = int(round(102.0 * (300.0 / 25.4)))
    assert cmd.width_bytes == math.ceil(expected_w_dots / 8)
    mid = cmd.image.width // 2
    assert "X000TSPL300" in [r["text"] for r in scan_barcodes_from_image(cmd.image.crop((0, 0, mid + 2, cmd.image.height)))]
    assert "X000TSPL300" in [r["text"] for r in scan_barcodes_from_image(cmd.image.crop((mid - 2, 0, cmd.image.width, cmd.image.height)))]


def test_sqlite_migration_from_v012_preserves_old_data(tmp_path) -> None:
    legacy_db = tmp_path / "legacy_v012.db"
    conn = sqlite3.connect(str(legacy_db))
    conn.execute(
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
            printer_name TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        INSERT INTO calibration_profiles (
            spec_key, label_width_mm, label_height_mm, cols, col_gap_mm, row_gap_mm,
            safe_width_mm, safe_height_mm, offset_x_mm, offset_y_mm, darkness,
            print_speed, preferred_channel, printer_name
        ) VALUES ('50x30_double', 50.0, 30.0, 2, 2.0, 2.0, 48.0, 28.0, 1.2, -0.4, 9, 4, 'pdf_export', 'MyLegacyPrinter')
        """
    )
    conn.commit()
    conn.close()

    # 幂等迁移应无损保留旧配置并安全补齐 v0.2.0 默认列
    db.init_db(legacy_db)
    db.init_db(legacy_db)
    profs = {p.spec_key: p for p in db.list_calibration_profiles(legacy_db)}
    assert "50x30_double" in profs
    assert "100x100_single" in profs
    p50 = profs["50x30_double"]
    assert p50.offset_x_mm == 1.2
    assert p50.offset_y_mm == -0.4
    assert p50.preferred_channel == "pdf_export"
    assert p50.printer_name == "MyLegacyPrinter"
    assert p50.protocol == "tspl"
    assert p50.dpi == 203
    assert p50.connection_type == "os_queue"
    assert p50.network_host == ""
    assert p50.network_port == 9100


def test_printer_brand_heuristic_hints() -> None:
    assert infer_printer_hints("Zebra_Technologies_ZTC_ZD421_300dpi_ZPL") == ("zpl", 300, True)
    assert infer_printer_hints("ZDesigner GK888t") == ("zpl", 203, True)
    assert infer_printer_hints("TSC_TTP_244_Pro") == ("tspl", 203, True)
    assert infer_printer_hints("TSC_TTP_345") == ("tspl", 300, True)
    assert infer_printer_hints("Xprinter XP-420B") == ("tspl", 203, True)
    assert infer_printer_hints("Gprinter GP-1324D") == ("tspl", 203, True)
    assert infer_printer_hints("Brother QL-800") == ("os_driver", 203, True)
    assert infer_printer_hints("EPSON_L4260_Series") == ("os_driver", 203, False)


def test_network_tcp_loopback_probe_and_zpl_300dpi_execute_print() -> None:
    from app.main import app

    received_chunks: list[bytes] = []
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    port = int(srv.getsockname()[1])
    stop_flag = threading.Event()

    def accept_loop() -> None:
        srv.settimeout(0.2)
        while not stop_flag.is_set():
            try:
                conn, _addr = srv.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with conn:
                buf = bytearray()
                while True:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    buf.extend(chunk)
                if buf:
                    received_chunks.append(bytes(buf))

    t = threading.Thread(target=accept_loop, daemon=True)
    t.start()
    try:
        client = TestClient(app)

        # 1. test-network 仅探活即断，严禁产生空数据以外任何外发载荷
        r_test = client.post("/api/hardware/test-network", json={"host": "127.0.0.1", "port": port})
        assert r_test.status_code == 200
        assert r_test.json()["ok"] is True
        assert received_chunks == []

        # 2. execute-print 通过网口 TCP + ZPL + 300dpi 发送 100x100 外箱标到环回端口
        _, fba_pdf = process_fba_pdf(build_synthetic_fba_en_pdf("FBA00NET99", "DMO1", 1), "fn1", "fn1.pdf")
        r_exec = client.post(
            "/api/hardware/execute-print",
            json={
                "pdf_b64": base64.b64encode(fba_pdf).decode("ascii"),
                "spec_key": "100x100_single",
                "channel": "tspl_raw",
                "printer_name": "",
                "dry_run": False,
                "protocol": "zpl",
                "dpi": 300,
                "connection_type": "network_tcp",
                "network_host": "127.0.0.1",
                "network_port": port,
                "batch": {
                    "batch_type": "box_fba_only",
                    "shipment_id": "FBA00NET99",
                    "warehouse_code": "DMO1",
                    "spec_key": "100x100_single",
                    "total_units_or_boxes": 1,
                    "copies_per_box": 1,
                    "order_mode": "interleave",
                    "channel": "tspl_raw",
                    "summary": "TCP 9100 ZPL 300dpi 环回测试",
                },
            },
        )
        assert r_exec.status_code == 200
        body = r_exec.json()
        assert body["ok"] is True
        assert body["protocol"] == "zpl"
        assert body["dpi"] == 300
        assert body["connection_type"] == "network_tcp"
        assert body["printer_result"]["ok"] is True
        assert body["printer_result"]["mode"] == "network_tcp"
    finally:
        stop_flag.set()
        srv.close()
        t.join(timeout=2)

    assert len(received_chunks) == 1
    decoded = parse_and_decode_zpl(received_chunks[0])
    assert len(decoded) == 1
    assert decoded[0].pw_dots == 1181
    assert "FBA00NET99U000001" in [r["text"] for r in scan_barcodes_from_image(decoded[0].image)]


def test_macos_airprint_raw_hint_and_windows_gdi_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    # 1. macOS CUPS AirPrint 拒绝 octet-stream 时必须返回清晰中文换通道指引
    monkeypatch.setattr("app.printers.macos_cups.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_kw: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr='lp: Unsupported document-format "application/octet-stream".\n',
        ),
    )
    res_mac = MacOSCupsAdapter().send_raw_tspl("AirPrint_Label", b"SIZE 100 mm, 100 mm\r\n")
    assert res_mac["ok"] is False
    assert "AirPrint" in str(res_mac.get("hint", ""))

    # 2. Windows Win32 GDI print_pdf mock 全链调用校验
    gdi_calls: list[tuple[str, object]] = []

    class FakeHDC:
        def CreatePrinterDC(self, name: str) -> None:
            gdi_calls.append(("CreatePrinterDC", name))

        def GetDeviceCaps(self, cap: int) -> int:
            return 203

        def StartDoc(self, title: str) -> None:
            gdi_calls.append(("StartDoc", title))

        def StartPage(self) -> None:
            gdi_calls.append(("StartPage", None))

        def GetHandleOutput(self) -> int:
            return 42

        def EndPage(self) -> None:
            gdi_calls.append(("EndPage", None))

        def EndDoc(self) -> None:
            gdi_calls.append(("EndDoc", None))

        def DeleteDC(self) -> None:
            gdi_calls.append(("DeleteDC", None))

    class FakeDib:
        def __init__(self, img) -> None:
            self.size = img.size

        def draw(self, handle: int, rect: tuple[int, int, int, int]) -> None:
            gdi_calls.append(("Draw", (handle, rect)))

    fake_win32ui = SimpleNamespace(CreateDC=lambda: FakeHDC())
    fake_win32con = SimpleNamespace(LOGPIXELSX=88, LOGPIXELSY=90)
    fake_imagewin = SimpleNamespace(Dib=FakeDib)

    adapter = WindowsRawAdapter()
    monkeypatch.setattr(adapter, "_import_win32_gdi", lambda: (fake_win32ui, fake_win32con, fake_imagewin))
    _, fba_pdf = process_fba_pdf(build_synthetic_fba_en_pdf("FBA00GDI01", "DMO1", 2), "fgdi", "fgdi.pdf")
    res_win = adapter.print_pdf("Brother_QL_800", fba_pdf, title="FBA00GDI01")
    assert res_win["ok"] is True
    assert res_win["mode"] == "os_driver"
    assert res_win["pages"] == 2
    assert res_win["device_dpi"] == 203
    assert ("CreatePrinterDC", "Brother_QL_800") in gdi_calls
    assert ("EndDoc", None) in gdi_calls
    assert ("DeleteDC", None) in gdi_calls
    assert sum(1 for k, _ in gdi_calls if k == "StartPage") == 2


def test_multi_protocol_execute_print_dryrun_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import app

    def forbid_send(*_a, **_kw):
        raise AssertionError("dry_run=True 时严禁向驱动或 TCP 发送真实字节")

    monkeypatch.setattr("app.api.hardware.send_raw_tcp", forbid_send)
    monkeypatch.setattr(
        "app.api.hardware.get_printer_adapter",
        lambda: SimpleNamespace(send_raw_tspl=forbid_send, send_raw=forbid_send, print_pdf=forbid_send),
    )

    client = TestClient(app)
    _, fba_pdf = process_fba_pdf(build_synthetic_fba_en_pdf("FBA00ZPLGRD", "DMO1", 1), "fgz", "fgz.pdf")
    pdf_b64 = base64.b64encode(fba_pdf).decode("ascii")

    for conn_type in ("os_queue", "network_tcp"):
        r = client.post(
            "/api/hardware/execute-print",
            json={
                "pdf_b64": pdf_b64,
                "spec_key": "100x100_single",
                "channel": "tspl_raw",
                "printer_name": "Zebra_ZD421" if conn_type == "os_queue" else "",
                "dry_run": True,
                "protocol": "zpl",
                "dpi": 300,
                "connection_type": conn_type,
                "network_host": "127.0.0.1" if conn_type == "network_tcp" else "",
                "network_port": 9100,
                "batch": {
                    "batch_type": "box_fba_only",
                    "shipment_id": "FBA00ZPLGRD",
                    "warehouse_code": "DMO1",
                    "spec_key": "100x100_single",
                    "total_units_or_boxes": 1,
                    "copies_per_box": 1,
                    "order_mode": "interleave",
                    "channel": "tspl_raw",
                    "summary": f"ZPL 干跑守卫-{conn_type}",
                },
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["protocol"] == "zpl"
        assert body["dpi"] == 300
        assert body["printer_result"] == {"ok": True, "mode": "tspl_raw", "offline_dryrun": True}
        assert body["tspl_commands"] == 1
        assert "^PW1181" in body["command_headers"][0]
