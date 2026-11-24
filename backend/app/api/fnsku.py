"""产品标签解析、条码可读性检查、单/双排矢量 PDF 渲染与模板管理接口。"""

from __future__ import annotations

import base64
import io

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile

from app import db
from app.engines.code128 import evaluate_barcode_readability, generate_qrcode_pil
from app.engines.fnsku_engine import (
    parse_amazon_product_pdf,
    parse_sku_csv_bytes,
    render_fnsku_batch_pdf,
    render_fnsku_elements_pdf,
)
from app.engines.pdf_engine import PyMuPDFEngine
from app.models.schemas import (
    BarcodeReadabilityReport,
    FnskuBatchRenderRequest,
    FnskuRenderRequest,
    SkuTemplate,
    SkuTemplateUpsert,
)
from app.printers.simulator import render_pdf_page_to_1bit_png_b64

router = APIRouter(prefix="/api/fnsku", tags=["fnsku"])


@router.post("/parse-pdf")
async def parse_fnsku_pdf_endpoint(file: UploadFile = File(...)) -> dict[str, str]:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")
    try:
        return parse_amazon_product_pdf(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"产品标签 PDF 解析失败: {exc}") from exc


@router.get("/readability", response_model=BarcodeReadabilityReport)
async def check_barcode_readability(
    code: str = Query(..., min_length=1, max_length=64),
    width_mm: float = Query(44.0, gt=5.0, le=120.0),
    dpi: int = Query(203, ge=150, le=600),
) -> BarcodeReadabilityReport:
    return evaluate_barcode_readability(code, width_mm=width_mm, dpi=dpi)


@router.post("/render-preview")
async def render_fnsku_preview(req: FnskuRenderRequest) -> dict[str, object]:
    pdf_bytes = render_fnsku_elements_pdf(req)
    eng = PyMuPDFEngine()
    page_count = eng.get_page_count(pdf_bytes)
    preview_b64 = render_pdf_page_to_1bit_png_b64(pdf_bytes, page_index=0, dpi=req.dpi)
    return {
        "page_count": page_count,
        "dpi": req.dpi,
        "pdf_b64": base64.b64encode(pdf_bytes).decode("ascii"),
        "preview_203dpi_b64": preview_b64,
    }


@router.get("/qrcode-preview")
async def qrcode_preview(code: str = Query("DEMO", min_length=1, max_length=256)) -> Response:
    """实时生成带静区的 QR 码 PNG，供设计器画布所见即所得渲染。"""
    img = generate_qrcode_pil(code, scale=4)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@router.get("/templates", response_model=list[SkuTemplate])
async def get_templates() -> list[SkuTemplate]:
    return db.list_sku_templates()


@router.post("/templates", response_model=SkuTemplate)
async def save_template(payload: SkuTemplateUpsert) -> SkuTemplate:
    return db.upsert_sku_template(payload)


@router.delete("/templates/{sku_id}")
async def remove_template(sku_id: str) -> dict[str, bool]:
    deleted = db.delete_sku_template(sku_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="模板不存在")
    return {"ok": True}


@router.get("/csv-template")
async def download_csv_template() -> Response:
    """下载标准 UTF-8-BOM CSV 批量 SKU 导入模板（兼容 Excel 直接打开不乱码）。"""
    csv_body = (
        "\ufeff"
        "sku,fnsku,title,qty\n"
        "DEMO-MAT-BLK,X000BAT001,新品：防滑硅胶厨房台面垫 黑色大号,10\n"
        "DEMO-MAT-GRY,X000BAT002,防滑硅胶厨房台面垫 灰色中号 (New),6\n"
    )
    return Response(
        content=csv_body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="fnsku_batch_template.csv"'},
    )


@router.post("/parse-csv")
async def parse_csv_endpoint(file: UploadFile = File(...)) -> dict[str, object]:
    """解析上传的 CSV/TSV SKU 清单并校验数量及清洗标题成色。"""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")
    try:
        return parse_sku_csv_bytes(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"CSV 清单解析失败: {exc}") from exc


@router.post("/render-batch")
async def render_batch_endpoint(req: FnskuBatchRenderRequest) -> dict[str, object]:
    """根据当前画布模板与多款 SKU 清单批量排版渲染高精矢量 PDF。"""
    pdf_bytes, total_pages, total_labels = render_fnsku_batch_pdf(req)
    return {
        "page_count": total_pages,
        "total_labels": total_labels,
        "total_skus": len(req.items),
        "dpi": req.dpi,
        "pdf_b64": base64.b64encode(pdf_bytes).decode("ascii"),
        "preview_203dpi_b64": render_pdf_page_to_1bit_png_b64(pdf_bytes, page_index=0, dpi=req.dpi),
    }
