"""外箱标签脱敏裁切、货代箱唛解析与多票配对编排接口。"""

from __future__ import annotations

import base64
import io
import json
import re
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
import pymupdf
from reportlab.pdfgen.canvas import Canvas

from app import db
from app.config import PAGE_BOX_MM, mm_to_pt
from app.engines.carrier_parser import preview_carrier_rules_on_text, process_carrier_pdf
from app.engines.fba_processor import process_fba_pdf
from app.engines.fnsku_engine import _draw_element
from app.engines.pairing_engine import pair_and_validate
from app.models.schemas import (
    BoxPrintPreferences,
    CanvasElement,
    CarrierProcessResponse,
    CarrierRule,
    FbaProcessResponse,
    FbaRedactionOptions,
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


def _build_overlay_single_page_pdf(elements: list[CanvasElement], page_mm: float = PAGE_BOX_MM) -> bytes:
    """将外箱叠加层元素渲染为透明背景单页矢量 PDF。"""
    buf = io.BytesIO()
    page_pt = mm_to_pt(page_mm)
    c = Canvas(buf, pagesize=(page_pt, page_pt))
    for el in elements:
        _draw_element(c, el, ox_mm=0.0, oy_mm=0.0, page_h_mm=page_mm)
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
        raise HTTPException(status_code=400, detail=f"FBA 外箱标签处理失败: {exc}") from exc

    ship_id = next((b.shipment_id for b in boxes if b.shipment_id), None)
    wh = next((b.warehouse_code for b in boxes if b.warehouse_code), None)
    return FbaProcessResponse(
        file_id=file_id,
        file_name=file.filename or "fba.pdf",
        page_count=len(boxes),
        shipment_id=ship_id,
        warehouse_code=wh,
        boxes=boxes,
        pdf_b64=base64.b64encode(out_pdf).decode("ascii"),
    )


@router.post("/process-carrier", response_model=CarrierProcessResponse)
async def process_carrier_endpoint(
    file: UploadFile = File(...),
    offset_x_mm: float = Form(0.0),
    offset_y_mm: float = Form(0.0),
) -> CarrierProcessResponse:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")

    file_id = f"car_{uuid.uuid4().hex[:8]}"
    rules = db.list_carrier_rules()
    try:
        items, out_pdf = process_carrier_pdf(
            raw,
            file_id=file_id,
            file_name=file.filename or "carrier.pdf",
            rules=rules,
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
        shipment_id=ship_id,
        warehouse_code=wh,
        items=items,
        pdf_b64=base64.b64encode(out_pdf).decode("ascii"),
    )


@router.post("/pair", response_model=PairingResponse)
async def pair_boxes_endpoint(req: PairingRequest) -> PairingResponse:
    return pair_and_validate(req)


@router.post("/export-merged-pdf")
async def export_merged_pdf_endpoint(req: MergedPdfExportRequest) -> dict[str, object]:
    """根据出纸队列精确拼接各箱矢量标签页并导出完整打印 PDF。"""
    if not req.queue:
        raise HTTPException(status_code=400, detail="打印队列为空")

    docs_cache: dict[tuple[str, str], pymupdf.Document] = {}
    out_doc = pymupdf.open()
    overlay_doc: pymupdf.Document | None = None

    try:
        if req.overlay_elements:
            ov_bytes = _build_overlay_single_page_pdf(req.overlay_elements, page_mm=PAGE_BOX_MM)
            overlay_doc = pymupdf.open(stream=ov_bytes, filetype="pdf")

        for fid, b64 in req.fba_pdfs_b64.items():
            docs_cache[("fba", fid)] = pymupdf.open(stream=base64.b64decode(b64), filetype="pdf")
        for fid, b64 in req.carrier_pdfs_b64.items():
            docs_cache[("carrier", fid)] = pymupdf.open(stream=base64.b64decode(b64), filetype="pdf")

        first_fba = next((d for (k, _), d in docs_cache.items() if k == "fba"), None)
        first_car = next((d for (k, _), d in docs_cache.items() if k == "carrier"), None)

        for item in req.queue:
            doc = docs_cache.get((item.kind, item.file_id)) or (first_fba if item.kind == "fba" else first_car)
            if doc is None or item.page_index < 0 or item.page_index >= len(doc):
                raise HTTPException(status_code=400, detail=f"缺失 {item.kind} 文件页 (file_id={item.file_id}, page={item.page_index})")
            out_doc.insert_pdf(doc, from_page=item.page_index, to_page=item.page_index)
            if overlay_doc is not None and item.kind == "fba":
                target_page = out_doc[-1]
                target_page.show_pdf_page(target_page.rect, overlay_doc, 0)

        merged_bytes = out_doc.tobytes(garbage=3, deflate=True)
        return {
            "page_count": len(out_doc),
            "pdf_b64": base64.b64encode(merged_bytes).decode("ascii"),
        }
    finally:
        if overlay_doc is not None:
            overlay_doc.close()
        out_doc.close()
        for d in docs_cache.values():
            d.close()


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
