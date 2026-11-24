"""货代箱唛解析、多规则字段提取与 98×98mm 安全裁切居中引擎。"""

from __future__ import annotations

import re

import pymupdf

from app.config import PAGE_BOX_MM, SAFE_BOX_MM
from app.engines.amazon_fc_codes import NOISE_FC_CODES, extract_amazon_fc_code
from app.engines.pdf_engine import PyMuPDFEngine, merge_single_page_pdfs, render_pdf_page_png_data_url
from app.models.schemas import CarrierBoxMeta, CarrierRule

DEFAULT_SHIPMENT_RE = re.compile(r"\b(FBA[A-Z0-9]{6,12})\b", re.IGNORECASE)
DEFAULT_WH_RE = re.compile(r"\b([A-Z]{3}\d)\b")
DEFAULT_CTN_PATTERNS = (
    re.compile(r"CTNS?[:：\s]*(\d+)\s*(?:/|of)\s*(\d+)", re.IGNORECASE),
    re.compile(r"Box\s*(\d+)\s*(?:/|of)\s*(\d+)", re.IGNORECASE),
    re.compile(r"(\d+)\s*/\s*(\d+)\s*[箱件]"),
)


def _order_enabled_rules(extra_rules: list[CarrierRule] | None) -> list[CarrierRule]:
    if not extra_rules:
        return []
    enabled = [r for r in extra_rules if r.enabled]
    custom = [r for r in enabled if r.id != "rule_default"]
    builtin = [r for r in enabled if r.id == "rule_default"]
    return custom + builtin


def _compile_safe(pattern: str, flags: int = 0) -> re.Pattern[str] | None:
    raw = (pattern or "").strip()
    if not raw:
        return None
    try:
        return re.compile(raw, flags)
    except re.error:
        return None


def _match_shipment_id(text: str, file_name: str, extra_rules: list[CarrierRule] | None = None) -> str | None:
    patterns: list[re.Pattern[str]] = []
    for rule in _order_enabled_rules(extra_rules):
        if rule.id == "rule_default":
            continue
        compiled = _compile_safe(rule.shipment_regex, re.IGNORECASE)
        if compiled is not None:
            patterns.append(compiled)
    patterns.append(DEFAULT_SHIPMENT_RE)
    for rule in _order_enabled_rules(extra_rules):
        if rule.id == "rule_default":
            compiled = _compile_safe(rule.shipment_regex, re.IGNORECASE)
            if compiled is not None:
                patterns.append(compiled)

    for source in (text, file_name):
        for pat in patterns:
            for m in pat.findall(source or ""):
                cand = (m[0] if isinstance(m, tuple) else m).strip().upper()
                if not cand:
                    continue
                # 若匹配到带 U+箱流水号后缀（如 FBA00AUD01U000001），剥离末尾箱后缀得到完整货件号
                if not re.search(r"U\d{3,8}$", cand):
                    return cand
                stripped = re.sub(r"U\d{3,8}$", "", cand)
                if stripped.startswith("FBA") and len(stripped) >= 8:
                    return stripped
                return cand
    return None


def _match_warehouse(text: str, file_name: str, extra_rules: list[CarrierRule] | None = None) -> str | None:
    for rule in _order_enabled_rules(extra_rules):
        if rule.id == "rule_default":
            continue
        compiled = _compile_safe(rule.warehouse_regex, re.IGNORECASE)
        if compiled is None:
            continue
        for source in ((text or "").upper(), (file_name or "").upper()):
            for m in compiled.findall(source):
                cand = (m[0] if isinstance(m, tuple) else m).strip().upper()
                if cand and not cand.startswith("FBA"):
                    return cand

    # 优先使用内置亚马逊 FBA 仓点词典并过滤 BOX1/CTN1 等干扰词
    fc = extract_amazon_fc_code(text, file_name)
    if fc:
        return fc

    for rule in _order_enabled_rules(extra_rules):
        if rule.id != "rule_default":
            continue
        compiled = _compile_safe(rule.warehouse_regex, re.IGNORECASE)
        if compiled is None:
            continue
        for source in ((text or "").upper(), (file_name or "").upper()):
            for m in compiled.findall(source):
                cand = (m[0] if isinstance(m, tuple) else m).strip().upper()
                if cand and not cand.startswith("FBA") and cand not in NOISE_FC_CODES:
                    return cand
    return None


def _match_ctn(text: str, fallback_idx: int, fallback_total: int, extra_rules: list[CarrierRule] | None = None) -> tuple[int, int]:
    patterns: list[re.Pattern[str]] = []
    for rule in _order_enabled_rules(extra_rules):
        if rule.id == "rule_default":
            continue
        compiled = _compile_safe(rule.ctn_regex, re.IGNORECASE)
        if compiled is not None:
            patterns.append(compiled)
    patterns.extend(DEFAULT_CTN_PATTERNS)
    for rule in _order_enabled_rules(extra_rules):
        if rule.id == "rule_default":
            compiled = _compile_safe(rule.ctn_regex, re.IGNORECASE)
            if compiled is not None:
                patterns.append(compiled)

    for pat in patterns:
        m = pat.search(text or "")
        if m:
            try:
                return int(m.group(1)), int(m.group(2))
            except (IndexError, ValueError):
                continue
    return fallback_idx, fallback_total


def preview_carrier_rules_on_text(
    text: str,
    file_name: str = "",
    rules: list[CarrierRule] | None = None,
) -> dict[str, object]:
    """针对样本文本与文件名运行当前货代箱唛解析规则，便于界面实时调试。"""
    ship_id = _match_shipment_id(text, file_name, rules)
    wh = _match_warehouse(text, file_name, rules)
    box_idx, box_tot = _match_ctn(text, fallback_idx=1, fallback_total=1, extra_rules=rules)
    return {
        "shipment_id": ship_id,
        "warehouse_code": wh,
        "box_index": box_idx,
        "total_boxes": box_tot,
    }


def process_carrier_pdf(
    pdf_bytes: bytes,
    file_id: str,
    file_name: str,
    rules: list[CarrierRule] | None = None,
    safe_width_mm: float = SAFE_BOX_MM,
    safe_height_mm: float = SAFE_BOX_MM,
    offset_x_mm: float = 0.0,
    offset_y_mm: float = 0.0,
    engine: PyMuPDFEngine | None = None,
) -> tuple[list[CarrierBoxMeta], bytes]:
    """逐页提取货代箱唛元信息（无编号保留 None 供人工归属），并居中落版为 100×100mm 单页矢量 PDF。"""
    eng = engine or PyMuPDFEngine()
    items: list[CarrierBoxMeta] = []
    pages_out: list[bytes] = []

    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as src_doc:
        total_pages = len(src_doc)
        for idx in range(total_pages):
            text = src_doc[idx].get_text("text")
            ship_id = _match_shipment_id(text, file_name, rules)
            wh = _match_warehouse(text, file_name, rules)
            box_idx, box_tot = _match_ctn(text, fallback_idx=idx + 1, fallback_total=total_pages, extra_rules=rules)

            centered = eng.crop_and_center_vector_pdf(
                pdf_bytes,
                page_index=idx,
                target_page_mm=PAGE_BOX_MM,
                safe_width_mm=safe_width_mm,
                safe_height_mm=safe_height_mm,
                offset_x_mm=offset_x_mm,
                offset_y_mm=offset_y_mm,
            )
            pages_out.append(centered)
            items.append(
                CarrierBoxMeta(
                    file_id=file_id,
                    file_name=file_name,
                    page_index=idx,
                    shipment_id=ship_id,
                    assigned_shipment_id=None,
                    box_index=box_idx,
                    total_boxes=box_tot,
                    warehouse_code=wh,
                    preview_b64=render_pdf_page_png_data_url(centered, page_index=0, dpi=150),
                )
            )

    return items, merge_single_page_pdfs(pages_out)
