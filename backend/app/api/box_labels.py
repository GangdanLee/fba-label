"""外箱标签脱敏裁切、货代箱唛解析与多票配对编排接口。"""

from __future__ import annotations

import base64
import csv
import io
import json
import re
import uuid
import zipfile
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
import pymupdf
from reportlab.pdfgen.canvas import Canvas

from app import db
from app.config import PAGE_BOX_MM, mm_to_pt
from app.engines.carrier_parser import preview_carrier_rules_on_text, process_carrier_pdf
from app.engines.fba_processor import process_fba_pdf
from app.engines.fnsku_engine import _draw_element
from app.engines.font_manager import ensure_reportlab_font
from app.engines.pairing_engine import _evaluate_group_printable, build_print_queue, pair_and_validate
from app.models.schemas import (
    BoxPrintPreferences,
    CanvasElement,
    CarrierProcessResponse,
    CarrierRule,
    FbaProcessResponse,
    FbaRedactionOptions,
    PairingGroup,
    PairingRequest,
    PairingResponse,
    PrintQueueItem,
)

router = APIRouter(prefix="/api/box", tags=["box"])


class CarrierRuleTestRequest(BaseModel):
    sample_text: str = ""
    file_name: str = ""
    rules: list[CarrierRule] | None = None


class MergedPdfExportRequest(BaseModel):
    fba_pdfs_b64: dict[str, str] = Field(default_factory=dict)
    carrier_pdfs_b64: dict[str, str] = Field(default_factory=dict)
    queue: list[PrintQueueItem] = Field(default_factory=list)
    overlay_elements: list[CanvasElement] = Field(default_factory=list)
    paper_size: Literal["100x100", "100x150"] | None = None


def _build_overlay_single_page_pdf(
    elements: list[CanvasElement],
    page_w_mm: float = PAGE_BOX_MM,
    page_h_mm: float = PAGE_BOX_MM,
) -> bytes:
    """将外箱叠加层元素渲染为透明背景单页矢量 PDF（支持 100×100mm 与 100×150mm）。"""
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=(mm_to_pt(page_w_mm), mm_to_pt(page_h_mm)))
    for el in elements:
        _draw_element(c, el, ox_mm=0.0, oy_mm=0.0, page_h_mm=page_h_mm)
    c.showPage()
    c.save()
    return buf.getvalue()


@router.post("/process-fba", response_model=FbaProcessResponse)
async def process_fba_endpoint(
    file: UploadFile = File(...),
    redact_ship_from: bool = Form(True),
    redact_fba_company: bool = Form(True),
    redact_headers: bool = Form(False),
    auto_add_mic: bool = Form(True),
    awd_apply_redaction: bool = Form(False),
    paper_size: Literal["100x100", "100x150"] = Form("100x100"),
    offset_x_mm: float = Form(0.0),
    offset_y_mm: float = Form(0.0),
) -> FbaProcessResponse:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")

    file_id = f"fba_{uuid.uuid4().hex[:8]}"
    opts = FbaRedactionOptions(
        redact_ship_from=redact_ship_from,
        redact_fba_company=redact_fba_company,
        redact_headers=redact_headers,
        auto_add_mic=auto_add_mic,
        awd_apply_redaction=awd_apply_redaction,
        paper_size=paper_size,
        safe_width_mm=98.0,
        safe_height_mm=148.0 if paper_size == "100x150" else 98.0,
        offset_x_mm=offset_x_mm,
        offset_y_mm=offset_y_mm,
    )
    try:
        boxes, out_pdf = process_fba_pdf(
            raw,
            file_id=file_id,
            file_name=file.filename or "fba.pdf",
            options=opts,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"FBA/AWD 外箱标签处理失败: {exc}") from exc

    ship_id = next((b.shipment_id for b in boxes if b.shipment_id), None)
    wh = next((b.warehouse_code for b in boxes if b.warehouse_code), None)
    label_type: Literal["fba", "awd"] = "awd" if any(b.label_type == "awd" for b in boxes) else "fba"
    return FbaProcessResponse(
        file_id=file_id,
        file_name=file.filename or "fba.pdf",
        page_count=len(boxes),
        label_type=label_type,
        paper_size=paper_size,
        shipment_id=ship_id,
        warehouse_code=wh,
        boxes=boxes,
        pdf_b64=base64.b64encode(out_pdf).decode("ascii"),
    )


@router.post("/process-carrier", response_model=CarrierProcessResponse)
async def process_carrier_endpoint(
    file: UploadFile = File(...),
    paper_size: Literal["100x100", "100x150"] = Form("100x100"),
    offset_x_mm: float = Form(0.0),
    offset_y_mm: float = Form(0.0),
) -> CarrierProcessResponse:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")

    file_id = f"car_{uuid.uuid4().hex[:8]}"
    rules = db.list_carrier_rules()
    target_h = 150.0 if paper_size == "100x150" else PAGE_BOX_MM
    safe_h = 148.0 if paper_size == "100x150" else 98.0
    try:
        items, out_pdf = process_carrier_pdf(
            raw,
            file_id=file_id,
            file_name=file.filename or "carrier.pdf",
            rules=rules,
            target_width_mm=PAGE_BOX_MM,
            target_height_mm=target_h,
            safe_width_mm=98.0,
            safe_height_mm=safe_h,
            offset_x_mm=offset_x_mm,
            offset_y_mm=offset_y_mm,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"货代箱唛处理失败: {exc}") from exc

    ship_id = next((c.shipment_id for c in items if c.shipment_id), None)
    wh = next((c.warehouse_code for c in items if c.warehouse_code), None)
    return CarrierProcessResponse(
        file_id=file_id,
        file_name=file.filename or "carrier.pdf",
        page_count=len(items),
        paper_size=paper_size,
        shipment_id=ship_id,
        warehouse_code=wh,
        items=items,
        pdf_b64=base64.b64encode(out_pdf).decode("ascii"),
    )


@router.post("/pair", response_model=PairingResponse)
async def pair_boxes_endpoint(req: PairingRequest) -> PairingResponse:
    return pair_and_validate(req)


def _draw_fitted_centered(
    c: Canvas,
    text: str,
    cx_pt: float,
    y_pt: float,
    max_w_pt: float,
    font_name: str,
    max_pt: float,
    min_pt: float = 6.5,
) -> None:
    """按物理边框宽度自适应缩放字号，超长尾部截断省略，防止分隔页文字冲出框外。"""
    clean = (text or "-").strip() or "-"
    size = float(max_pt)
    while size > min_pt and c.stringWidth(clean, font_name, size) > max_w_pt:
        size = round(size - 0.5, 1)
    if c.stringWidth(clean, font_name, size) > max_w_pt:
        trimmed = clean
        while len(trimmed) > 3 and c.stringWidth(trimmed + "...", font_name, size) > max_w_pt:
            trimmed = trimmed[:-1]
        clean = trimmed + "..."
    c.setFont(font_name, size)
    c.drawCentredString(cx_pt, y_pt, clean)


def _build_separator_page_pdf(
    item: PrintQueueItem,
    page_w_mm: float = PAGE_BOX_MM,
    page_h_mm: float = PAGE_BOX_MM,
) -> bytes:
    """用 ReportLab 绘制高对比黑白分隔提示页（自动适配 100×100 / 100×150），防止跨仓/换单连续打印贴混。"""
    buf = io.BytesIO()
    page_w_pt = mm_to_pt(page_w_mm)
    page_h_pt = mm_to_pt(page_h_mm)
    c = Canvas(buf, pagesize=(page_w_pt, page_h_pt))
    font_bold = ensure_reportlab_font(prefer_cjk=True, bold=True)
    font_reg = ensure_reportlab_font(prefer_cjk=True, bold=False)

    # 外边框与顶部黑底警醒横幅
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(2.0)
    c.rect(mm_to_pt(4), mm_to_pt(4), mm_to_pt(page_w_mm - 8), mm_to_pt(page_h_mm - 8), stroke=1, fill=0)
    c.setFillColorRGB(0, 0, 0)
    c.rect(mm_to_pt(4), mm_to_pt(page_h_mm - 20), mm_to_pt(page_w_mm - 8), mm_to_pt(16), stroke=0, fill=1)

    max_w_pt = mm_to_pt(page_w_mm - 16)
    cx_pt = mm_to_pt(page_w_mm / 2)
    mid_offset_mm = (page_h_mm - PAGE_BOX_MM) * 0.45

    c.setFillColorRGB(1, 1, 1)
    _draw_fitted_centered(c, "出纸分隔提示 · 请核对换仓 / 换款", cx_pt, mm_to_pt(page_h_mm - 14), max_w_pt, font_bold, 13.0)

    c.setFillColorRGB(0, 0, 0)
    wh_text = (item.warehouse_code or "待确认仓库").strip()
    _draw_fitted_centered(c, wh_text, cx_pt, mm_to_pt(page_h_mm - 42 - mid_offset_mm * 0.4), max_w_pt, font_bold, 26.0, min_pt=14.0)

    c.setLineWidth(0.8)
    line_y = page_h_mm - 50 - mid_offset_mm * 0.5
    c.line(mm_to_pt(12), mm_to_pt(line_y), mm_to_pt(page_w_mm - 12), mm_to_pt(line_y))

    detail_str = item.separator_detail or "后续为此仓对应外箱标签"
    sku_disp = (item.sku_text or "").strip()
    if not sku_disp:
        if "混装箱" in detail_str:
            sku_disp = "混装箱 (Mixed SKU)"
        elif "未识别 SKU" in detail_str:
            sku_disp = "未识别 SKU"
        else:
            sku_disp = "-"

    _draw_fitted_centered(c, f"SKU: {sku_disp}", cx_pt, mm_to_pt(line_y - 12), max_w_pt, font_bold, 11.0)
    _draw_fitted_centered(
        c,
        f"货件编号: {item.shipment_id or '-'}",
        cx_pt,
        mm_to_pt(line_y - 22),
        max_w_pt,
        font_reg,
        10.0,
    )
    _draw_fitted_centered(c, detail_str, cx_pt, mm_to_pt(line_y - 32), max_w_pt, font_reg, 10.0)

    c.setFont(font_reg, 8.5)
    c.drawCentredString(cx_pt, mm_to_pt(10), "FBA Label Studio · 分仓防错贴提示页（请勿当外箱标贴箱）")
    c.showPage()
    c.save()
    return buf.getvalue()


def _render_queue_to_pdf_bytes(
    queue: list[PrintQueueItem],
    fba_pdfs_b64: dict[str, str],
    carrier_pdfs_b64: dict[str, str],
    overlay_elements: list[CanvasElement] | None = None,
    paper_size: Literal["100x100", "100x150"] | None = None,
) -> bytes:
    """根据有序队列拼接矢量标签与分隔提示页，输出完整打印 PDF 字节流（统一 100×100 或 100×150 尺寸）。"""
    if not queue:
        raise HTTPException(status_code=400, detail="打印队列为空")

    docs_cache: dict[tuple[str, str], pymupdf.Document] = {}
    out_doc = pymupdf.open()
    overlay_doc: pymupdf.Document | None = None

    try:
        for fid, b64 in fba_pdfs_b64.items():
            docs_cache[("fba", fid)] = pymupdf.open(stream=base64.b64decode(b64), filetype="pdf")
        for fid, b64 in carrier_pdfs_b64.items():
            docs_cache[("carrier", fid)] = pymupdf.open(stream=base64.b64decode(b64), filetype="pdf")

        first_fba = next((d for (k, _), d in docs_cache.items() if k == "fba"), None)
        first_car = next((d for (k, _), d in docs_cache.items() if k == "carrier"), None)

        page_w_mm = PAGE_BOX_MM
        page_h_mm = 150.0 if paper_size == "100x150" else PAGE_BOX_MM
        if paper_size is None:
            sample_doc = first_fba or first_car
            if sample_doc is not None and len(sample_doc) > 0:
                rect = sample_doc[0].rect
                w_mm = rect.width * 25.4 / 72.0
                h_mm = rect.height * 25.4 / 72.0
                if h_mm > 125.0:
                    page_w_mm = round(w_mm, 1)
                    page_h_mm = 150.0

        if overlay_elements:
            ov_bytes = _build_overlay_single_page_pdf(overlay_elements, page_w_mm=page_w_mm, page_h_mm=page_h_mm)
            overlay_doc = pymupdf.open(stream=ov_bytes, filetype="pdf")

        for item in queue:
            if item.is_separator:
                sep_bytes = _build_separator_page_pdf(item, page_w_mm=page_w_mm, page_h_mm=page_h_mm)
                with pymupdf.open(stream=sep_bytes, filetype="pdf") as sep_doc:
                    out_doc.insert_pdf(sep_doc, from_page=0, to_page=0)
                continue

            doc = docs_cache.get((item.kind, item.file_id)) or (first_fba if item.kind == "fba" else first_car)
            if doc is None or item.page_index < 0 or item.page_index >= len(doc):
                raise HTTPException(status_code=400, detail=f"缺失 {item.kind} 文件页 (file_id={item.file_id}, page={item.page_index})")
            out_doc.insert_pdf(doc, from_page=item.page_index, to_page=item.page_index)
            if overlay_doc is not None and item.kind == "fba":
                target_page = out_doc[-1]
                target_page.show_pdf_page(target_page.rect, overlay_doc, 0)

        return out_doc.tobytes(garbage=3, deflate=True)
    finally:
        if overlay_doc is not None:
            overlay_doc.close()
        out_doc.close()
        for d in docs_cache.values():
            d.close()


def _build_manifest_csv_bytes(rows: list[list[object]], headers: list[str]) -> bytes:
    """生成带 UTF-8-BOM 头的标准核对 CSV，确保 Excel 与 WPS 直接双打开无乱码。"""
    sio = io.StringIO()
    writer = csv.writer(sio, lineterminator="\r\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return ("\ufeff" + sio.getvalue()).encode("utf-8")


def _queue_item_to_manifest_row(item: PrintQueueItem, output_file: str = "") -> list[object]:
    kind_label = "分隔提示页" if item.is_separator else ("亚马逊外箱" if item.kind == "fba" else "货代箱唛")
    note = item.separator_title if item.is_separator else f"第{item.copy_no}份"
    row: list[object] = [
        item.seq,
        kind_label,
        item.sku_text or "-",
        item.warehouse_code or "-",
        item.shipment_id or "-",
        "-" if item.is_separator else item.box_index,
        "-" if item.is_separator else item.copy_no,
        item.source_file_name or "-",
        "-" if item.is_separator else item.source_page_no,
        note,
    ]
    if output_file:
        row.append(output_file)
    return row


class ManifestCsvExportRequest(BaseModel):
    queue: list[PrintQueueItem] = Field(default_factory=list)
    title: str = "queue"


class SkuZipExportRequest(BaseModel):
    fba_pdfs_b64: dict[str, str] = Field(default_factory=dict)
    carrier_pdfs_b64: dict[str, str] = Field(default_factory=dict)
    groups: list[PairingGroup] = Field(default_factory=list)
    group_by: Literal["shipment", "sku"] = "sku"
    work_mode: Literal["paired", "fba_only", "carrier_only"] = "paired"
    order_mode: Literal["interleave", "per_box_group", "split_all"] = "per_box_group"
    insert_separator_pages: bool = False
    force_unlocked: bool = False
    overlay_elements: list[CanvasElement] = Field(default_factory=list)
    paper_size: Literal["100x100", "100x150"] | None = None


@router.post("/export-merged-pdf")
async def export_merged_pdf_endpoint(req: MergedPdfExportRequest) -> dict[str, object]:
    """根据出纸队列精确拼接各箱矢量标签页并导出完整打印 PDF。"""
    merged_bytes = _render_queue_to_pdf_bytes(
        queue=req.queue,
        fba_pdfs_b64=req.fba_pdfs_b64,
        carrier_pdfs_b64=req.carrier_pdfs_b64,
        overlay_elements=req.overlay_elements,
        paper_size=req.paper_size,
    )
    return {
        "page_count": len(req.queue),
        "pdf_b64": base64.b64encode(merged_bytes).decode("ascii"),
    }


@router.post("/export-manifest-csv")
async def export_manifest_csv_endpoint(req: ManifestCsvExportRequest) -> dict[str, object]:
    """导出出纸核对明细 CSV（UTF-8-BOM，含 SKU/仓点/来源文件名与页码映射）。"""
    if not req.queue:
        raise HTTPException(status_code=400, detail="出纸队列为空，无法导出核对明细")
    headers = ["出纸序号", "标签类型", "SKU", "目标仓库", "FBA货件号", "箱号", "副本序号", "来源文件名", "原始页码", "说明"]
    rows = [_queue_item_to_manifest_row(item) for item in req.queue]
    csv_bytes = _build_manifest_csv_bytes(rows, headers)
    safe_title = re.sub(r"[^A-Za-z0-9._-]+", "_", (req.title or "queue").strip())[:48] or "queue"
    return {
        "filename": f"{safe_title}_出纸核对明细.csv",
        "row_count": len(rows),
        "csv_b64": base64.b64encode(csv_bytes).decode("ascii"),
    }


@router.post("/export-sku-zip")
async def export_sku_zip_endpoint(req: SkuZipExportRequest) -> dict[str, object]:
    """按每个分组（SKU 或货件）生成独立矢量 PDF（跳过未配对或存在冲突阻断的组），打包附带统一核对明细 CSV。"""
    if not req.groups:
        raise HTTPException(status_code=400, detail="当前没有可导出的分组数据")

    headers = ["出纸序号", "标签类型", "SKU", "目标仓库", "FBA货件号", "箱号", "副本序号", "来源文件名", "原始页码", "说明", "输出文件"]
    all_manifest_rows: list[list[object]] = []
    file_count = 0
    total_pages = 0
    used_names: set[str] = set()
    skipped_groups: list[str] = []
    effective_group_by = "shipment" if (req.group_by == "shipment" or req.groups[0].group_kind == "shipment") else "sku"

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for grp in req.groups:
            raw_label = (grp.display_label or grp.shipment_id or f"group_{file_count + 1}").strip()
            can_print, _ = _evaluate_group_printable(grp, req.work_mode, req.force_unlocked)
            if not can_print:
                skipped_groups.append(raw_label)
                continue

            q = build_print_queue(
                grp,
                work_mode=req.work_mode,
                order_mode=req.order_mode,
                insert_separator_pages=req.insert_separator_pages,
            )
            if not q:
                skipped_groups.append(raw_label)
                continue
            pdf_bytes = _render_queue_to_pdf_bytes(
                queue=q,
                fba_pdfs_b64=req.fba_pdfs_b64,
                carrier_pdfs_b64=req.carrier_pdfs_b64,
                overlay_elements=req.overlay_elements,
                paper_size=req.paper_size,
            )
            safe_base = re.sub(r'[\\/:*?"<>|\s]+', "_", raw_label)[:48].strip("_") or f"group_{file_count + 1}"
            fname = f"{safe_base}_{len(q)}pages.pdf"
            if fname in used_names:
                fname = f"{safe_base}_{file_count + 1}_{len(q)}pages.pdf"
            used_names.add(fname)

            zf.writestr(fname, pdf_bytes)
            file_count += 1
            total_pages += len(q)
            for item in q:
                all_manifest_rows.append(_queue_item_to_manifest_row(item, output_file=fname))

        if file_count == 0:
            raise HTTPException(
                status_code=400,
                detail="没有通过配对校验的可导出分组（请补齐外箱/箱唛或排查仓点/箱数冲突）",
            )

        csv_bytes = _build_manifest_csv_bytes(all_manifest_rows, headers)
        zf.writestr("出纸核对明细.csv", csv_bytes)

    zip_prefix = "FBA_Label_按货件分组" if effective_group_by == "shipment" else "FBA_Label_按SKU归集"
    unit_word = "票" if effective_group_by == "shipment" else "款"
    return {
        "filename": f"{zip_prefix}_{file_count}{unit_word}_{total_pages}页.zip",
        "file_count": file_count,
        "total_pages": total_pages,
        "group_by": effective_group_by,
        "skipped_groups": skipped_groups,
        "zip_b64": base64.b64encode(zip_buf.getvalue()).decode("ascii"),
    }


def _validate_rule_regex(label: str, pattern: str) -> None:
    if not (pattern or "").strip():
        return
    try:
        re.compile(pattern)
    except re.error as exc:
        raise HTTPException(status_code=400, detail=f"{label} 正则语法无效: {exc}") from exc


@router.get("/carrier-rules", response_model=list[CarrierRule])
async def get_carrier_rules() -> list[CarrierRule]:
    return db.list_carrier_rules(include_disabled=True)


@router.post("/carrier-rules", response_model=CarrierRule)
async def upsert_carrier_rule_endpoint(rule: CarrierRule) -> CarrierRule:
    _validate_rule_regex("货件号规则", rule.shipment_regex)
    _validate_rule_regex("仓点规则", rule.warehouse_regex)
    _validate_rule_regex("箱号规则", rule.ctn_regex)
    return db.upsert_carrier_rule(rule)


@router.delete("/carrier-rules/{rule_id}")
async def delete_carrier_rule_endpoint(rule_id: str) -> dict[str, bool]:
    if rule_id == "rule_default":
        raise HTTPException(status_code=400, detail="内置默认解析规则不可删除，可停用或新增自定义规则覆盖")
    if not db.delete_carrier_rule(rule_id):
        raise HTTPException(status_code=404, detail="未找到指定的解析规则")
    return {"ok": True}


@router.post("/carrier-rules/test")
async def test_carrier_rules_endpoint(req: CarrierRuleTestRequest) -> dict[str, object]:
    for r in req.rules or []:
        _validate_rule_regex(f"规则「{r.name}」货件号", r.shipment_regex)
        _validate_rule_regex(f"规则「{r.name}」仓点", r.warehouse_regex)
        _validate_rule_regex(f"规则「{r.name}」箱号", r.ctn_regex)
    rules = req.rules if req.rules is not None else db.list_carrier_rules(include_disabled=False)
    return preview_carrier_rules_on_text(req.sample_text, req.file_name, rules)


_BOX_PREFS_KEY = "box_print_preferences"


@router.get("/preferences", response_model=BoxPrintPreferences)
async def get_box_preferences() -> BoxPrintPreferences:
    """获取持久化的外箱打印配比组合、出纸顺序与脱敏规则默认偏好。"""
    raw = db.get_app_state(_BOX_PREFS_KEY, "")
    if not raw:
        return BoxPrintPreferences()
    try:
        return BoxPrintPreferences.model_validate_json(raw)
    except Exception:
        return BoxPrintPreferences()


@router.put("/preferences", response_model=BoxPrintPreferences)
async def save_box_preferences(prefs: BoxPrintPreferences) -> BoxPrintPreferences:
    """将用户常用的 FBA / 货代箱唛张数配比、出纸顺序与脱敏规则默认留存到 SQLite。"""
    if prefs.default_fba_copies == 0 and prefs.default_carrier_copies == 0:
        raise HTTPException(status_code=400, detail="FBA 外箱与货代箱唛默认张数不能同时为 0")
    db.set_app_state(_BOX_PREFS_KEY, json.dumps(prefs.model_dump(), ensure_ascii=False))
    return prefs
