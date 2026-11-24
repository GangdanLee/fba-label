"""历史打印批次查询、快照补打下载与删除接口。"""

from __future__ import annotations

import base64
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app import db
from app.models.schemas import PrintBatchCreate, PrintBatchRecord

router = APIRouter(prefix="/api/batches", tags=["batches"])


@router.get("", response_model=list[PrintBatchRecord])
async def list_batches_endpoint() -> list[PrintBatchRecord]:
    return db.list_print_batches()


@router.post("", response_model=PrintBatchRecord)
async def create_batch_endpoint(payload: PrintBatchCreate) -> PrintBatchRecord:
    return db.create_print_batch(payload)


@router.get("/{batch_id}/pdf")
async def get_batch_snapshot_pdf(batch_id: str) -> dict[str, str]:
    """读取历史打印批次落盘快照 PDF（用于一键补打或重下）。"""
    rec = db.get_print_batch(batch_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="未找到该打印记录")
    if not rec.snapshot_dir:
        raise HTTPException(status_code=404, detail="该历史记录未保存 PDF 快照")
    snap_path = Path(rec.snapshot_dir)
    if not snap_path.is_file():
        raise HTTPException(status_code=404, detail="批次 PDF 快照文件不存在")
    safe_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in rec.shipment_id)
    return {
        "batch_id": rec.id,
        "filename": f"{safe_id}_{rec.spec_key}.pdf",
        "pdf_b64": base64.b64encode(snap_path.read_bytes()).decode("ascii"),
    }


@router.delete("/{batch_id}")
async def delete_batch_endpoint(batch_id: str) -> dict[str, bool]:
    """删除历史打印记录及其关联的本地快照 PDF。"""
    rec = db.delete_print_batch(batch_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="未找到该打印记录")
    if rec.snapshot_dir:
        snap_path = Path(rec.snapshot_dir)
        if snap_path.is_file():
            snap_path.unlink()
    return {"ok": True}
