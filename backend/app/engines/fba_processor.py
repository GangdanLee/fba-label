"""FBA 外箱标中英文语义锚点物理脱敏与 98×98mm 安全区落版引擎。"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Literal

import pymupdf
from PIL import Image

from app.config import PAGE_BOX_MM, SAFE_BOX_MM, mm_to_pt
from app.engines.amazon_fc_codes import extract_amazon_fc_code
from app.engines.font_manager import ensure_reportlab_font
from app.engines.pdf_engine import (
    PyMuPDFEngine,
    WordSpan,
    detect_non_white_bbox,
    merge_single_page_pdfs,
    render_pdf_page_png_data_url,
)
from app.models.schemas import FbaBoxMeta, FbaRedactionOptions

SHIPMENT_ID_RE = re.compile(r"\b(FBA[A-Z0-9]{6,12})\b", re.IGNORECASE)
BOX_ID_RE = re.compile(r"\b((FBA[A-Z0-9]{6,12})U\d{3,8})\b", re.IGNORECASE)
WH_CODE_RE = re.compile(r"\b([A-Z]{3}\d)\b")
BOX_SEQ_EN_RE = re.compile(r"Box\s*(\d+)\s*of\s*(\d+)", re.IGNORECASE)
BOX_SEQ_ZH_RE = re.compile(r"纸箱编号\s*(\d+)\s*[，,/\s]\s*(?:共\s*)?(\d+)")
QTY_RE = re.compile(r"(?:Qty|数量)[:：\s]*(\d+)", re.IGNORECASE)


@dataclass
class _TextLine:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    words: list[WordSpan]

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2.0


def _group_words_into_lines(words: list[WordSpan]) -> list[_TextLine]:
    buckets: dict[tuple[int, int], list[WordSpan]] = {}
    for w in words:
        buckets.setdefault((w.block_no, w.line_no), []).append(w)

    lines: list[_TextLine] = []
    for _, grp in buckets.items():
        grp.sort(key=lambda item: item.x0)
        lines.append(
            _TextLine(
                x0=min(w.x0 for w in grp),
                y0=min(w.y0 for w in grp),
                x1=max(w.x1 for w in grp),
                y1=max(w.y1 for w in grp),
                text=" ".join(w.text for w in grp),
                words=grp,
            )
        )
    lines.sort(key=lambda ln: (round(ln.y0, 1), ln.x0))
    return lines


def detect_fba_lang(text: str) -> Literal["en", "zh", "unknown"]:
    if any(k in text for k in ("发货地", "目的地", "纸箱编号", "请不要遮住此标签")):
        return "zh"
    if any(k in text.upper() for k in ("SHIP FROM", "SHIP TO", "LEAVE THIS LABEL")):
        return "en"
    return "unknown"


def _extract_warehouse(text: str, file_name: str) -> str | None:
    return extract_amazon_fc_code(text, file_name)


_SKU_SKIP_WORDS: frozenset[str] = frozenset(
    {"QTY", "UNITS", "UNIT", "PCS", "BOX", "BOXES", "TOTAL", "MADE", "IN", "CHINA", "PLEASE", "LEAVE"}
)


def _extract_sku_info(text: str) -> tuple[str | None, bool]:
    """识别标签中的 Single SKU / SKU: 或 Mixed SKU 混装箱标志。"""
    raw = text or ""
    if re.search(r"\b(?:Mixed\s+SKUs?|Multiple\s+SKUs?)\b|混合\s*SKU|多\s*SKU", raw, re.IGNORECASE):
        return None, True

    patterns = (
        re.compile(r"(?:Single\s+SKU|单个\s*SKU)\s*[:：-]?\s*(?:\r?\n\s*)?([A-Za-z0-9][A-Za-z0-9._-]{1,48})", re.IGNORECASE),
        re.compile(r"\bSKU\s*[:：]\s*([A-Za-z0-9][A-Za-z0-9._-]{1,48})", re.IGNORECASE),
        re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]{2,48})\s*[·•|/]\s*Qty\b", re.IGNORECASE),
        re.compile(r"\b(X0[0-9A-Z]{8})\b"),
    )
    for pat in patterns:
        m = pat.search(raw)
        if not m:
            continue
        cand = m.group(1).strip()
        up = cand.upper()
        if up in _SKU_SKIP_WORDS or re.match(r"^FBA[A-Z0-9]{6,}", up):
            continue
        return cand, False

    return None, False


def _parse_box_meta(
    text: str,
    file_id: str,
    file_name: str,
    page_index: int,
    fallback_total: int,
) -> FbaBoxMeta:
    box_m = BOX_ID_RE.search(text)
    box_id = box_m.group(1).upper() if box_m else None

    shipment_id: str | None = None
    if box_m:
        shipment_id = box_m.group(2).upper()
    else:
        for cand in SHIPMENT_ID_RE.findall(f"{text}\n{file_name}"):
            up = cand.upper()
            if not re.search(r"U\d{3,8}$", up):
                shipment_id = up
                break

    box_idx = page_index + 1
    total_boxes = fallback_total
    seq_en = BOX_SEQ_EN_RE.search(text)
    seq_zh = BOX_SEQ_ZH_RE.search(text)
    if seq_en:
        box_idx = int(seq_en.group(1))
        total_boxes = int(seq_en.group(2))
    elif seq_zh:
        box_idx = int(seq_zh.group(1))
        total_boxes = int(seq_zh.group(2))

    if box_id is None and shipment_id:
        box_id = f"{shipment_id}U{box_idx:06d}"

    qty_m = QTY_RE.search(text)
    has_mic = bool(re.search(r"made\s+in\s+china", text, re.IGNORECASE))
    sku_text, is_mixed = _extract_sku_info(text)

    return FbaBoxMeta(
        file_id=file_id,
        file_name=file_name,
        page_index=page_index,
        shipment_id=shipment_id,
        box_id=box_id,
        box_index=box_idx,
        total_boxes=total_boxes,
        warehouse_code=_extract_warehouse(text, file_name),
        lang=detect_fba_lang(text),
        sku_text=sku_text,
        is_mixed_sku=is_mixed,
        qty=int(qty_m.group(1)) if qty_m else None,
        has_made_in_china=has_mic,
    )


def _find_header_band_bottom_y(page: pymupdf.Page, lines: list[_TextLine]) -> float:
    """定位地址区域下界（黑色条码标题条或主条码上方边界），避免擦伤下方条码。"""
    # 优先用文本锚点（FBA STA / Created: / U000）确定地址区下界
    for ln in lines:
        up = ln.text.upper()
        if "FBA STA" in up or "CREATED:" in up:
            return max(40.0, ln.y0 - 2.0)

    # 其次找水平长黑条或分隔线
    page_w = float(page.rect.width)
    min_y = page.rect.height * 0.55
    for d in page.get_drawings():
        r = d.get("rect")
        if r and r.width > page_w * 0.45 and 1.0 <= r.height <= 36.0 and r.y0 > 80.0:
            fill = d.get("fill")
            # 寻找地址下方的黑色带或底部分隔条
            if fill is not None and sum(fill) < 0.6:
                min_y = min(min_y, float(r.y0))
    return min_y


def _compute_redaction_rects(
    page: pymupdf.Page,
    lines: list[_TextLine],
    options: FbaRedactionOptions,
) -> list[pymupdf.Rect]:
    """根据页面语义锚点动态生成物理擦除矩形（兼容中英文左右互异栏位）。"""
    rects: list[pymupdf.Rect] = []
    from_hdr: _TextLine | None = None
    to_hdr: _TextLine | None = None

    for ln in lines:
        up = ln.text.upper().strip()
        if ("SHIP FROM" in up or "发货地" in ln.text) and from_hdr is None:
            from_hdr = ln
        if ("SHIP TO" in up or "目的地" in ln.text) and to_hdr is None:
            to_hdr = ln

    bar_bottom_y = _find_header_band_bottom_y(page, lines)
    page_w = float(page.rect.width)

    # 动态判定左右栏分界线
    if from_hdr and to_hdr:
        mid_x = (from_hdr.x0 + to_hdr.x0) / 2.0
        # 修正：若两栏同行，取两者起始与结束间合理分隔点
        if abs(from_hdr.x0 - to_hdr.x0) > 40.0:
            left_hdr, right_hdr = (from_hdr, to_hdr) if from_hdr.x0 < to_hdr.x0 else (to_hdr, from_hdr)
            mid_x = (left_hdr.x1 + right_hdr.x0) / 2.0
        else:
            mid_x = page_w * 0.5
        from_on_left = from_hdr.x0 < mid_x
    else:
        mid_x = page_w * 0.5
        from_on_left = True

    from_x_range = (0.0, mid_x) if from_on_left else (mid_x, page_w)
    to_x_range = (mid_x, page_w) if from_on_left else (0.0, mid_x)

    # 1. 抹除 SHIP FROM: / 发货地：下方所有发件人地址行
    if options.redact_ship_from and from_hdr is not None:
        top_limit = from_hdr.y1 + 0.6
        for ln in lines:
            if (
                from_x_range[0] - 2.0 <= ln.x0 <= from_x_range[1]
                and ln.center_y > top_limit
                and ln.y1 <= bar_bottom_y + 1.0
            ):
                rects.append(pymupdf.Rect(ln.x0 - 1.0, ln.y0 - 0.5, ln.x1 + 1.5, ln.y1 + 0.5))

    # 2. 抹除 SHIP TO: / 目的地：栏内 "FBA:" 后面的公司名，保留 "FBA:" 与后续仓库名/地址
    if options.redact_fba_company:
        to_top_y = (to_hdr.y0 - 1.0) if to_hdr is not None else 0.0
        for ln in lines:
            if not (to_x_range[0] - 2.0 <= ln.x0 <= to_x_range[1]):
                continue
            if not (to_top_y <= ln.center_y <= bar_bottom_y + 1.0):
                continue
            compact = ln.text.strip()
            if not re.match(r"^FBA\s*[:：]", compact, re.IGNORECASE):
                continue

            # 定位 "FBA:" 前缀的精确右边界，仅抹除冒号之后的内容
            first_w = ln.words[0]
            if len(ln.words) == 1:
                m_pref = re.match(r"^(FBA\s*[:：])\s*(.+)$", first_w.text, re.IGNORECASE)
                if m_pref:
                    prefix_ratio = len(m_pref.group(1)) / max(1, len(first_w.text))
                    keep_x1 = first_w.x0 + (first_w.x1 - first_w.x0) * prefix_ratio + 0.5
                    rects.append(pymupdf.Rect(keep_x1, ln.y0 - 0.5, ln.x1 + 1.5, ln.y1 + 0.5))
            else:
                # 确定冒号所在单词，之后全部词纳入红区
                keep_idx = 0
                if ":" not in first_w.text and "：" not in first_w.text and len(ln.words) > 1 and ln.words[1].text in (":", "："):
                    keep_idx = 1
                if keep_idx + 1 < len(ln.words):
                    redact_x0 = ln.words[keep_idx + 1].x0 - 0.5
                    rects.append(pymupdf.Rect(redact_x0, ln.y0 - 0.5, ln.x1 + 1.5, ln.y1 + 0.5))
                else:
                    # 冒号和公司名黏在同一词里（如 FBA:DemoCorp）
                    w_txt = ln.words[keep_idx].text
                    m_col = re.match(r"^(FBA\s*[:：])(.+)$", w_txt, re.IGNORECASE)
                    if m_col:
                        ratio = len(m_col.group(1)) / len(w_txt)
                        rx0 = ln.words[keep_idx].x0 + (ln.words[keep_idx].x1 - ln.words[keep_idx].x0) * ratio + 0.4
                        rects.append(pymupdf.Rect(rx0, ln.y0 - 0.5, ln.x1 + 1.5, ln.y1 + 0.5))

    # 3. 可选抹除顶部 FBA / Box X of Y / SHIP FROM / SHIP TO 标题词
    if options.redact_headers:
        hdr_bottom = max(
            from_hdr.y1 + 1.0 if from_hdr else 0.0,
            to_hdr.y1 + 1.0 if to_hdr else 0.0,
        )
        for ln in lines:
            up = ln.text.upper().strip()
            if ln.y1 <= hdr_bottom + 1.0 and (
                up.startswith("FBA")
                or "BOX " in up
                or "纸箱编号" in ln.text
                or "SHIP FROM" in up
                or "SHIP TO" in up
                or "发货地" in ln.text
                or "目的地" in ln.text
            ):
                rects.append(pymupdf.Rect(ln.x0 - 1.0, ln.y0 - 0.5, ln.x1 + 1.5, ln.y1 + 0.5))

    return rects


def _draw_made_in_china_safely(pdf_bytes: bytes) -> bytes:
    """在 100×100mm 安全区左下空白区域补印矢量 'Made In China'，避免压字。"""
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        page = doc[0]
        zoom = 2.0  # 144dpi 探针像素图
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")

        page_pt = mm_to_pt(PAGE_BOX_MM)
        # 候选位置从标准左下安全留白到稍高安全留白依次探测碰撞
        candidates_mm = [
            (8.0, 82.0),
            (8.0, 91.5),
            (8.0, 74.0),
            (10.0, 94.5),
        ]
        chosen_pt: tuple[float, float] = (mm_to_pt(8.0), mm_to_pt(82.0))
        box_w_px = int(mm_to_pt(32.0) * zoom)
        box_h_px = int(mm_to_pt(6.0) * zoom)

        for cx_mm, cy_mm in candidates_mm:
            px0 = int(mm_to_pt(cx_mm) * zoom)
            py0 = int(mm_to_pt(cy_mm - 5.0) * zoom)
            region = img.crop((px0, max(0, py0), min(img.width, px0 + box_w_px), min(img.height, py0 + box_h_px)))
            if detect_non_white_bbox(region, white_threshold=245, pad_px=0) is None:
                chosen_pt = (mm_to_pt(cx_mm), mm_to_pt(cy_mm))
                break

        # 用英文内置 Helvetica-Bold 插入清晰矢量字
        ensure_reportlab_font(prefer_cjk=False, bold=True)
        # 确保不溢出 98×98 安全框 [1mm..99mm]
        tx = min(max(chosen_pt[0], mm_to_pt(2.0)), page_pt - mm_to_pt(35.0))
        ty = min(max(chosen_pt[1], mm_to_pt(6.0)), page_pt - mm_to_pt(3.0))
        page.insert_text(
            pymupdf.Point(tx, ty),
            "Made In China",
            fontname="helv",
            fontsize=10.5,
            color=(0, 0, 0),
        )
        return doc.tobytes(garbage=3, deflate=True)


def process_fba_pdf(
    pdf_bytes: bytes,
    file_id: str,
    file_name: str,
    options: FbaRedactionOptions | None = None,
    engine: PyMuPDFEngine | None = None,
) -> tuple[list[FbaBoxMeta], bytes]:
    """解析 FBA 外箱 PDF 全部页面，执行物理真脱敏并自动裁切居中为 100×100mm（有效区 <=98×98mm）。"""
    opts = options or FbaRedactionOptions()
    eng = engine or PyMuPDFEngine()
    single_pages: list[bytes] = []
    boxes: list[FbaBoxMeta] = []

    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as src_doc:
        total_pages = len(src_doc)
        for idx in range(total_pages):
            page = src_doc[idx]
            page_text = page.get_text("text")
            meta = _parse_box_meta(page_text, file_id=file_id, file_name=file_name, page_index=idx, fallback_total=total_pages)

            # 在单页临时文档中执行物理红区擦除，保证完全隔离且底层文本流被清除
            tmp_doc = pymupdf.open()
            tmp_doc.insert_pdf(src_doc, from_page=idx, to_page=idx)
            raw_single_bytes = tmp_doc.tobytes(garbage=3, deflate=True)
            tmp_page = tmp_doc[0]

            words = [
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
                for w in tmp_page.get_text("words")
            ]
            lines = _group_words_into_lines(words)
            redact_rects = _compute_redaction_rects(tmp_page, lines, opts)
            meta.redacted_regions_count = len(redact_rects)

            for r in redact_rects:
                tmp_page.add_redact_annot(r, fill=(1, 1, 1))
            if redact_rects:
                tmp_page.apply_redactions(
                    images=pymupdf.PDF_REDACT_IMAGE_NONE,
                    graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                    text=pymupdf.PDF_REDACT_TEXT_REMOVE,
                )

            redacted_single_bytes = tmp_doc.tobytes(garbage=3, deflate=True)
            tmp_doc.close()

            raw_centered_bytes = eng.crop_and_center_vector_pdf(
                raw_single_bytes,
                page_index=0,
                target_page_mm=PAGE_BOX_MM,
                safe_width_mm=opts.safe_width_mm,
                safe_height_mm=opts.safe_height_mm,
                offset_x_mm=opts.offset_x_mm,
                offset_y_mm=opts.offset_y_mm,
            )
            centered_bytes = eng.crop_and_center_vector_pdf(
                redacted_single_bytes,
                page_index=0,
                target_page_mm=PAGE_BOX_MM,
                safe_width_mm=opts.safe_width_mm,
                safe_height_mm=opts.safe_height_mm,
                offset_x_mm=opts.offset_x_mm,
                offset_y_mm=opts.offset_y_mm,
            )

            if opts.auto_add_mic and not meta.has_made_in_china:
                centered_bytes = _draw_made_in_china_safely(centered_bytes)
                meta.mic_auto_added = True

            meta.full_page_b64 = render_pdf_page_png_data_url(raw_single_bytes, page_index=0, dpi=110)
            meta.raw_preview_b64 = render_pdf_page_png_data_url(raw_centered_bytes, page_index=0, dpi=150)
            meta.clean_preview_b64 = render_pdf_page_png_data_url(centered_bytes, page_index=0, dpi=150)

            single_pages.append(centered_bytes)
            boxes.append(meta)

    merged_pdf = merge_single_page_pdfs(single_pages)
    return boxes, merged_pdf
