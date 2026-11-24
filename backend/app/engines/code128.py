"""Code128B 完整编码器、203dpi 整数 dot 对齐矢量绘制及条码可读性评估。"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image, ImageDraw
from reportlab.pdfgen.canvas import Canvas
import zxingcpp

from app.config import DOTS_PER_MM, mm_to_pt
from app.engines.font_manager import ensure_reportlab_font, get_pil_font
from app.models.schemas import BarcodeReadabilityReport

# 标准 Code128 模式表（索引 0..106，含校验位与 7 元素 Stop 码 106）
CODE128_PATTERNS: tuple[str, ...] = (
    "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312",
    "132212", "221213", "221312", "231212", "112232", "122132", "122231", "113222",
    "123122", "123221", "223211", "221132", "221231", "213212", "223112", "312131",
    "311222", "321122", "321221", "312212", "322112", "322211", "212123", "212321",
    "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
    "231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121",
    "313121", "211331", "231131", "213113", "213311", "213131", "311123", "311321",
    "331121", "312113", "312311", "332111", "314111", "221411", "431111", "111224",
    "111422", "121124", "121421", "141122", "141221", "112214", "112412", "122114",
    "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
    "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112",
    "421211", "212141", "214121", "412121", "111143", "111341", "131141", "114113",
    "114311", "411113", "411311", "113141", "114131", "311141", "411131", "211412",
    "211214", "211232", "2331112",
)


@dataclass
class EncodedCode128:
    code: str
    bars: list[tuple[int, int]]  # (x_module_offset, module_width)
    total_modules: int


def encode_code128b(text: str) -> EncodedCode128:
    """将可打印 ASCII 字符串编码为 Code128B 相对模块条形几何序列。"""
    clean = "".join(ch if 32 <= ord(ch) <= 126 else "-" for ch in (text or "X000DEMO01"))
    if not clean:
        clean = "X000DEMO01"

    codes = [104]  # Start B
    checksum = 104
    for idx, ch in enumerate(clean, start=1):
        val = ord(ch) - 32
        codes.append(val)
        checksum += val * idx
    codes.append(checksum % 103)
    codes.append(106)  # Stop

    bars: list[tuple[int, int]] = []
    pos = 0
    for symbol in codes:
        pat = CODE128_PATTERNS[symbol]
        for i, w_char in enumerate(pat):
            w = int(w_char)
            if i % 2 == 0:
                bars.append((pos, w))
            pos += w

    return EncodedCode128(code=clean, bars=bars, total_modules=pos)


REAL_DOTS_PER_MM: float = 203.0 / 25.4
PT_PER_DOT: float = 72.0 / 203.0


def evaluate_barcode_readability(
    code: str,
    width_mm: float,
    dots_per_mm: float | None = None,
    dpi: int = 203,
) -> BarcodeReadabilityReport:
    """评估在目标热敏分辨率下条码每模块像素点数及粘连风险。"""
    enc = encode_code128b(code)
    effective_dpm = float(dots_per_mm) if dots_per_mm is not None else (float(dpi) / 25.4)
    # 两侧各至少保留 10 模块静区（共 +20 模块）计算物理有效模块密度
    usable_dots = float(width_mm) * effective_dpm
    dpm = usable_dots / (enc.total_modules + 20)
    int_dpm = max(1, int(math.floor(usable_dots / (enc.total_modules + 20))))
    if dpm < 1.35:
        level = "danger"
        msg = "条码过窄（<1.35 dots/module），热敏打印易糊边拒扫，建议拉宽条码框"
    elif dpm < 2.0:
        level = "warn"
        msg = f"接近 {dpi}dpi 最小安全宽度，建议适当拉宽或保留 >=2 dots/module"
    else:
        level = "safe"
        msg = f"条码粗细充足（>=2 dots/module），{dpi}dpi 扫码清晰"
    return BarcodeReadabilityReport(
        code=enc.code,
        total_modules=enc.total_modules,
        dots_per_module=round(dpm, 2),
        min_dots_per_module=int_dpm,
        level=level,
        message=msg,
    )


def _compute_integer_dot_layout(
    code: str,
    w_mm: float,
    dots_per_mm: float = REAL_DOTS_PER_MM,
) -> tuple[EncodedCode128, int, int, float]:
    """计算严格整数 dot 模宽 (dots_per_mod)、居中整点偏移 (x_off_dots) 及浮点兜底模宽。"""
    enc = encode_code128b(code)
    avail_dots = max(1, int(math.floor(float(w_mm) * dots_per_mm)))
    dots_per_mod = max(1, avail_dots // (enc.total_modules + 20))
    bar_span_dots = enc.total_modules * dots_per_mod
    if bar_span_dots <= avail_dots:
        x_off_dots = max(0, (avail_dots - bar_span_dots) // 2)
        return enc, dots_per_mod, x_off_dots, float(dots_per_mod)

    # 极端窄框退化为连续缩放以防越界
    float_dpm = (float(w_mm) * dots_per_mm) / (enc.total_modules + 12)
    x_off_dots = int(round(6.0 * float_dpm))
    return enc, 0, x_off_dots, float_dpm


def draw_barcode1d_on_reportlab(
    c: Canvas,
    code: str,
    x_mm: float,
    y_top_mm: float,
    w_mm: float,
    h_mm: float,
    page_h_mm: float,
    show_text: bool = True,
    font_size_pt: float = 8.5,
    dpi: int = 203,
) -> None:
    """在 ReportLab Canvas 上一体化绘制指定 DPI 严格整数 dot 对齐 Code128B 条纹及正下方可读编号。"""
    real_dpm = float(dpi) / 25.4
    pt_per_dot = 72.0 / float(dpi)
    enc, dots_per_mod, x_off_dots, float_dpm = _compute_integer_dot_layout(code, w_mm, dots_per_mm=real_dpm)

    text_band_mm = (float(font_size_pt) * 25.4 / 72.0) * 1.35 if show_text else 0.0
    bars_h_mm = max(2.5, float(h_mm) - text_band_mm)

    c.saveState()
    c.setFillColorRGB(0, 0, 0)
    c.setStrokeColorRGB(0, 0, 0)

    # ReportLab 原点在左下角，需转换 top-down 毫米坐标；水平方向对齐目标 DPI 整点防止右栏混叠拒扫
    bars_bottom_mm = page_h_mm - (y_top_mm + bars_h_mm)
    bars_h_pt = mm_to_pt(bars_h_mm)
    bars_y_pt = mm_to_pt(bars_bottom_mm)
    start_dot = int(round(float(x_mm) * real_dpm)) + x_off_dots

    for bx_mod, bw_mod in enc.bars:
        if dots_per_mod >= 1:
            bx_pt = (start_dot + bx_mod * dots_per_mod) * pt_per_dot
            bw_pt = (bw_mod * dots_per_mod) * pt_per_dot
        else:
            bx_pt = (start_dot + bx_mod * float_dpm) * pt_per_dot
            bw_pt = (bw_mod * float_dpm) * pt_per_dot
        c.rect(bx_pt, bars_y_pt, bw_pt, bars_h_pt, stroke=0, fill=1)

    if show_text:
        font_name = ensure_reportlab_font(prefer_cjk=False, bold=True)
        c.setFont(font_name, float(font_size_pt))
        center_x_pt = mm_to_pt(x_mm + w_mm / 2.0)
        text_baseline_mm = page_h_mm - (y_top_mm + float(h_mm) - (float(font_size_pt) * 25.4 / 72.0) * 0.2)
        c.drawCentredString(center_x_pt, mm_to_pt(text_baseline_mm), enc.code)

    c.restoreState()


def draw_barcode1d_on_pil(
    draw: ImageDraw.ImageDraw,
    code: str,
    x_mm: float,
    y_top_mm: float,
    w_mm: float,
    h_mm: float,
    dots_per_mm: float = DOTS_PER_MM,
    show_text: bool = True,
    font_size_pt: float = 8.5,
) -> None:
    """直接在 203dpi 1-bit/灰度 Pillow 画布上绘制严格整数 dot 对齐 Code128B 一体化条码。"""
    enc, dots_per_mod, x_off_dots, float_dpm = _compute_integer_dot_layout(code, w_mm, dots_per_mm=dots_per_mm)
    text_band_mm = (float(font_size_pt) * 25.4 / 72.0) * 1.35 if show_text else 0.0
    bars_h_mm = max(2.5, float(h_mm) - text_band_mm)

    y0 = int(round(y_top_mm * dots_per_mm))
    y1 = int(round((y_top_mm + bars_h_mm) * dots_per_mm))
    start_dot = int(round(float(x_mm) * dots_per_mm)) + x_off_dots
    step_dpm = float(dots_per_mod) if dots_per_mod >= 1 else float_dpm

    for bx_mod, bw_mod in enc.bars:
        x0 = int(round(start_dot + bx_mod * step_dpm))
        x1 = int(round(start_dot + (bx_mod + bw_mod) * step_dpm)) - 1
        if x1 >= x0:
            draw.rectangle([x0, y0, x1, max(y0, y1 - 1)], fill=0)

    if show_text:
        px_h = max(12, int(round(float(font_size_pt) * dots_per_mm * 25.4 / 72.0)))
        font = get_pil_font(px_h, enc.code, bold=True)
        cx = int(round((x_mm + w_mm / 2.0) * dots_per_mm))
        ty = int(round((y_top_mm + bars_h_mm + 0.3) * dots_per_mm))
        draw.text((cx, ty), enc.code, fill=0, font=font, anchor="mt")


def generate_qrcode_pil(data: str, scale: int = 4) -> Image.Image:
    """利用 zxing-cpp 生成带静区的锐利二值 QR 码 Pillow 图像。"""
    bc = zxingcpp.create_barcode(data or "DEMO", zxingcpp.BarcodeFormat.QRCode)
    zimg = zxingcpp.write_barcode_to_image(bc, scale=scale, add_quiet_zones=True)
    return Image.fromarray(zimg).convert("L")
