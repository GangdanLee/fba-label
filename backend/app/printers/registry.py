"""通用热敏与办公打印机品牌/型号协议、精度及实用兼容性启发式识别。"""

from __future__ import annotations

import re
from typing import Literal

_ZPL_KEYWORDS = (
    "ZEBRA",
    "ZDESIGNER",
    "GK888",
    "GX420",
    "GX430",
    "ZD220",
    "ZD230",
    "ZD420",
    "ZD421",
    "ZD620",
    "ZT230",
    "ZT410",
    "ZT411",
    "HONEYWELL",
    "INTERMEC",
    "POSTEK",
    "ZPL",
)

_TSPL_KEYWORDS = (
    "TSC",
    "TTP",
    "TE200",
    "TE244",
    "TE300",
    "TE310",
    "TDP-",
    "TX300",
    "MB340",
    "MH340",
    "XPRINTER",
    "芯烨",
    "XP-",
    "XP420",
    "XP450",
    "XP460",
    "XP470",
    "XP490",
    "GAINSCHA",
    "GPRINTER",
    "佳博",
    "GP-",
    "GP1",
    "GP2",
    "GP3",
    "GP4",
    "GP9",
    "GS-",
    "HPRT",
    "汉印",
    "QR-",
    "启锐",
    "DELI",
    "得力",
    "4BARCODE",
    "4B-",
    "ROLLO",
    "MUNBYN",
    "JIOSE",
    "BEEPRT",
    "PHOMEMO",
    "POLONO",
    "LABELRANGE",
    "BARCODE PRINTER",
    "LABEL PRINTER",
    "THERMAL",
    "TSPL",
)

_OS_DRIVER_THERMAL_KEYWORDS = ("BROTHER", "QL-", "DYMO", "LABELWRITER")

_DPI_300_RE = re.compile(
    r"(?:^|[^0-9])(?:300|345|344|346)(?:DPI|D)?(?:$|[^0-9])"
    r"|TE300|TE310|TX300|MB340|MH340|TTP-?34[0-9]"
    r"|GP-?1134|GP-?1334|GP-?1534|GP-?2134|GP-?3134|GS-?340"
    r"|XP-?TT437|XP-?T371|XP-?H400|300DPI",
    re.IGNORECASE,
)


def infer_printer_hints(
    printer_name: str,
) -> tuple[Literal["tspl", "zpl", "os_driver"], Literal[203, 300], bool]:
    """根据系统打印机驱动名称推断推荐协议、打印头 DPI 与是否属于专用热敏机。"""
    upper = (printer_name or "").upper()
    dpi_hint: Literal[203, 300] = 300 if _DPI_300_RE.search(upper) else 203

    if any(kw in upper for kw in _OS_DRIVER_THERMAL_KEYWORDS):
        return ("os_driver", dpi_hint, True)
    if any(kw in upper for kw in _ZPL_KEYWORDS):
        return ("zpl", dpi_hint, True)
    if any(kw in upper for kw in _TSPL_KEYWORDS):
        return ("tspl", dpi_hint, True)
    return ("os_driver", 203, False)


def infer_printer_brand_note(printer_name: str) -> tuple[str, str]:
    """返回品牌友好简称与针对国产热敏机的模式/驱动排错提示。"""
    upper = (printer_name or "").upper()
    if any(kw in upper for kw in ("XPRINTER", "芯烨", "XP-", "XP420", "XP450", "XP460", "XP470", "XP490")):
        return (
            "芯烨 Xprinter (TSPL2)",
            "如 XP-420B 等机型：请确认机器处于 TSPL 标签模式（非 ESC/POS 小票模式）；Windows 若缺队列可装 4BARCODE 4B-2054A 驱动或通过网口 TCP 9100 直连。",
        )
    if any(kw in upper for kw in ("GPRINTER", "佳博", "GAINSCHA", "GP-", "GP1", "GP2", "GP3", "GP4", "GP9", "GS-")):
        return (
            "佳博 Gprinter (TSPL2)",
            "支持 GP-1324D / GP-1134T / GP-3120TU 等 TSPL 兼容机型；若出现撕纸位不准或偏移，系统已内置 REFERENCE 0,0 与 SET TEAR ON 重置，如遇反白可在下方开启位图反色补偿。",
        )
    if any(kw in upper for kw in ("4BARCODE", "4B-")):
        return (
            "4BARCODE / 兼容热敏 (TSPL2)",
            "兼容芯烨/佳博 OEM TSPL2 指令集，推荐使用裸指令直出（TSPL2）通道。",
        )
    if any(kw in upper for kw in ("TSC", "TTP", "TE200", "TE244", "TE300", "TE310", "TDP-")):
        return (
            "TSC 原生 TSPL2",
            "macOS 若系统驱动使用 AirPrint 拒绝 RAW 数据流，请改选「系统原生驱动打印」通道或删改队列为通用 Raw/CUPS。",
        )
    if any(kw in upper for kw in _ZPL_KEYWORDS):
        return (
            "Zebra / ZPL II",
            "原生 ^GF ASCII Hex 位图直出；300dpi 机型请在下方选择 300 dpi。",
        )
    if any(kw in upper for kw in ("HPRT", "汉印", "QR-", "启锐", "DELI", "得力", "ROLLO", "MUNBYN")):
        return (
            "TSPL2 兼容热敏机",
            "支持 1-bit TSPL2 裸指令直出与系统驱动兜底打印。",
        )
    if any(kw in upper for kw in _OS_DRIVER_THERMAL_KEYWORDS):
        return (
            "系统原生驱动热敏机",
            "建议使用「系统原生驱动打印」通道。",
        )
    return ("", "")
