"""ZPL II 裸指令编码器与离线逆向解码器（支持 203/300dpi 1-bit 黑白二值 ^GFA 位图）。"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from PIL import Image

from app.config import dots_per_mm_for_dpi, mm_to_dots
from app.engines.pdf_engine import PyMuPDFEngine


@dataclass
class DecodedZplCommand:
    """从 ZPL II 字节流逆向解析出的指令头与位图图像。"""

    pw_dots: int | None
    ll_dots: int | None
    ls_dots: int
    lt_dots: int
    density: int | None
    speed: int | None
    width_bytes: int
    height_dots: int
    copies: int
    bitmap_payload: bytes
    image: Image.Image


def pil_1bit_to_zpl_hex(img: Image.Image) -> tuple[str, int, int, int]:
    """将 Pillow 图像转为 ZPL ^GFA 所需的 ASCII Hex 位图载荷（1=黑点打印，0=白底留空）。"""
    bw = img.convert("1", dither=Image.Dither.NONE)
    w, h = bw.size
    w_bytes = math.ceil(w / 8)

    if w % 8 != 0:
        padded = Image.new("1", (w_bytes * 8, h), color=255)
        padded.paste(bw, (0, 0))
        bw = padded

    # Pillow '1' 模式 0 为黑、1 为白，而 ZPL ^GFA 1 为黑、0 为白，逐字节异或翻转
    inv_bytes = bytes(b ^ 0xFF for b in bw.tobytes())
    expected_len = w_bytes * h
    assert len(inv_bytes) == expected_len, f"ZPL bitmap size mismatch: {len(inv_bytes)} != {expected_len}"
    return inv_bytes.hex().upper(), expected_len, w_bytes, h


def _normalize_canvas_size(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """对齐目标画布点数：1~2px 舍入误差通过贴白底裁切消除，避免抽列破坏 1-dot 窄条码。"""
    if img.size == (target_w, target_h):
        return img
    dw = abs(img.width - target_w)
    dh = abs(img.height - target_h)
    if dw <= 3 and dh <= 3:
        canvas = Image.new("1", (target_w, target_h), color=255)
        canvas.paste(img.convert("1", dither=Image.Dither.NONE), (0, 0))
        return canvas
    resized = img.convert("L").resize((target_w, target_h), Image.Resampling.NEAREST)
    return resized.point(lambda p: 0 if p < 160 else 255, mode="1")


def encode_image_to_zpl(
    img: Image.Image,
    width_mm: float,
    height_mm: float,
    dpi: int = 203,
    density: int = 8,
    speed: int = 4,
    copies: int = 1,
    offset_x_mm: float = 0.0,
    offset_y_mm: float = 0.0,
) -> bytes:
    """将单页标签位图封装为 Zebra 兼容 ZPL II 指令块。"""
    dpm = dots_per_mm_for_dpi(dpi)
    pw = max(8, mm_to_dots(width_mm, dots_per_mm=dpm))
    ll = max(8, mm_to_dots(height_mm, dots_per_mm=dpm))
    img = _normalize_canvas_size(img, pw, ll)

    hex_str, total_bytes, w_bytes, _h_dots = pil_1bit_to_zpl_hex(img)
    x_dots = mm_to_dots(offset_x_mm, dots_per_mm=dpm)
    y_dots = mm_to_dots(offset_y_mm, dots_per_mm=dpm)
    sd = min(30, max(0, int(density) * 2))
    spd = min(12, max(2, int(speed)))
    qty = max(1, int(copies))

    cmd = (
        f"^XA\r\n"
        f"^CI28\r\n"
        f"^PW{pw}\r\n"
        f"^LL{ll}\r\n"
        f"^LH0,0\r\n"
        f"^LS{x_dots}\r\n"
        f"^LT{y_dots}\r\n"
        f"^PR{spd}\r\n"
        f"~SD{sd:02d}\r\n"
        f"^FO0,0^GFA,{total_bytes},{total_bytes},{w_bytes},{hex_str}^FS\r\n"
        f"^PQ{qty}\r\n"
        f"^XZ\r\n"
    )
    return cmd.encode("ascii")


def encode_pdf_pages_to_zpl(
    pdf_bytes: bytes,
    width_mm: float,
    height_mm: float,
    dpi: int = 203,
    density: int = 8,
    speed: int = 4,
    copies_per_page: int = 1,
    offset_x_mm: float = 0.0,
    offset_y_mm: float = 0.0,
) -> bytes:
    """将多页矢量 PDF 按指定 DPI 栅格化并串联编码为 ZPL II 字节流。"""
    eng = PyMuPDFEngine()
    count = eng.get_page_count(pdf_bytes)
    chunks: list[bytes] = []
    for idx in range(count):
        img_1bit = eng.render_page_to_1bit(pdf_bytes, idx, dpi=dpi, threshold=160)
        chunks.append(
            encode_image_to_zpl(
                img_1bit,
                width_mm=width_mm,
                height_mm=height_mm,
                dpi=dpi,
                density=density,
                speed=speed,
                copies=copies_per_page,
                offset_x_mm=offset_x_mm,
                offset_y_mm=offset_y_mm,
            )
        )
    return b"".join(chunks)


def parse_and_decode_zpl(raw_bytes: bytes) -> list[DecodedZplCommand]:
    """逆向解析 ZPL II ^GFA 指令块并还原为 1-bit Pillow Image（用于干跑校验与机器扫码验证）。"""
    text = raw_bytes.decode("ascii", errors="replace")
    results: list[DecodedZplCommand] = []

    for m_block in re.finditer(r"\^XA(.*?)\^XZ", text, re.S):
        block = m_block.group(1)
        m_gfa = re.search(r"\^GFA,(\d+),(\d+),(\d+),([0-9A-Fa-f\s]+)", block)
        if not m_gfa:
            continue

        total_bytes = int(m_gfa.group(1))
        field_bytes = int(m_gfa.group(2))
        w_bytes = int(m_gfa.group(3))
        hex_clean = re.sub(r"\s+", "", m_gfa.group(4))
        payload = bytes.fromhex(hex_clean)

        if len(payload) != total_bytes or total_bytes != field_bytes:
            raise ValueError(f"ZPL ^GFA 载荷长度不一致: expected={total_bytes}, field={field_bytes}, actual={len(payload)}")
        if w_bytes <= 0 or total_bytes % w_bytes != 0:
            raise ValueError(f"ZPL ^GFA 行字节宽异常: total={total_bytes}, w_bytes={w_bytes}")

        h_dots = total_bytes // w_bytes
        pw_m = re.search(r"\^PW(\d+)", block)
        ll_m = re.search(r"\^LL(\d+)", block)
        ls_m = re.search(r"\^LS(-?\d+)", block)
        lt_m = re.search(r"\^LT(-?\d+)", block)
        sd_m = re.search(r"~SD(\d+)", block)
        pr_m = re.search(r"\^PR(\d+)", block)
        pq_m = re.search(r"\^PQ(\d+)", block)

        pil_bytes = bytes(b ^ 0xFF for b in payload)
        img = Image.frombytes("1", (w_bytes * 8, h_dots), pil_bytes)
        pw_dots = int(pw_m.group(1)) if pw_m else None
        ll_dots = int(ll_m.group(1)) if ll_m else None
        if pw_dots is not None and ll_dots is not None and pw_dots <= w_bytes * 8 and ll_dots <= h_dots:
            img = img.crop((0, 0, pw_dots, ll_dots))

        results.append(
            DecodedZplCommand(
                pw_dots=pw_dots,
                ll_dots=ll_dots,
                ls_dots=int(ls_m.group(1)) if ls_m else 0,
                lt_dots=int(lt_m.group(1)) if lt_m else 0,
                density=(int(sd_m.group(1)) // 2) if sd_m else None,
                speed=int(pr_m.group(1)) if pr_m else None,
                width_bytes=w_bytes,
                height_dots=h_dots,
                copies=int(pq_m.group(1)) if pq_m else 1,
                bitmap_payload=payload,
                image=img,
            )
        )

    return results
