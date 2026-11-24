"""macOS CUPS 打印机探测、lp -o raw 裸指令发送与系统 PDF 打印适配器。"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from app.models.schemas import PrinterDevice
from app.printers.base import PrinterAdapter
from app.printers.registry import infer_printer_hints


class MacOSCupsAdapter(PrinterAdapter):
    """基于 CUPS lpstat 与 lp 命令的 macOS 热敏/办公打印机适配实现。"""

    def list_printers(self) -> list[PrinterDevice]:
        if not shutil.which("lpstat"):
            return []

        default_name = ""
        try:
            res_def = subprocess.run(["lpstat", "-d"], capture_output=True, text=True, timeout=3)
            if res_def.returncode == 0 and ":" in res_def.stdout:
                default_name = res_def.stdout.split(":", 1)[1].strip()
        except Exception:
            pass

        printers: list[PrinterDevice] = []
        try:
            res = subprocess.run(["lpstat", "-p"], capture_output=True, text=True, timeout=3)
            entries: list[tuple[str, list[str]]] = []
            for raw_line in res.stdout.splitlines():
                if raw_line.startswith("printer "):
                    entries.append((raw_line, []))
                elif entries and raw_line.startswith((" ", "\t")) and raw_line.strip():
                    entries[-1][1].append(raw_line.strip())

            for header_line, detail_lines in entries:
                parts = header_line.split()
                if len(parts) < 2:
                    continue
                name = parts[1]
                status_detail = " ".join(detail_lines)
                combined_lower = f"{header_line} {status_detail}".lower()
                if any(kw in combined_lower for kw in ("offline", "not connected", "unplugged")):
                    status = "offline"
                elif any(kw in combined_lower for kw in ("disabled", "paused")):
                    status = "disabled"
                else:
                    status = "ready"
                sugg_proto, sugg_dpi, is_thermal = infer_printer_hints(name)
                printers.append(
                    PrinterDevice(
                        name=name,
                        system="macOS CUPS",
                        is_default=(name == default_name),
                        is_recommended=is_thermal,
                        status=status,
                        status_detail=status_detail,
                        suggested_protocol=sugg_proto,
                        suggested_dpi=sugg_dpi,
                        is_thermal_hint=is_thermal,
                    )
                )
        except Exception:
            return []
        return printers

    def send_raw_tspl(self, printer_name: str, payload: bytes) -> dict[str, object]:
        if not printer_name:
            return {"ok": False, "mode": "tspl_raw", "error": "未指定打印机名称（当前可能处于离线无真机模式）"}
        if not shutil.which("lp"):
            return {"ok": False, "mode": "tspl_raw", "error": "未找到系统 lp 打印命令"}

        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as tf:
                tf.write(payload)
                tmp_path = tf.name
            res = subprocess.run(
                ["lp", "-d", printer_name, "-o", "raw", tmp_path],
                capture_output=True,
                text=True,
                timeout=15,
            )
            out: dict[str, object] = {
                "ok": res.returncode == 0,
                "mode": "tspl_raw",
                "printer": printer_name,
                "bytes": len(payload),
                "stdout": res.stdout.strip(),
                "stderr": res.stderr.strip(),
            }
            err_lower = res.stderr.lower()
            if res.returncode != 0 and (
                "unsupported document-format" in err_lower or "application/octet-stream" in err_lower
            ):
                out["hint"] = (
                    "当前 CUPS 队列（可能使用了 AirPrint 驱动）不支持 RAW 裸流，"
                    "请切换为「系统原生驱动打印」通道，或在打印机设置中改用「局域网 TCP 9100 直连」。"
                )
            return out
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def print_pdf(self, printer_name: str, pdf_bytes: bytes, title: str = "FBA_Label") -> dict[str, object]:
        if not printer_name:
            return {"ok": False, "mode": "os_driver", "error": "未指定打印机名称"}
        if not shutil.which("lp"):
            return {"ok": False, "mode": "os_driver", "error": "未找到系统 lp 打印命令"}

        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
                tf.write(pdf_bytes)
                tmp_path = tf.name
            # 强制禁止 CUPS 彩色半色调抖动以保护条码边锐度
            res = subprocess.run(
                ["lp", "-d", printer_name, "-t", title, "-o", "ColorOption=None", tmp_path],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return {
                "ok": res.returncode == 0,
                "mode": "os_driver",
                "printer": printer_name,
                "stdout": res.stdout.strip(),
                "stderr": res.stderr.strip(),
            }
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
