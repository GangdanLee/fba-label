"""FastAPI 主入口：挂载核心业务路由与静态前端托管。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import db
from app.api import batches, box_labels, fnsku, hardware, system_backup
from app.config import get_frontend_dist_dir


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    yield


app = FastAPI(
    title="FBA Label Studio API",
    version="0.6.0",
    lifespan=lifespan,
)

app.include_router(fnsku.router)
app.include_router(box_labels.router)
app.include_router(batches.router)
app.include_router(hardware.router)
app.include_router(system_backup.router)


@app.get("/api/health")
async def health_check() -> JSONResponse:
    return JSONResponse({"ok": True, "service": "fba-label-studio", "version": "0.6.0"})


_frontend_dir = get_frontend_dist_dir()
if _frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
