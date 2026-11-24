"""亚马逊产品标签 PDF 解析、中文成色清洗与自由画布单/双排渲染引擎。"""

from __future__ import annotations

import base64
import csv
import io
import math
import re

import pymupdf
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from app.config import mm_to_pt
from app.engines.code128 import draw_barcode1d_on_reportlab, generate_qrcode_pil
from app.engines.font_manager import contains_cjk, ensure_reportlab_font
from app.models.schemas import BatchSkuItem, CanvasElement, FnskuBatchRenderRequest, FnskuRenderRequest

FNSKU_RE = re.compile(r"\b(X0[A-Z0-9]{8})\b")


def clean_product_title(raw_title: str) -> str:
    """清洗亚马逊中文产品标常见成色前缀（'新品'->'New'、全角标点转半角）。"""
    cleaned = (raw_title or "").replace("：", ":").replace("（", "(").replace("）", ")").replace("，", ",")
    cleaned = re.sub(r"^\s*新品\s*[-:：]?\s*", "New - ", cleaned)
    cleaned = re.sub(r"\s*[-–]\s*新品\s*$", " (New)", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def parse_amazon_product_pdf(pdf_bytes: bytes) -> dict[str, str]:
    """从亚马逊导出的产品标签 PDF 中提取 FNSKU、原标题、清洗后标题与默认一体化元素列表。"""
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        if len(doc) == 0:
            raise ValueError("上传的 PDF 不包含任何页面")
        text = doc[0].get_text("text")

    fnsku_m = FNSKU_RE.search(text.upper())
    fnsku = fnsku_m.group(1) if fnsku_m else "X009DEMO01"

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    content_lines = [ln for ln in lines if ln.upper() != fnsku]
    raw_title = " ".join(content_lines[:2]) if content_lines else "Demo Product Item"
    clean_title = clean_product_title(raw_title)

    return {
        "fnsku": fnsku,
        "title_raw": raw_title,
        "title_clean": clean_title,
    }


def _wrap_text_to_width(
    c: Canvas,
    text: str,
    max_width_pt: float,
    font_name: str,
    font_size: float,
) -> list[str]:
    """按词边界优先（兼顾中英文混合及超长单词退回字符断行）适配物理盒宽。"""
    lines: list[str] = []
    for para in (text or "").split("\n"):
        if not para:
            lines.append("")
            continue
        tokens = re.findall(r"[A-Za-z0-9\-_/.:()]+|\s+|.", para)
        cur = ""
        for tok in tokens:
            if not cur and tok.isspace():
                continue
            nxt = cur + tok
            if c.stringWidth(nxt, font_name, font_size) <= max_width_pt:
                cur = nxt
                continue
            if cur:
                lines.append(cur.rstrip())
                cur = ""
            if tok.isspace():
                continue
            if c.stringWidth(tok, font_name, font_size) <= max_width_pt:
                cur = tok
            else:
                for ch in tok:
                    nxt_c = cur + ch
                    if c.stringWidth(nxt_c, font_name, font_size) <= max_width_pt or not cur:
                        cur = nxt_c
                    else:
                        lines.append(cur)
                        cur = ch
        if cur:
            lines.append(cur.rstrip())
    return lines or [""]


def _draw_element(
    c: Canvas,
    el: CanvasElement,
    ox_mm: float,
    oy_mm: float,
    page_h_mm: float,
    dpi: int = 203,
) -> None:
    """将单个统一画布元素精确渲染到 ReportLab PDF（top-down mm 转 PDF bottom-up pt）。"""
    ex = el.x + ox_mm
    ey = el.y + oy_mm

    c.saveState()
    if el.rotate:
        cx_pt = mm_to_pt(ex + el.w / 2.0)
        cy_pt = mm_to_pt(page_h_mm - (ey + el.h / 2.0))
        c.translate(cx_pt, cy_pt)
        c.rotate(-el.rotate)
        c.translate(-cx_pt, -cy_pt)

    if el.type == "mask":
        c.setFillColorRGB(1, 1, 1)
        c.rect(
            mm_to_pt(ex),
            mm_to_pt(page_h_mm - (ey + el.h)),
            mm_to_pt(el.w),
            mm_to_pt(el.h),
            stroke=0,
            fill=1,
        )
    elif el.type == "rect":
        c.setStrokeColorRGB(0, 0, 0)
        c.setLineWidth(mm_to_pt(el.stroke_width or 0.4))
        if el.dashed:
            c.setDash(3, 2)
        fill_flag = 1 if el.fill and el.fill != "none" else 0
        if fill_flag:
            c.setFillColorRGB(1, 1, 1)
        c.rect(
            mm_to_pt(ex),
            mm_to_pt(page_h_mm - (ey + el.h)),
            mm_to_pt(el.w),
            mm_to_pt(el.h),
            stroke=1,
            fill=fill_flag,
        )
    elif el.type == "line":
        c.setStrokeColorRGB(0, 0, 0)
        c.setLineWidth(mm_to_pt(el.stroke_width or 0.35))
        if el.dashed:
            c.setDash(3, 2)
        mid_y_pt = mm_to_pt(page_h_mm - (ey + el.h / 2.0))
        c.line(mm_to_pt(ex), mid_y_pt, mm_to_pt(ex + el.w), mid_y_pt)
    elif el.type == "barcode1d":
        draw_barcode1d_on_reportlab(
            c=c,
            code=el.code or "X000DEMO01",
            x_mm=ex,
            y_top_mm=ey,
            w_mm=el.w,
            h_mm=el.h,
            page_h_mm=page_h_mm,
            show_text=el.show_text,
            font_size_pt=el.font_size or 8.5,
            dpi=dpi,
        )
    elif el.type == "qrcode":
        qr_img = generate_qrcode_pil(el.code or "DEMO", scale=4)
        c.drawImage(
            ImageReader(qr_img),
            mm_to_pt(ex),
            mm_to_pt(page_h_mm - (ey + el.h)),
            width=mm_to_pt(el.w),
            height=mm_to_pt(el.h),
            preserveAspectRatio=True,
            mask="auto",
        )
    elif el.type == "image" and el.image_data_url:
        b64 = el.image_data_url.split(",", 1)[1] if "," in el.image_data_url else el.image_data_url
        raw = base64.b64decode(b64)
        c.drawImage(
            ImageReader(io.BytesIO(raw)),
            mm_to_pt(ex),
            mm_to_pt(page_h_mm - (ey + el.h)),
            width=mm_to_pt(el.w),
            height=mm_to_pt(el.h),
            preserveAspectRatio=True,
            mask="auto",
        )
    elif el.type == "text":
        txt = el.text or ""
        font_pt = float(el.font_size or 7.5)
        font_name = ensure_reportlab_font(prefer_cjk=contains_cjk(txt), bold=el.bold)
        c.setFillColorRGB(0, 0, 0)
        c.setFont(font_name, font_pt)
        wrapped = _wrap_text_to_width(c, txt, mm_to_pt(max(2.0, el.w)), font_name, font_pt)
        line_h_mm = (font_pt * 25.4 / 72.0) * float(el.line_height or 1.2)
        for idx, line_str in enumerate(wrapped):
            base_y_mm = ey + (font_pt * 25.4 / 72.0) * 0.9 + idx * line_h_mm
            if base_y_mm > ey + el.h + 1.5:
                break
            py = mm_to_pt(page_h_mm - base_y_mm)
            if el.align == "center":
                c.drawCentredString(mm_to_pt(ex + el.w / 2.0), py, line_str)
            elif el.align == "right":
                c.drawRightString(mm_to_pt(ex + el.w), py, line_str)
            else:
                c.drawString(mm_to_pt(ex), py, line_str)

    c.restoreState()


def render_fnsku_elements_pdf(req: FnskuRenderRequest) -> bytes:
    """将统一画布元素集按单排或双排物理毫米渲染为精确尺寸的多页 PDF。"""
    is_double = req.layout_type == "double"
    page_w_mm = (req.width_mm * 2.0 + req.col_gap_mm) if is_double else req.width_mm
    page_h_mm = req.height_mm
    page_w_pt = mm_to_pt(page_w_mm)
    page_h_pt = mm_to_pt(page_h_mm)

    buf = io.BytesIO()
    c = Canvas(buf, pagesize=(page_w_pt, page_h_pt))

    total_labels = max(1, int(req.qty))
    total_pages = math.ceil(total_labels / 2) if is_double else total_labels

    for page_idx in range(total_pages):
        # 绘制左栏（或单排页）
        for el in req.elements:
            _draw_element(c, el, ox_mm=req.offset_x_mm, oy_mm=req.offset_y_mm, page_h_mm=page_h_mm, dpi=req.dpi)

        # 若为双排且尚有第 2 个标签需要打印，平移 width_mm + col_gap_mm 绘制右栏；奇数末行留空
        if is_double:
            second_label_num = page_idx * 2 + 2
            if second_label_num <= total_labels:
                right_ox = req.width_mm + req.col_gap_mm + req.offset_x_mm
                for el in req.elements:
                    _draw_element(c, el, ox_mm=right_ox, oy_mm=req.offset_y_mm, page_h_mm=page_h_mm, dpi=req.dpi)

        c.showPage()

    c.save()
    return buf.getvalue()


_CSV_SKU_ALIASES = {"sku", "sellersku", "msku", "商品sku", "货号", "sku编号"}
_CSV_FNSKU_ALIASES = {"fnsku", "条码", "条码编号", "barcode", "code", "x00"}
_CSV_TITLE_ALIASES = {"title", "titleclean", "商品名称", "品名", "标题", "商品描述", "名称", "描述", "name", "description"}
_CSV_QTY_ALIASES = {"qty", "quantity", "数量", "打印张数", "张数", "copies", "count"}


def _decode_csv_text(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_sku_csv_bytes(raw: bytes) -> dict[str, object]:
    """解析多编码 CSV/TSV 清单，识别中英文列头并自动清洗中文成色，返回明细与异常告警。"""
    text = _decode_csv_text(raw).strip("\r\n")
    if not text.strip():
        raise ValueError("上传的 CSV 清单为空")

    first_line = text.splitlines()[0]
    delimiter = "\t" if first_line.count("\t") > first_line.count(",") else ","
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delimiter) if any(cell.strip() for cell in r)]
    if not rows:
        raise ValueError("CSV 中未找到有效数据行")

    norm_header = [re.sub(r"[\s_\-]", "", cell.strip().lstrip("\ufeff").lower()) for cell in rows[0]]
    col_map: dict[str, int] = {}
    for idx, name in enumerate(norm_header):
        if name in _CSV_SKU_ALIASES and "sku" not in col_map:
            col_map["sku"] = idx
        elif name in _CSV_FNSKU_ALIASES and "fnsku" not in col_map:
            col_map["fnsku"] = idx
        elif name in _CSV_TITLE_ALIASES and "title" not in col_map:
            col_map["title"] = idx
        elif name in _CSV_QTY_ALIASES and "qty" not in col_map:
            col_map["qty"] = idx

    warnings: list[str] = []
    start_row = 1
    if "fnsku" not in col_map:
        # 若首行包含形如 X0... 的 FNSKU 值则视为无表头 CSV，按 [sku, fnsku, title, qty] 兜底
        has_fnsku_in_first = any(FNSKU_RE.search(cell.strip().upper()) for cell in rows[0])
        if has_fnsku_in_first and len(rows[0]) >= 2:
            col_map = {"sku": 0, "fnsku": 1}
            if len(rows[0]) >= 3:
                col_map["title"] = 2
            if len(rows[0]) >= 4:
                col_map["qty"] = 3
            start_row = 0
            warnings.append("未检测到标准表头，已按默认列序 [SKU, FNSKU, 标题, 数量] 解析")
        else:
            raise ValueError("未识别到 FNSKU 列头，请确认首行包含 fnsku / 条码 等列名（或下载模板参考）")

    items: list[dict[str, object]] = []
    for row_no, row in enumerate(rows[start_row:], start=start_row + 1):
        def _cell(key: str) -> str:
            idx = col_map.get(key)
            if idx is None or idx >= len(row):
                return ""
            return row[idx].strip()

        fnsku = _cell("fnsku").upper()
        if not fnsku:
            warnings.append(f"第 {row_no} 行缺少 FNSKU 条码，已跳过")
            continue

        raw_qty = _cell("qty")
        if not raw_qty:
            qty = 1
        else:
            try:
                qty_f = float(raw_qty)
                if not qty_f.is_integer() or qty_f < 1 or qty_f > 9999:
                    raise ValueError("qty out of range")
                qty = int(qty_f)
            except ValueError:
                warnings.append(f"第 {row_no} 行 ({fnsku}) 数量「{raw_qty}」无效（需为 1~9999 整数），已跳过")
                continue

        sku = _cell("sku") or fnsku
        title = clean_product_title(_cell("title"))
        items.append({"sku": sku, "fnsku": fnsku, "title": title, "qty": qty})

    if not items:
        raise ValueError("未提取到有效可打印的 SKU 条目：" + ("；".join(warnings) if warnings else "请检查 CSV 内容"))

    return {
        "items": items,
        "total_skus": len(items),
        "total_labels": sum(int(it["qty"]) for it in items),
        "warnings": warnings,
    }


def _clone_elements_for_sku(template_elements: list[CanvasElement], item: BatchSkuItem) -> list[CanvasElement]:
    """基于模板画布生成单款 SKU 专属元素列表：替换主条码、同步 QR 码与商品描述，保留合规固定元素。"""
    primary_bc_idx = next((i for i, e in enumerate(template_elements) if e.type == "barcode1d"), None)
    orig_code = template_elements[primary_bc_idx].code if primary_bc_idx is not None else None

    title_idx = next(
        (
            i
            for i, e in enumerate(template_elements)
            if e.type == "text"
            and (
                "title" in (e.id or "").lower()
                or any(k in (e.name or "") for k in ("商品", "标题", "名称", "描述"))
            )
        ),
        None,
    )
    if title_idx is None:
        fixed_marks = {"made in china", "new", "ce", "ukca"}
        title_idx = next(
            (
                i
                for i, e in enumerate(template_elements)
                if e.type == "text" and (e.text or "").strip().lower() not in fixed_marks
            ),
            None,
        )

    cloned: list[CanvasElement] = []
    for i, el in enumerate(template_elements):
        copy_el = el.model_copy(deep=True)
        if i == primary_bc_idx:
            copy_el.code = item.fnsku
        elif el.type == "qrcode" and orig_code and (el.code or "") == orig_code:
            copy_el.code = item.fnsku
        elif i == title_idx and item.title.strip():
            copy_el.text = item.title.strip()
        cloned.append(copy_el)
    return cloned


def render_fnsku_batch_pdf(req: FnskuBatchRenderRequest) -> tuple[bytes, int, int]:
    """将多款 SKU 清单按单排或双排（支持跨 SKU 强制换行右栏留白）批量渲染为矢量 PDF。"""
    is_double = req.layout_type == "double"
    page_w_mm = (req.width_mm * 2.0 + req.col_gap_mm) if is_double else req.width_mm
    page_h_mm = req.height_mm

    slots: list[list[CanvasElement] | None] = []
    total_labels = 0
    for item in req.items:
        sku_elements = _clone_elements_for_sku(req.template_elements, item)
        for _ in range(item.qty):
            slots.append(sku_elements)
            total_labels += 1
        if is_double and req.page_break_between_skus and len(slots) % 2 == 1:
            slots.append(None)

    buf = io.BytesIO()
    c = Canvas(buf, pagesize=(mm_to_pt(page_w_mm), mm_to_pt(page_h_mm)))
    total_pages = 0

    if not is_double:
        for slot in slots:
            if slot is None:
                continue
            for el in slot:
                _draw_element(c, el, ox_mm=req.offset_x_mm, oy_mm=req.offset_y_mm, page_h_mm=page_h_mm, dpi=req.dpi)
            c.showPage()
            total_pages += 1
    else:
        for idx in range(0, len(slots), 2):
            left_slot = slots[idx]
            right_slot = slots[idx + 1] if idx + 1 < len(slots) else None
            if left_slot is not None:
                for el in left_slot:
                    _draw_element(c, el, ox_mm=req.offset_x_mm, oy_mm=req.offset_y_mm, page_h_mm=page_h_mm, dpi=req.dpi)
            if right_slot is not None:
                right_ox = req.width_mm + req.col_gap_mm + req.offset_x_mm
                for el in right_slot:
                    _draw_element(c, el, ox_mm=right_ox, oy_mm=req.offset_y_mm, page_h_mm=page_h_mm, dpi=req.dpi)
            c.showPage()
            total_pages += 1

    c.save()
    return buf.getvalue(), total_pages, total_labels
