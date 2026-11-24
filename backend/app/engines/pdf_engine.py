"""PDFEngine 抽象层与一期 PyMuPDF 实现（保留未来无缝切换 pypdfium2 + pikepdf 边界）。"""

from __future__ import annotations

import base64
import io
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import pymupdf
from PIL import Image

from app.config import PAGE_BOX_MM, SAFE_BOX_MM, mm_to_pt


@dataclass
class WordSpan:
    """页内单词/字符块几何信息 (PDF pt 坐标，原点左上)。"""

    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    block_no: int
    line_no: int
    word_no: int


class PDFEngine(ABC):
    """PDF 解析、物理脱敏、自动裁边居中与 203dpi 位图栅格化抽象接口。"""

    @abstractmethod
    def get_page_count(self, pdf_bytes: bytes) -> int:
        ...

    @abstractmethod
    def get_page_dimensions_pt(self, pdf_bytes: bytes) -> list[tuple[float, float]]:
        ...

    @abstractmethod
    def extract_text_per_page(self, pdf_bytes: bytes) -> list[str]:
        ...

    @abstractmethod
    def extract_words(self, pdf_bytes: bytes, page_index: int) -> list[WordSpan]:
        ...

    @abstractmethod
    def render_page_to_pil(self, pdf_bytes: bytes, page_index: int, dpi: int = 203) -> Image.Image:
        ...

    @abstractmethod
    def render_page_to_1bit(
        self, pdf_bytes: bytes, page_index: int, dpi: int = 203, threshold: int = 160
    ) -> Image.Image:
        ...

    @abstractmethod
    def crop_and_center_vector_pdf(
        self,
        pdf_bytes: bytes,
        page_index: int = 0,
        target_page_mm: float = PAGE_BOX_MM,
        target_height_mm: float | None = None,
        safe_width_mm: float = SAFE_BOX_MM,
        safe_height_mm: float = SAFE_BOX_MM,
        offset_x_mm: float = 0.0,
        offset_y_mm: float = 0.0,
    ) -> bytes:
        ...


def detect_non_white_bbox(
    img: Image.Image,
    white_threshold: int = 245,
    pad_px: int = 2,
) -> tuple[int, int, int, int] | None:
    """在灰度图中探测全部非白有效内容像素的最小包围盒 (left, top, right, bottom)。"""
    gray = img.convert("L")
    # 将大于阈值的背景变成 0，前景非白像素变成 >0，利用 Pillow C 扩展高速求 bbox
    mask = gray.point(lambda p: 255 if p < white_threshold else 0)
    bbox = mask.getbbox()
    if bbox is None:
        return None
    l, t, r, b = bbox
    w, h = gray.size
    return (
        max(0, l - pad_px),
        max(0, t - pad_px),
        min(w, r + pad_px),
        min(h, b + pad_px),
    )


class PyMuPDFEngine(PDFEngine):
    """基于 PyMuPDF (fitz) 的高性能矢量 PDF 解析与物理红区擦除实现。"""

    def get_page_count(self, pdf_bytes: bytes) -> int:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
            return len(doc)

    def get_page_dimensions_pt(self, pdf_bytes: bytes) -> list[tuple[float, float]]:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
            return [(float(p.rect.width), float(p.rect.height)) for p in doc]

    def extract_text_per_page(self, pdf_bytes: bytes) -> list[str]:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
            return [page.get_text("text") for page in doc]

    def extract_words(self, pdf_bytes: bytes, page_index: int) -> list[WordSpan]:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
            page = doc[page_index]
            raw_words = page.get_text("words")
            return [
                WordSpan(
                    x0=float(w[0]),
                    y0=float(w[1]),
                    x1=float(w[2]),
                    y1=float(w[3]),
                    text=str(w[4]),
                    block_no=int(w[5]),
                    line_no=int(w[6]),
                    word_no=int(w[7]),
                )
                for w in raw_words
            ]

    def render_page_to_pil(self, pdf_bytes: bytes, page_index: int, dpi: int = 203) -> Image.Image:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
            page = doc[page_index]
            zoom = dpi / 72.0
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    def render_page_to_1bit(
        self, pdf_bytes: bytes, page_index: int, dpi: int = 203, threshold: int = 160
    ) -> Image.Image:
        """强制纯黑白二值阈值化（禁止 Floyd-Steinberg 半色调抖动，保护条码边缘锐度）。"""
        rgb = self.render_page_to_pil(pdf_bytes, page_index, dpi=dpi)
        gray = rgb.convert("L")
        return gray.point(lambda p: 0 if p < threshold else 255, mode="1")

    def compute_content_clip_rect_pt(
        self,
        doc: pymupdf.Document,
        page_index: int,
        probe_dpi: int = 216,
    ) -> pymupdf.Rect:
        """高精度探测页面非白有效内容区在原始 pt 坐标系下的紧凑裁切矩形。"""
        page = doc[page_index]
        zoom = probe_dpi / 72.0
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        bbox = detect_non_white_bbox(img, white_threshold=245, pad_px=4)
        if bbox is None:
            return pymupdf.Rect(page.rect)

        l, t, r, b = bbox
        scale = 72.0 / probe_dpi
        # 注意 pixmap 起点对应 page.rect.x0 / page.rect.y0
        x0 = page.rect.x0 + l * scale
        y0 = page.rect.y0 + t * scale
        x1 = page.rect.x0 + r * scale
        y1 = page.rect.y0 + b * scale
        rect = pymupdf.Rect(x0, y0, x1, y1) & page.rect
        return rect if not rect.is_empty else pymupdf.Rect(page.rect)

    def crop_and_center_vector_pdf(
        self,
        pdf_bytes: bytes,
        page_index: int = 0,
        target_page_mm: float = PAGE_BOX_MM,
        target_height_mm: float | None = None,
        safe_width_mm: float = SAFE_BOX_MM,
        safe_height_mm: float = SAFE_BOX_MM,
        offset_x_mm: float = 0.0,
        offset_y_mm: float = 0.0,
    ) -> bytes:
        """保留原 PDF 矢量/原位清晰度，自动去除留白并等比居中落版至指定尺寸（如 100×100mm 或 100×150mm）。"""
        eff_h_mm = float(target_height_mm) if target_height_mm is not None else float(target_page_mm)
        page_w_pt = mm_to_pt(target_page_mm)
        page_h_pt = mm_to_pt(eff_h_mm)
        safe_w_pt = mm_to_pt(safe_width_mm)
        safe_h_pt = mm_to_pt(safe_height_mm)
        off_x_pt = mm_to_pt(offset_x_mm)
        off_y_pt = mm_to_pt(offset_y_mm)

        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as src_doc:
            clip_rect = self.compute_content_clip_rect_pt(src_doc, page_index)
            cw = max(1.0, float(clip_rect.width))
            ch = max(1.0, float(clip_rect.height))
            ratio = min(safe_w_pt / cw, safe_h_pt / ch)
            dest_w = cw * ratio
            dest_h = ch * ratio

            # 居中落版并叠加打印机毫米校准微调，强制夹紧在页面安全框内
            cx = (page_w_pt - dest_w) / 2.0 + off_x_pt
            cy = (page_h_pt - dest_h) / 2.0 + off_y_pt
            margin_x = max(0.0, (page_w_pt - safe_w_pt) / 2.0)
            margin_y = max(0.0, (page_h_pt - safe_h_pt) / 2.0)
            cx = min(max(cx, margin_x), page_w_pt - margin_x - dest_w)
            cy = min(max(cy, margin_y), page_h_pt - margin_y - dest_h)

            dest_rect = pymupdf.Rect(cx, cy, cx + dest_w, cy + dest_h)

            out_doc = pymupdf.open()
            out_page = out_doc.new_page(width=page_w_pt, height=page_h_pt)
            out_page.show_pdf_page(dest_rect, src_doc, page_index, clip=clip_rect)
            return out_doc.tobytes(garbage=3, deflate=True)


def merge_single_page_pdfs(page_pdfs: list[bytes]) -> bytes:
    """将多个单页 PDF 按给定顺序合并为一个多页打印 PDF。"""
    out = pymupdf.open()
    for pbytes in page_pdfs:
        with pymupdf.open(stream=pbytes, filetype="pdf") as d:
            out.insert_pdf(d)
    return out.tobytes(garbage=3, deflate=True)


def render_pdf_page_png_data_url(pdf_bytes: bytes, page_index: int = 0, dpi: int = 150) -> str:
    """将指定 PDF 单页光栅化为 PNG Data URL，供前端高清预览与卷帘对比使用。"""
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        page = doc[page_index]
        zoom = dpi / 72.0
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def get_default_pdf_engine() -> PyMuPDFEngine:
    """获取当前配置的 PDF 引擎实例。"""
    return PyMuPDFEngine()
