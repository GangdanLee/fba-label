"""本机 SQLite 配置与打印快照一键 ZIP 备份及安全导入恢复接口。"""

from __future__ import annotations

import base64
import io
import json
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app import db
from app.config import get_data_dir, get_db_path, get_snapshots_dir

router = APIRouter(prefix="/api/system/backup", tags=["backup"])

MAX_BACKUP_ZIP_BYTES = 200 * 1024 * 1024  # 200 MB
MAX_UNCOMPRESSED_ENTRY_BYTES = 80 * 1024 * 1024


class BackupExportRequest(BaseModel):
    include_snapshots: bool = False


def _is_safe_zip_member(name: str) -> bool:
    if not name or name.startswith("/") or name.startswith("\\"):
        return False
    if len(name) >= 2 and name[1] == ":":
        return False
    norm = name.replace("\\", "/")
    parts = PurePosixPath(norm).parts
    return ".." not in parts


@router.get("/summary")
async def get_backup_summary_endpoint() -> dict[str, object]:
    """返回本地数据规模统计（不含任何绝对磁盘路径）。"""
    return db.get_backup_summary()


@router.post("/export")
async def export_backup_endpoint(req: BackupExportRequest) -> dict[str, object]:
    """导出包含 SKU 模板、货代规则、纸卷校准、偏好设置（及可选批次快照）的内存 ZIP 包。"""
    payload = db.export_backup_payload(include_batches=req.include_snapshots)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    snap_dir = get_snapshots_dir()
    included_snapshots: list[str] = []

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        if req.include_snapshots:
            for batch in payload.get("print_batches", []):
                if not isinstance(batch, dict):
                    continue
                fname = Path(str(batch.get("snapshot_filename") or "")).name
                if not fname:
                    continue
                fpath = snap_dir / fname
                if fpath.is_file() and fname not in included_snapshots:
                    zf.write(fpath, arcname=f"snapshots/{fname}")
                    included_snapshots.append(fname)

        config_json = json.dumps(payload, ensure_ascii=False, indent=2)
        manifest = {
            "app": "FBA Label Studio",
            "format_version": "1.0",
            "exported_at": now_iso,
            "include_snapshots": req.include_snapshots,
            "counts": {
                "skus": len(payload.get("skus", [])),
                "profiles": len(payload.get("calibration_profiles", [])),
                "rules": len(payload.get("carrier_rules", [])),
                "batches": len(payload.get("print_batches", [])),
                "snapshots": len(included_snapshots),
            },
        }
        zf.writestr("config_data.json", config_json.encode("utf-8"))
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))

    zip_bytes = buf.getvalue()
    tag = "full" if req.include_snapshots else "config"
    return {
        "filename": f"FBA-Label-Studio-backup-{tag}-{stamp}.zip",
        "size_bytes": len(zip_bytes),
        "counts": manifest["counts"],
        "zip_b64": base64.b64encode(zip_bytes).decode("ascii"),
    }


def _create_pre_import_db_backup() -> str:
    """导入前自动创建当前数据库文件回滚副本，滚动保留最近 5 份。"""
    db_path = get_db_path()
    backup_dir = get_data_dir() / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_name = f"pre_import_{stamp}.db"
    if db_path.is_file():
        shutil.copy2(db_path, backup_dir / backup_name)

    existing = sorted(backup_dir.glob("pre_import_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in existing[5:]:
        try:
            os.remove(stale)
        except OSError:
            pass
    return backup_name


@router.post("/import")
async def import_backup_endpoint(
    file: UploadFile = File(...),
    mode: Literal["merge", "replace"] = Form("merge"),
) -> dict[str, object]:
    """导入配置备份 ZIP 包，校验安全性并在写入前自动留存回滚副本。"""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="上传的备份文件为空")
    if len(raw) > MAX_BACKUP_ZIP_BYTES:
        raise HTTPException(status_code=400, detail="备份文件超过 200MB 安全上限")

    try:
        zf = zipfile.ZipFile(io.BytesIO(raw), "r")
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="备份文件不是有效的 ZIP 压缩包") from exc

    with zf:
        infos = zf.infolist()
        for info in infos:
            if not _is_safe_zip_member(info.filename):
                raise HTTPException(status_code=400, detail=f"检测到非法压缩包路径，已拒绝导入: {info.filename}")
            if info.file_size > MAX_UNCOMPRESSED_ENTRY_BYTES:
                raise HTTPException(status_code=400, detail=f"压缩包单文件过大: {info.filename}")

        names = {info.filename: info for info in infos if not info.is_dir()}
        if "config_data.json" not in names:
            raise HTTPException(status_code=400, detail="备份包缺少核心配置文件 config_data.json")

        try:
            payload = json.loads(zf.read("config_data.json").decode("utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"config_data.json 解析失败: {exc}") from exc

        if not isinstance(payload, dict) or "skus" not in payload:
            raise HTTPException(status_code=400, detail="config_data.json 结构不合法")

        pre_backup_name = _create_pre_import_db_backup()

        snap_dir = get_snapshots_dir()
        written_snaps: set[str] = set()
        for fname, info in names.items():
            norm = fname.replace("\\", "/")
            if norm.startswith("snapshots/") and norm.lower().endswith(".pdf"):
                base_name = Path(norm).name
                if base_name:
                    (snap_dir / base_name).write_bytes(zf.read(info))
                    written_snaps.add(base_name)

    try:
        restored = db.restore_backup_payload(
            payload=payload,
            mode=mode,
            snapshot_dest_dir=snap_dir,
            written_snapshots=written_snaps,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"恢复本地数据失败（已保留回滚备份 {pre_backup_name}）: {exc}") from exc

    return {
        "ok": True,
        "mode": mode,
        "restored": restored,
        "snapshots_restored": len(written_snaps),
        "pre_import_backup_name": pre_backup_name,
    }
