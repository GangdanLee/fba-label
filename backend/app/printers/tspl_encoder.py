"""TSPL2 裸指令编码器与离线逆向解析/位图校验器（严格 203dpi 1-bit 黑白二值）。"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from PIL import Image

from app.config import DOTS_PER_MM, dots_per_mm_for_dpi, mm_to_dots
from app.engines.pdf_engine import PyMuPDFEngine


@dataclass
class DecodedTsplCommand:
    """从 TSPL 字节流逆向解析出的指令头与位图载荷。"""

    size_mm: tuple[float, float] | None
    gap_mm: tuple[float, float] | None
    direction: int | None
    density: int | None
    speed: int | None
    bitmap_x: int
    bitmap_y: int
    width_bytes: int
    height_dots: int
    mode: int
    bitmap_payload: bytes
    copies: int
    image: Image.Image


def pil_1bit_to_tspl_bytes(img: Image.Image) -> tuple[bytes, int, int]:
    """将图像规范化为纯 1-bit 位图并输出 TSPL BITMAP 行字节流（0=黑点打印，1=白点留空）。"""
    bw = img.convert("1", dither=Image.Dither.NONE)
    w, h = bw.size
    w_bytes = math.ceil(w / 8)

    # 若宽度非 8 的倍数，补齐右侧白边像素 (255 -> bit 1)
    if w % 8 != 0:
        padded = Image.new("1", (w_bytes * 8, h), color=255)
        padded.paste(bw, (0, 0))
        bw = padded

    raw = bw.tobytes()
    expected_len = w_bytes * h
    assert len(raw) == expected_len, f"TSPL bitmap size mismatch: {len(raw)} != {expected_len}"
    return raw, w_bytes, h


def _normalize_canvas_size(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """对齐目标点阵：1~2px 舍入误差通过贴白底裁切消除，避免抽列破坏 1-dot 条码。"""
    if img.size == (target_w, target_h):
        return img
    if abs(img.width - target_w) <= 3 and abs(img.height - target_h) <= 3:
        canvas = Image.new("1", (target_w, target_h), color=255)
        canvas.paste(img.convert("1", dither=Image.Dither.NONE), (0, 0))
        return canvas
    resized = img.convert("L").resize((target_w, target_h), Image.Resampling.NEAREST)
    return resized.point(lambda p: 0 if p < 160 else 255, mode="1")


def encode_image_to_tspl(
    img: Image.Image,
    width_mm: float,
    height_mm: float,
    dpi: int = 203,
    gap_mm: float = 2.0,
    density: int = 8,
    speed: int = 4,
    direction: int = 1,
    copies: int = 1,
    offset_x_mm: float = 0.0,
    offset_y_mm: float = 0.0,
) -> bytes:
    """将单张标签图像编码为完整的 TSC/TSPL2 兼容裸指令字节流（支持 203/300dpi）。"""
    dpm = dots_per_mm_for_dpi(dpi)
    target_w_dots = max(8, mm_to_dots(width_mm, dots_per_mm=dpm))
    target_h_dots = max(8, mm_to_dots(height_mm, dots_per_mm=dpm))
    img = _normalize_canvas_size(img, target_w_dots, target_h_dots)

    bitmap_bytes, w_bytes, h_dots = pil_1bit_to_tspl_bytes(img)
    x_dots = mm_to_dots(offset_x_mm, dots_per_mm=dpm)
    y_dots = mm_to_dots(offset_y_mm, dots_per_mm=dpm)

    header = (
        f"SIZE {width_mm:.1f} mm, {height_mm:.1f} mm\r\n"
        f"GAP {gap_mm:.1f} mm, 0 mm\r\n"
        f"DIRECTION {int(direction)}\r\n"
        f"SPEED {int(speed)}\r\n"
        f"DENSITY {int(density)}\r\n"
        f"CLS\r\n"
        f"BITMAP {x_dots},{y_dots},{w_bytes},{h_dots},0,"
    ).encode("ascii")

    footer = f"\r\nPRINT 1,{max(1, int(copies))}\r\n".encode("ascii")
    return header + bitmap_bytes + footer


def encode_pdf_pages_to_tspl(
    pdf_bytes: bytes,
    width_mm: float,
    height_mm: float,
    dpi: int = 203,
    gap_mm: float = 2.0,
    density: int = 8,
    speed: int = 4,
    copies_per_page: int = 1,
    offset_x_mm: float = 0.0,
    offset_y_mm: float = 0.0,
) -> bytes:
    """将多页矢量 PDF 按指定 DPI 逐页光栅化为 1-bit 位图并串联封装为 TSPL2 字节流。"""
    eng = PyMuPDFEngine()
    count = eng.get_page_count(pdf_bytes)
    chunks: list[bytes] = []
    for idx in range(count):
        img_1bit = eng.render_page_to_1bit(pdf_bytes, idx, dpi=dpi, threshold=160)
        chunks.append(
            encode_image_to_tspl(
                img_1bit,
                width_mm=width_mm,
                height_mm=height_mm,
                dpi=dpi,
                gap_mm=gap_mm,
                density=density,
                speed=speed,
                copies=copies_per_page,
                offset_x_mm=offset_x_mm,
                offset_y_mm=offset_y_mm,
            )
        )
    return b"".join(chunks)


def parse_and_decode_tspl(raw_bytes: bytes) -> list[DecodedTsplCommand]:
    """逆向解析 TSPL 原始字节流、校验 BITMAP 载荷字节长度并还原为 1-bit Pillow Image。"""
    results: list[DecodedTsplCommand] = []
    pos = 0
    total_len = len(raw_bytes)

    while pos < total_len:
        bm_idx = raw_bytes.find(b"BITMAP ", pos)
        if bm_idx == -1:
            break

        # 查找 BITMAP 参数行末尾的最后一个逗号
        # 格式: BITMAP x,y,w_bytes,height,mode,<binary...>
        line_prefix_end = bm_idx
        comma_count = 0
        cursor = bm_idx
        while cursor < total_len and comma_count < 5:
            if raw_bytes[cursor : cursor + 1] == b",":
                comma_count += 1
            cursor += 1
        if comma_count < 5:
            raise ValueError("TSPL BITMAP 指令头参数不完整")

        header_text = raw_bytes[pos:bm_idx].decode("ascii", errors="replace")
        bm_cmd_text = raw_bytes[bm_idx : cursor - 1].decode("ascii")

        m_bm = re.match(r"BITMAP\s+(-?\d+),(-?\d+),(\d+),(\d+),(\d+)", bm_cmd_text)
        if not m_bm:
            raise ValueError(f"无法解析 BITMAP 指令参数: {bm_cmd_text}")

        bx, by, w_bytes, h_dots, mode = (int(m_bm.group(i)) for i in range(1, 6))
        expected_payload_len = w_bytes * h_dots
        payload_start = cursor
        payload_end = payload_start + expected_payload_len
        if payload_end > total_len:
            raise ValueError(
                f"TSPL BITMAP 载荷长度不足: 期望 {expected_payload_len} 字节, 实际仅剩 {total_len - payload_start} 字节"
            )

        payload = raw_bytes[payload_start:payload_end]
        tail_chunk_end = raw_bytes.find(b"\n", payload_end)
        next_print_end = raw_bytes.find(b"PRINT ", payload_end)
        if next_print_end != -1:
            eol = raw_bytes.find(b"\n", next_print_end)
            tail_end = (eol + 1) if eol != -1 else total_len
        elif tail_chunk_end != -1:
            tail_end = tail_chunk_end + 1
        else:
            tail_end = total_len

        tail_text = raw_bytes[payload_end:tail_end].decode("ascii", errors="replace")

        size_m = re.search(r"SIZE\s+([0-9.]+)\s*mm,\s*([0-9.]+)\s*mm", header_text)
        gap_m = re.search(r"GAP\s+([0-9.]+)\s*mm,\s*([0-9.]+)\s*mm", header_text)
        dir_m = re.search(r"DIRECTION\s+(\d+)", header_text)
        den_m = re.search(r"DENSITY\s+(\d+)", header_text)
        spd_m = re.search(r"SPEED\s+(\d+)", header_text)
        prt_m = re.search(r"PRINT\s+\d+,(\d+)", tail_text)

        img = Image.frombytes("1", (w_bytes * 8, h_dots), payload)
        results.append(
            DecodedTsplCommand(
                size_mm=(float(size_m.group(1)), float(size_m.group(2))) if size_m else None,
                gap_mm=(float(gap_m.group(1)), float(gap_m.group(2))) if gap_m else None,
                direction=int(dir_m.group(1)) if dir_m else None,
                density=int(den_m.group(1)) if den_m else None,
                speed=int(spd_m.group(1)) if spd_m else None,
                bitmap_x=bx,
                bitmap_y=by,
                width_bytes=w_bytes,
                height_dots=h_dots,
                mode=mode,
                bitmap_payload=payload,
                copies=int(prt_m.group(1)) if prt_m else 1,
                image=img,
            )
        )
        pos = tail_end

    return results
