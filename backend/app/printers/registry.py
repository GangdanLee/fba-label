"""通用热敏与办公打印机品牌/型号协议及精度启发式识别。"""

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
    "XPRINTER",
    "XP-",
    "GAINSCHA",
    "GPRINTER",
    "GP-",
    "HPRT",
    "QR-",
    "DELI",
    "ROLLO",
    "MUNBYN",
    "JIOSE",
    "BEEPRT",
    "PHOMEMO",
    "POLONO",
    "LABELRANGE",
    "THERMAL",
    "TSPL",
)

_OS_DRIVER_THERMAL_KEYWORDS = ("BROTHER", "QL-", "DYMO", "LABELWRITER")
_DPI_300_RE = re.compile(r"(?:^|[^0-9])(?:300|345|344|346)(?:DPI|D)?(?:$|[^0-9])|TE300|TE310|300DPI", re.IGNORECASE)


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
