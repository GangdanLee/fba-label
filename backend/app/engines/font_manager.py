"""跨平台系统字体探测与 CJK 字体嵌入回退管理器。"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PIL import ImageFont
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

_REGISTERED_RL_FONTS: dict[str, str] = {}

CJK_FONT_CANDIDATES: tuple[str, ...] = (
    # macOS 常见系统 CJK 字体（注意优先单独 TTF 或可用 .ttc）
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    # Windows 常见系统 CJK 字体
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    # Linux 常见开源 CJK 字体
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
)

LATIN_BOLD_CANDIDATES: tuple[str, ...] = (
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)

LATIN_REGULAR_CANDIDATES: tuple[str, ...] = (
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
)


def _first_existing(paths: Iterable[str]) -> str | None:
    for p in paths:
        if Path(p).is_file():
            return p
    return None


def find_cjk_font_path() -> str | None:
    """返回首个本机可用的 CJK 字体路径。"""
    return _first_existing(CJK_FONT_CANDIDATES)


def ensure_reportlab_font(prefer_cjk: bool = True, bold: bool = False) -> str:
    """向 ReportLab 注册并返回一个可用字体名，确保中文不会报 KeyError 或丢字。"""
    if not prefer_cjk:
        return "Helvetica-Bold" if bold else "Helvetica"

    cache_key = f"cjk_{'b' if bold else 'r'}"
    if cache_key in _REGISTERED_RL_FONTS:
        return _REGISTERED_RL_FONTS[cache_key]

    candidates = list(CJK_FONT_CANDIDATES)
    for font_path in candidates:
        if not Path(font_path).is_file():
            continue
        rl_name = f"AppCJK_{Path(font_path).stem.replace(' ', '_')}"
        if rl_name in pdfmetrics.getRegisteredFontNames():
            _REGISTERED_RL_FONTS[cache_key] = rl_name
            return rl_name
        try:
            if font_path.lower().endswith(".ttc"):
                pdfmetrics.registerFont(TTFont(rl_name, font_path, subfontIndex=0))
            else:
                pdfmetrics.registerFont(TTFont(rl_name, font_path))
            _REGISTERED_RL_FONTS[cache_key] = rl_name
            return rl_name
        except Exception:
            continue

    return "Helvetica-Bold" if bold else "Helvetica"


def get_pil_font(size_px: int, text: str = "", bold: bool = False) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    """获取用于 Pillow 203dpi 位图渲染的字体对象，按字符集自动选择 CJK 或西文字体。"""
    has_non_ascii = any(ord(ch) > 127 for ch in text)
    if has_non_ascii:
        cjk = find_cjk_font_path()
        if cjk:
            try:
                return ImageFont.truetype(cjk, size_px, index=0)
            except Exception:
                pass

    latins = LATIN_BOLD_CANDIDATES if bold else LATIN_REGULAR_CANDIDATES
    latin_path = _first_existing(latins)
    if latin_path:
        try:
            return ImageFont.truetype(latin_path, size_px, index=0)
        except Exception:
            pass

    cjk = find_cjk_font_path()
    if cjk:
        try:
            return ImageFont.truetype(cjk, size_px, index=0)
        except Exception:
            pass

    return ImageFont.load_default()


def contains_cjk(text: str) -> bool:
    """判断字符串是否包含中日韩或全角非 ASCII 字符。"""
    return any(ord(ch) > 127 for ch in text)
