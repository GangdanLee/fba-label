"""打印机适配器抽象接口与跨平台实例选择工厂。"""

from __future__ import annotations

import platform
from abc import ABC, abstractmethod

from app.models.schemas import PrinterDevice


class PrinterAdapter(ABC):
    """统一物理打印、原生驱动打印与设备探测抽象基类。"""

    @abstractmethod
    def list_printers(self) -> list[PrinterDevice]:
        ...

    @abstractmethod
    def send_raw_tspl(self, printer_name: str, payload: bytes) -> dict[str, object]:
        ...

    def send_raw(self, printer_name: str, payload: bytes, protocol: str = "tspl") -> dict[str, object]:
        """发送指定协议（TSPL / ZPL）的裸指令字节流；默认转发至底层 RAW 发送实现。"""
        res = self.send_raw_tspl(printer_name, payload)
        if protocol != "tspl" and isinstance(res, dict):
            return {**res, "protocol": protocol}
        return res

    @abstractmethod
    def print_pdf(self, printer_name: str, pdf_bytes: bytes, title: str = "FBA_Label") -> dict[str, object]:
        ...


def get_printer_adapter() -> PrinterAdapter:
    """按运行操作系统自动选择 macOS CUPS 或 Windows Win32 适配器。"""
    sys_name = platform.system()
    if sys_name == "Windows":
        from app.printers.windows_raw import WindowsRawAdapter

        return WindowsRawAdapter()

    from app.printers.macos_cups import MacOSCupsAdapter

    return MacOSCupsAdapter()
