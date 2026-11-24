"""打印机探测、双规格校准配置、纸卷防呆状态及 TSPL 干跑校验接口。"""

from __future__ import annotations

import base64
import io
import re
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from reportlab.pdfgen.canvas import Canvas

from app import db
from app.config import get_snapshots_dir, mm_to_pt
from app.engines.code128 import draw_barcode1d_on_reportlab
from app.engines.font_manager import ensure_reportlab_font
from app.engines.pdf_engine import PyMuPDFEngine
from app.models.schemas import CalibrationProfile, PrintBatchCreate, PrinterDevice, SpecStateUpdate
from app.printers.base import get_printer_adapter
from app.printers.network_raw import send_raw_tcp, test_tcp_printer
from app.printers.simulator import render_pdf_page_to_1bit_png_b64
from app.printers.tspl_encoder import DecodedTsplCommand, encode_pdf_pages_to_tspl, parse_and_decode_tspl
from app.printers.zpl_encoder import DecodedZplCommand, encode_pdf_pages_to_zpl, parse_and_decode_zpl

router = APIRouter(prefix="/api/hardware", tags=["hardware"])


def _resolve_profile(profiles: dict[str, CalibrationProfile], spec_key: str) -> CalibrationProfile | None:
    if spec_key in profiles:
        return profiles[spec_key]
    if spec_key.endswith("_double"):
        return profiles.get("50x30_double")
    return profiles.get("100x100_single")


def _format_tspl_command_headers(decoded: list[DecodedTsplCommand]) -> list[str]:
    """将逆向解析出的每页 TSPL2 指令头格式化为可读预览文本。"""
    headers: list[str] = []
    for idx, cmd in enumerate(decoded, start=1):
        size_str = f"SIZE {cmd.size_mm[0]:.1f} mm, {cmd.size_mm[1]:.1f} mm" if cmd.size_mm else "SIZE ?"
        gap_str = f"GAP {cmd.gap_mm[0]:.1f} mm, {cmd.gap_mm[1]:.1f} mm" if cmd.gap_mm else "GAP ?"
        bm_str = (
            f"BITMAP {cmd.bitmap_x},{cmd.bitmap_y},{cmd.width_bytes},{cmd.height_dots},"
            f"{cmd.mode},<{len(cmd.bitmap_payload)} bytes>"
        )
        prt_str = f"PRINT 1,{cmd.copies}"
        headers.append(f"[P{idx}] {size_str}; {gap_str}; {bm_str}; {prt_str}")
    return headers


def _format_zpl_command_headers(decoded: list[DecodedZplCommand]) -> list[str]:
    """将逆向解析出的每页 ZPL II 指令头格式化为可读预览文本。"""
    headers: list[str] = []
    for idx, cmd in enumerate(decoded, start=1):
        pw_str = f"^PW{cmd.pw_dots}" if cmd.pw_dots is not None else "^PW?"
        ll_str = f"^LL{cmd.ll_dots}" if cmd.ll_dots is not None else "^LL?"
        bm_str = f"^GFA,{len(cmd.bitmap_payload)},{len(cmd.bitmap_payload)},{cmd.width_bytes},<{len(cmd.bitmap_payload)} bytes>"
        headers.append(f"[P{idx}] {pw_str}; {ll_str}; ^LS{cmd.ls_dots}; ^LT{cmd.lt_dots}; {bm_str}; ^PQ{cmd.copies}")
    return headers


class NetworkTestRequest(BaseModel):
    host: str
    port: int = Field(default=9100, ge=1, le=65535)


class TsplDryRunRequest(BaseModel):
    pdf_b64: str
    width_mm: float = 100.0
    height_mm: float = 100.0
    gap_mm: float = 2.0
    density: int = 8
    speed: int = 4
    copies_per_page: int = 1
    protocol: Literal["tspl", "zpl"] = "tspl"
    dpi: Literal[203, 300] = 203


class CalibrationCardRequest(BaseModel):
    spec_key: str = "100x100_single"


class ExecutePrintRequest(BaseModel):
    pdf_b64: str
    spec_key: str
    channel: str = "tspl_raw"
    printer_name: str = ""
    dry_run: bool = False
    protocol: Literal["tspl", "zpl"] | None = None
    dpi: Literal[203, 300] | None = None
    connection_type: Literal["os_queue", "network_tcp"] | None = None
    network_host: str = ""
    network_port: int | None = None
    batch: PrintBatchCreate


@router.get("/printers", response_model=list[PrinterDevice])
async def detect_printers() -> list[PrinterDevice]:
    adapter = get_printer_adapter()
    return adapter.list_printers()


@router.post("/test-network")
async def test_network_printer_endpoint(req: NetworkTestRequest) -> dict[str, object]:
    """探测局域网 TCP 9100 网口热敏机连通性（只建连即断，不触发走纸或打印）。"""
    return test_tcp_printer(req.host, req.port)


_SPEC_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{2,48}$")
_BUILTIN_PROFILE_KEYS = {"100x100_single", "50x30_double"}


@router.get("/profiles", response_model=list[CalibrationProfile])
async def get_profiles() -> list[CalibrationProfile]:
    return db.list_calibration_profiles()


@router.post("/profiles", response_model=CalibrationProfile)
async def create_profile(profile: CalibrationProfile) -> CalibrationProfile:
    if not _SPEC_KEY_RE.match(profile.spec_key):
        raise HTTPException(status_code=400, detail="纸卷规格标识仅支持 2~48 位字母、数字、下划线或连字符")
    if profile.label_width_mm < 15.0 or profile.label_height_mm < 15.0:
        raise HTTPException(status_code=400, detail="纸卷标签宽高不能小于 15mm")
    return db.upsert_calibration_profile(profile)


@router.put("/profiles/{spec_key}", response_model=CalibrationProfile)
async def update_profile(spec_key: str, profile: CalibrationProfile) -> CalibrationProfile:
    if profile.spec_key != spec_key:
        raise HTTPException(status_code=400, detail="路径参数与 spec_key 不一致")
    return db.upsert_calibration_profile(profile)


@router.delete("/profiles/{spec_key}")
async def delete_profile(spec_key: str) -> dict[str, bool]:
    if spec_key in _BUILTIN_PROFILE_KEYS:
        raise HTTPException(status_code=400, detail="内置默认规格不可删除")
    if not db.delete_calibration_profile(spec_key):
        raise HTTPException(status_code=404, detail="未找到指定的纸卷校准档案")
    return {"ok": True}


@router.get("/spec-state")
async def get_spec_state() -> dict[str, str]:
    return {"last_printed_spec": db.get_app_state("last_printed_spec", "100x100_single")}


@router.put("/spec-state")
async def put_spec_state(payload: SpecStateUpdate) -> dict[str, str]:
    db.set_app_state("last_printed_spec", payload.last_printed_spec)
    return {"last_printed_spec": payload.last_printed_spec}


def _run_raw_dryrun(req: TsplDryRunRequest) -> dict[str, object]:
    """离线生成 TSPL2 或 ZPL II 裸指令流并立刻逆向解码校验长度、尺寸与位图。"""
    try:
        pdf_bytes = base64.b64decode(req.pdf_b64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="无效的 PDF Base64 载荷") from exc

    if req.protocol == "zpl":
        raw_bytes = encode_pdf_pages_to_zpl(
            pdf_bytes,
            width_mm=req.width_mm,
            height_mm=req.height_mm,
            dpi=req.dpi,
            density=req.density,
            speed=req.speed,
            copies_per_page=req.copies_per_page,
        )
        decoded_zpl = parse_and_decode_zpl(raw_bytes)
        return {
            "ok": True,
            "protocol": "zpl",
            "dpi": req.dpi,
            "total_bytes": len(raw_bytes),
            "commands_count": len(decoded_zpl),
            "command_headers": _format_zpl_command_headers(decoded_zpl),
            "pages": [
                {
                    "pw_dots": cmd.pw_dots,
                    "ll_dots": cmd.ll_dots,
                    "width_bytes": cmd.width_bytes,
                    "height_dots": cmd.height_dots,
                    "bitmap_bytes": len(cmd.bitmap_payload),
                    "copies": cmd.copies,
                }
                for cmd in decoded_zpl
            ],
        }

    tspl_bytes = encode_pdf_pages_to_tspl(
        pdf_bytes,
        width_mm=req.width_mm,
        height_mm=req.height_mm,
        dpi=req.dpi,
        gap_mm=req.gap_mm,
        density=req.density,
        speed=req.speed,
        copies_per_page=req.copies_per_page,
    )
    decoded = parse_and_decode_tspl(tspl_bytes)
    return {
        "ok": True,
        "protocol": "tspl",
        "dpi": req.dpi,
        "total_bytes": len(tspl_bytes),
        "commands_count": len(decoded),
        "command_headers": _format_tspl_command_headers(decoded),
        "pages": [
            {
                "size_mm": cmd.size_mm,
                "gap_mm": cmd.gap_mm,
                "width_bytes": cmd.width_bytes,
                "height_dots": cmd.height_dots,
                "bitmap_bytes": len(cmd.bitmap_payload),
                "copies": cmd.copies,
            }
            for cmd in decoded
        ],
    }


@router.post("/dryrun-tspl")
async def dryrun_tspl(req: TsplDryRunRequest) -> dict[str, object]:
    """向后兼容的 TSPL/ZPL 离线裸指令校验端点。"""
    return _run_raw_dryrun(req)


@router.post("/dryrun-raw")
async def dryrun_raw(req: TsplDryRunRequest) -> dict[str, object]:
    """多协议（TSPL2 / ZPL II）及多精度（203 / 300dpi）离线裸指令校验端点。"""
    return _run_raw_dryrun(req)


@router.post("/calibration-card")
async def generate_calibration_card(req: CalibrationCardRequest) -> dict[str, object]:
    """按纸卷规格、目标 DPI 与协议生成物理毫米校准测试卡 PDF 与点阵仿真预览图。"""
    profiles = {p.spec_key: p for p in db.list_calibration_profiles()}
    prof = profiles.get(req.spec_key)
    if prof is None:
        raise HTTPException(status_code=404, detail=f"未找到规格校准档: {req.spec_key}")

    is_double = prof.cols >= 2
    w_mm = (prof.label_width_mm * 2.0 + prof.col_gap_mm) if is_double else prof.label_width_mm
    h_mm = prof.label_height_mm
    ox, oy = prof.offset_x_mm, prof.offset_y_mm
    dpi = int(prof.dpi)

    buf = io.BytesIO()
    c = Canvas(buf, pagesize=(mm_to_pt(w_mm), mm_to_pt(h_mm)))
    font_b = ensure_reportlab_font(prefer_cjk=False, bold=True)

    if is_double:
        pad_x = 2.0 if prof.label_width_mm <= 42.0 else 3.0
        bc_w = max(18.0, prof.label_width_mm - pad_x * 2.0)
        bc_h = min(15.0, max(9.0, h_mm * 0.5))
        for col_idx in range(2):
            col_x = col_idx * (prof.label_width_mm + prof.col_gap_mm) + ox
            c.setLineWidth(0.8)
            c.setDash(3, 2)
            c.rect(mm_to_pt(col_x + 1.0), mm_to_pt(1.0 - oy), mm_to_pt(prof.label_width_mm - 2.0), mm_to_pt(h_mm - 2.0))
            c.setDash()
            draw_barcode1d_on_reportlab(
                c,
                f"CAL50C{col_idx + 1}",
                x_mm=col_x + pad_x,
                y_top_mm=3.0 + oy,
                w_mm=bc_w,
                h_mm=bc_h,
                page_h_mm=h_mm,
                show_text=True,
                font_size_pt=7.0 if prof.label_width_mm <= 42.0 else 7.5,
                dpi=dpi,
            )
            c.setFont(font_b, 5.5 if prof.label_width_mm <= 42.0 else 6.0)
            c.drawCentredString(
                mm_to_pt(col_x + prof.label_width_mm / 2.0),
                mm_to_pt(3.2 - oy),
                f"CAL {prof.label_width_mm:.0f}x{prof.label_height_mm:.0f} C{col_idx + 1} · {dpi}dpi {prof.protocol.upper()}",
            )
    else:
        c.setLineWidth(1.0)
        c.setDash(4, 3)
        c.rect(mm_to_pt(1.0 + ox), mm_to_pt(1.0 - oy), mm_to_pt(w_mm - 2.0), mm_to_pt(h_mm - 2.0))
        c.setDash()
        # 四边中点内侧短刻度线（适配任意尺寸，不进入条码静区）
        cx_mm = w_mm / 2.0 + ox
        cy_mid_mm = h_mm / 2.0 - oy
        tick_len = min(6.0, w_mm * 0.1, h_mm * 0.1)
        c.line(mm_to_pt(cx_mm), mm_to_pt(1.0 - oy), mm_to_pt(cx_mm), mm_to_pt(1.0 + tick_len - oy))
        c.line(mm_to_pt(cx_mm), mm_to_pt(h_mm - 1.0 - oy), mm_to_pt(cx_mm), mm_to_pt(h_mm - 1.0 - tick_len - oy))
        c.line(mm_to_pt(1.0 + ox), mm_to_pt(cy_mid_mm), mm_to_pt(1.0 + tick_len + ox), mm_to_pt(cy_mid_mm))
        c.line(mm_to_pt(w_mm - 1.0 + ox), mm_to_pt(cy_mid_mm), mm_to_pt(w_mm - 1.0 - tick_len + ox), mm_to_pt(cy_mid_mm))

        title_pt = 9.5 if w_mm >= 85.0 else 7.0
        title_y_pdf = h_mm - min(12.0, max(5.5, h_mm * 0.14)) - oy
        c.setFont(font_b, title_pt)
        c.drawCentredString(
            mm_to_pt(cx_mm),
            mm_to_pt(title_y_pdf),
            f"CALIBRATION {w_mm:.0f}x{h_mm:.0f}mm · {dpi}dpi · {prof.protocol.upper()}",
        )

        bc_w = min(68.0, max(24.0, w_mm - 12.0))
        bc_x = (w_mm - bc_w) / 2.0 + ox
        bc_top_y = min(22.0, max(8.5, h_mm * 0.23)) + oy
        bc_h = min(24.0, max(12.0, h_mm * 0.28))
        draw_barcode1d_on_reportlab(
            c,
            "CAL100DEMO",
            x_mm=bc_x,
            y_top_mm=bc_top_y,
            w_mm=bc_w,
            h_mm=bc_h,
            page_h_mm=h_mm,
            show_text=True,
            font_size_pt=9.0 if w_mm >= 85.0 else 7.5,
            dpi=dpi,
        )

        # 下半区独立校准十字准星及 OFFSET 提示（完全低于条码底边）
        arm = min(12.0, w_mm * 0.14, h_mm * 0.1)
        cross_y_mm = max(arm + 2.0, min(24.0, h_mm * 0.22)) - oy
        c.line(mm_to_pt(cx_mm - arm), mm_to_pt(cross_y_mm), mm_to_pt(cx_mm + arm), mm_to_pt(cross_y_mm))
        c.line(mm_to_pt(cx_mm), mm_to_pt(cross_y_mm - arm), mm_to_pt(cx_mm), mm_to_pt(cross_y_mm + arm))
        offset_y_pdf = (40.0 - oy) if h_mm >= 95.0 else (cross_y_mm + arm + 2.5)
        c.setFont(font_b, 8.0 if w_mm >= 85.0 else 6.5)
        c.drawCentredString(mm_to_pt(cx_mm), mm_to_pt(offset_y_pdf), f"OFFSET X: {ox:+.1f}mm / Y: {oy:+.1f}mm")

    c.showPage()
    c.save()
    pdf_bytes = buf.getvalue()
    return {
        "spec_key": prof.spec_key,
        "dpi": dpi,
        "protocol": prof.protocol,
        "pdf_b64": base64.b64encode(pdf_bytes).decode("ascii"),
        "preview_203dpi_b64": render_pdf_page_to_1bit_png_b64(pdf_bytes, page_index=0, dpi=dpi),
    }


@router.post("/execute-print")
async def execute_print(req: ExecutePrintRequest) -> dict[str, object]:
    """统一执行打印/干跑校验：按规格档案或请求参数自动路由 TSPL2 / ZPL II / OS 驱动 / 网口 TCP 9100。"""
    try:
        pdf_bytes = base64.b64decode(req.pdf_b64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="无效的 PDF Base64 载荷") from exc

    profiles = {p.spec_key: p for p in db.list_calibration_profiles()}
    exact_prof = profiles.get(req.spec_key)
    prof = _resolve_profile(profiles, req.spec_key)
    eng = PyMuPDFEngine()
    dims_pt = eng.get_page_dimensions_pt(pdf_bytes)
    if not dims_pt:
        raise HTTPException(status_code=400, detail="PDF 不包含有效页面")

    width_mm = (
        exact_prof.label_width_mm * (2.0 if exact_prof.cols >= 2 else 1.0)
        + (exact_prof.col_gap_mm if exact_prof.cols >= 2 else 0.0)
        if exact_prof
        else (dims_pt[0][0] * 25.4 / 72.0)
    )
    height_mm = exact_prof.label_height_mm if exact_prof else (dims_pt[0][1] * 25.4 / 72.0)
    gap_mm = prof.row_gap_mm if prof else 2.0
    density = prof.darkness if prof else 8
    speed = prof.print_speed if prof else 4

    effective_protocol = req.protocol or (prof.protocol if prof else "tspl")
    effective_dpi = int(req.dpi or (prof.dpi if prof else 203))
    effective_conn = req.connection_type or (prof.connection_type if prof else "os_queue")
    effective_host = (req.network_host or (prof.network_host if prof else "")).strip()
    effective_port = int(req.network_port or (prof.network_port if prof else 9100))
    effective_printer = (req.printer_name or (prof.printer_name if prof else "")).strip()

    is_dry_run = (
        req.dry_run
        or (effective_conn == "os_queue" and not effective_printer)
        or (effective_conn == "network_tcp" and not effective_host)
    )
    raw_bytes_len = 0
    raw_commands = 0
    command_headers: list[str] = []
    printer_result: dict[str, object] = (
        {"ok": True, "mode": "pdf_export", "offline_dryrun": False}
        if req.channel == "pdf_export"
        else {"ok": True, "mode": req.channel, "offline_dryrun": True}
    )

    if req.channel == "tspl_raw" or (req.channel != "pdf_export" and is_dry_run):
        ox = prof.offset_x_mm if prof else 0.0
        oy = prof.offset_y_mm if prof else 0.0
        if effective_protocol == "zpl":
            raw_bytes = encode_pdf_pages_to_zpl(
                pdf_bytes,
                width_mm=width_mm,
                height_mm=height_mm,
                dpi=effective_dpi,
                density=density,
                speed=speed,
                offset_x_mm=ox,
                offset_y_mm=oy,
            )
            decoded_zpl = parse_and_decode_zpl(raw_bytes)
            raw_bytes_len = len(raw_bytes)
            raw_commands = len(decoded_zpl)
            command_headers = _format_zpl_command_headers(decoded_zpl)
        else:
            raw_bytes = encode_pdf_pages_to_tspl(
                pdf_bytes,
                width_mm=width_mm,
                height_mm=height_mm,
                dpi=effective_dpi,
                gap_mm=gap_mm,
                density=density,
                speed=speed,
                offset_x_mm=ox,
                offset_y_mm=oy,
                direction=(prof.tspl_direction if prof else 1),
                invert_bitmap=(bool(prof.invert_bitmap) if prof else False),
            )
            decoded_tspl = parse_and_decode_tspl(raw_bytes)
            raw_bytes_len = len(raw_bytes)
            raw_commands = len(decoded_tspl)
            command_headers = _format_tspl_command_headers(decoded_tspl)

        if req.channel == "tspl_raw" and not is_dry_run:
            if effective_conn == "network_tcp":
                printer_result = send_raw_tcp(effective_host, effective_port, raw_bytes)
            else:
                adapter = get_printer_adapter()
                printer_result = (
                    adapter.send_raw_tspl(effective_printer, raw_bytes)
                    if effective_protocol == "tspl"
                    else adapter.send_raw(effective_printer, raw_bytes, protocol=effective_protocol)
                )
    elif req.channel == "os_driver":
        if effective_conn == "network_tcp":
            raise HTTPException(status_code=400, detail="局域网 TCP 9100 直连请使用「裸指令直出（TSPL / ZPL）」通道")
        printer_result = get_printer_adapter().print_pdf(effective_printer, pdf_bytes, title=req.batch.shipment_id)

    record = db.create_print_batch(req.batch)
    snap_path = get_snapshots_dir() / f"{record.id}.pdf"
    snap_path.write_bytes(pdf_bytes)
    db.update_print_batch_snapshot(record.id, str(snap_path))
    record = db.get_print_batch(record.id) or record
    db.set_app_state("last_printed_spec", req.spec_key)

    return {
        "ok": True,
        "protocol": effective_protocol,
        "dpi": effective_dpi,
        "connection_type": effective_conn,
        "tspl_bytes_len": raw_bytes_len,
        "tspl_commands": raw_commands,
        "command_headers": command_headers,
        "printer_result": printer_result,
        "batch": record.model_dump(),
        "last_printed_spec": req.spec_key,
    }
