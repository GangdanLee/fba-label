"""离线 203dpi 1-bit 仿真图输出与 zxing-cpp 自动扫码回归检查器。"""

from __future__ import annotations

import base64
import io

from PIL import Image
import zxingcpp

from app.engines.pdf_engine import PyMuPDFEngine


def scan_barcodes_from_image(img: Image.Image) -> list[dict[str, str]]:
    """使用 zxing-cpp 对 203dpi 位图执行真实机读扫码识别。"""
    gray = img.convert("L")
    results = zxingcpp.read_barcodes(gray)
    return [
        {
            "text": r.text,
            "format": str(r.format),
        }
        for r in results
        if r.valid
    ]


def render_pdf_page_to_1bit_png_b64(pdf_bytes: bytes, page_index: int = 0, dpi: int = 203) -> str:
    """将指定 PDF 页按目标精度（203/300dpi）转换为 1-bit PNG Base64，供前端模拟仿真对比或测试查看。"""
    eng = PyMuPDFEngine()
    img_1bit = eng.render_page_to_1bit(pdf_bytes, page_index=page_index, dpi=dpi, threshold=160)
    buf = io.BytesIO()
    img_1bit.convert("L").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def render_pdf_page_to_203dpi_png_b64(pdf_bytes: bytes, page_index: int = 0) -> str:
    """向后兼容包装：按 203dpi 输出 1-bit PNG Base64。"""
    return render_pdf_page_to_1bit_png_b64(pdf_bytes, page_index=page_index, dpi=203)
