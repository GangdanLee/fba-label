"""Windows 平台 win32print RAW 直出与 Win32 GDI 原生驱动打印机适配器。"""

from __future__ import annotations

from app.engines.pdf_engine import PyMuPDFEngine
from app.models.schemas import PrinterDevice
from app.printers.base import PrinterAdapter
from app.printers.registry import infer_printer_hints


class WindowsRawAdapter(PrinterAdapter):
    """基于 pywin32 (win32print / win32ui) 的 Windows RAW 与 GDI 通道打印机适配器。"""

    def _import_win32(self):
        try:
            import win32print  # type: ignore

            return win32print
        except ImportError:
            return None

    def _import_win32_gdi(self):
        try:
            import win32con  # type: ignore
            import win32ui  # type: ignore
            from PIL import ImageWin

            return win32ui, win32con, ImageWin
        except ImportError:
            return None

    def list_printers(self) -> list[PrinterDevice]:
        win32print = self._import_win32()
        if win32print is None:
            return []

        default_name = ""
        try:
            default_name = win32print.GetDefaultPrinter()
        except Exception:
            pass

        devices: list[PrinterDevice] = []
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        for item in win32print.EnumPrinters(flags):
            name = item[2]
            sugg_proto, sugg_dpi, is_thermal = infer_printer_hints(name)
            devices.append(
                PrinterDevice(
                    name=name,
                    system="Windows Win32",
                    is_default=(name == default_name),
                    is_recommended=is_thermal,
                    status="ready",
                    suggested_protocol=sugg_proto,
                    suggested_dpi=sugg_dpi,
                    is_thermal_hint=is_thermal,
                )
            )
        return devices

    def send_raw_tspl(self, printer_name: str, payload: bytes) -> dict[str, object]:
        win32print = self._import_win32()
        if win32print is None:
            return {"ok": False, "mode": "tspl_raw", "error": "Windows 环境缺少 pywin32 依赖"}
        if not printer_name:
            return {"ok": False, "mode": "tspl_raw", "error": "未指定打印机名称"}

        handle = win32print.OpenPrinter(printer_name)
        try:
            win32print.StartDocPrinter(handle, 1, ("FBA_RAW_Label", None, "RAW"))
            try:
                win32print.StartPagePrinter(handle)
                win32print.WritePrinter(handle, payload)
                win32print.EndPagePrinter(handle)
            finally:
                win32print.EndDocPrinter(handle)
            return {"ok": True, "mode": "tspl_raw", "printer": printer_name, "bytes": len(payload)}
        finally:
            win32print.ClosePrinter(handle)

    def print_pdf(self, printer_name: str, pdf_bytes: bytes, title: str = "FBA_Label") -> dict[str, object]:
        if not printer_name:
            return {"ok": False, "mode": "os_driver", "error": "未指定打印机名称"}
        gdi = self._import_win32_gdi()
        if gdi is None:
            return {
                "ok": False,
                "mode": "os_driver",
                "error": "Windows 原生驱动打印缺少 pywin32 (win32ui) 或 Pillow ImageWin 组件",
            }
        win32ui, win32con, ImageWin = gdi
        eng = PyMuPDFEngine()
        page_count = eng.get_page_count(pdf_bytes)
        dims = eng.get_page_dimensions_pt(pdf_bytes)

        hdc = win32ui.CreateDC()
        hdc.CreatePrinterDC(printer_name)
        try:
            dpi_x = max(150, int(hdc.GetDeviceCaps(win32con.LOGPIXELSX)))
            dpi_y = max(150, int(hdc.GetDeviceCaps(win32con.LOGPIXELSY)))
            render_dpi = max(dpi_x, dpi_y)
            hdc.StartDoc(title or "FBA_Label")
            for idx in range(page_count):
                img_1bit = eng.render_page_to_1bit(pdf_bytes, idx, dpi=render_dpi, threshold=160)
                rgb = img_1bit.convert("RGB")
                w_pt, h_pt = dims[idx]
                target_w = max(1, int(round(w_pt * dpi_x / 72.0)))
                target_h = max(1, int(round(h_pt * dpi_y / 72.0)))
                hdc.StartPage()
                dib = ImageWin.Dib(rgb)
                dib.draw(hdc.GetHandleOutput(), (0, 0, target_w, target_h))
                hdc.EndPage()
            hdc.EndDoc()
            return {
                "ok": True,
                "mode": "os_driver",
                "printer": printer_name,
                "pages": page_count,
                "device_dpi": render_dpi,
            }
        finally:
            hdc.DeleteDC()
