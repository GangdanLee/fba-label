"""测试隔离环境配置与 100% 虚构中英文 PDF 测试夹具生成器。"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from app import db
from app.config import mm_to_pt
from app.engines.code128 import draw_barcode1d_on_reportlab, generate_qrcode_pil
from app.engines.font_manager import ensure_reportlab_font


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """为每个测试创建独立的临时 SQLite 数据目录，禁止写入仓库真实目录。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LABEL_PRINT_DATA_DIR", str(data_dir))
    db.init_db()
    return data_dir


def build_synthetic_fba_en_pdf(
    shipment_id: str = "FBA00DEMO01",
    warehouse: str = "DMO1",
    total_boxes: int = 2,
    include_mic: bool = True,
) -> bytes:
    """生成 100% 虚构的英文拼版风格 FBA 外箱 PDF（100×100mm，含左右敏感字段与真条码）。"""
    buf = io.BytesIO()
    w_mm, h_mm = 100.0, 100.0
    c = Canvas(buf, pagesize=(mm_to_pt(w_mm), mm_to_pt(h_mm)))
    font_reg = ensure_reportlab_font(prefer_cjk=False, bold=False)
    font_bold = ensure_reportlab_font(prefer_cjk=False, bold=True)

    for box_no in range(1, total_boxes + 1):
        box_id = f"{shipment_id}U{box_no:06d}"

        # 顶栏标题
        c.setFont(font_bold, 13)
        c.drawString(mm_to_pt(4), mm_to_pt(h_mm - 8), "FBA")
        c.setFont(font_bold, 9)
        c.drawRightString(mm_to_pt(96), mm_to_pt(h_mm - 8), f"Box {box_no} of {total_boxes} - 30lb")
        c.setLineWidth(1.2)
        c.line(mm_to_pt(4), mm_to_pt(h_mm - 10), mm_to_pt(96), mm_to_pt(h_mm - 10))

        # 左栏：SHIP FROM（整块发件地址应被抹除）
        c.setFont(font_bold, 7.5)
        c.drawString(mm_to_pt(4), mm_to_pt(h_mm - 14.5), "SHIP FROM:")
        c.setFont(font_reg, 7.0)
        c.drawString(mm_to_pt(4), mm_to_pt(h_mm - 18.5), "Demo Sender Logistics Co")
        c.drawString(mm_to_pt(4), mm_to_pt(h_mm - 22.0), "88 Fictional Road, Demo City")
        c.drawString(mm_to_pt(4), mm_to_pt(h_mm - 25.5), "Demo Country")

        # 右栏：SHIP TO（仅抹除 FBA: 后面的公司名，保留仓库地址）
        c.setFont(font_bold, 7.5)
        c.drawString(mm_to_pt(52), mm_to_pt(h_mm - 14.5), "SHIP TO:")
        c.setFont(font_bold, 6.8)
        c.drawString(mm_to_pt(52), mm_to_pt(h_mm - 18.5), "FBA: Example Fictional Seller Ltd")
        c.setFont(font_reg, 7.0)
        c.drawString(mm_to_pt(52), mm_to_pt(h_mm - 22.0), "Amazon Demo FC")
        c.drawString(mm_to_pt(52), mm_to_pt(h_mm - 25.5), "100 Mock Ave, Demo City, US 00000")

        # 中央黑色分割横带
        c.setFillColorRGB(0, 0, 0)
        c.rect(mm_to_pt(4), mm_to_pt(h_mm - 32.5), mm_to_pt(92), mm_to_pt(4.5), stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont(font_bold, 6.5)
        c.drawString(mm_to_pt(5.5), mm_to_pt(h_mm - 31.2), f"FBA STA (DEMO) - {warehouse}")
        c.drawRightString(mm_to_pt(94.5), mm_to_pt(h_mm - 31.2), "Created: DEMO-BATCH")

        # 主条码与右侧 2D QR 码
        c.setFillColorRGB(0, 0, 0)
        draw_barcode1d_on_reportlab(
            c=c,
            code=box_id,
            x_mm=4.0,
            y_top_mm=36.0,
            w_mm=66.0,
            h_mm=28.0,
            page_h_mm=h_mm,
            show_text=True,
            font_size_pt=7.5,
        )
        qr_img = generate_qrcode_pil(box_id, scale=4)
        c.drawImage(
            ImageReader(qr_img),
            mm_to_pt(73.0),
            mm_to_pt(h_mm - 62.0),
            width=mm_to_pt(22.0),
            height=mm_to_pt(22.0),
            preserveAspectRatio=True,
        )

        c.setFont(font_bold, 8)
        if include_mic:
            c.drawString(mm_to_pt(8), mm_to_pt(h_mm - 76.0), "Made In China")
        c.drawRightString(mm_to_pt(68), mm_to_pt(h_mm - 76.0), "DEMO-SKU-01 · Qty 100")
        c.drawCentredString(mm_to_pt(50), mm_to_pt(h_mm - 92.0), "PLEASE LEAVE THIS LABEL UNCOVERED")
        c.showPage()

    c.save()
    return buf.getvalue()


def build_synthetic_fba_zh_4x6_pdf(
    shipment_id: str = "FBA00DEMO02",
    warehouse: str = "DMO2",
    total_boxes: int = 2,
) -> bytes:
    """生成 100% 虚构的中文 4×6 英寸外箱 PDF（右发货地/左目的地，含下半页大量留白且不含 Made In China）。"""
    buf = io.BytesIO()
    w_mm, h_mm = 101.6, 152.4  # 4×6 英寸
    c = Canvas(buf, pagesize=(mm_to_pt(w_mm), mm_to_pt(h_mm)))
    font_zh = ensure_reportlab_font(prefer_cjk=True, bold=False)
    font_bold = ensure_reportlab_font(prefer_cjk=False, bold=True)

    for box_no in range(1, total_boxes + 1):
        box_id = f"{shipment_id}U{box_no:06d}"

        # 上半页有效标签（y: 5mm..96mm，下半页 96..152mm 全空白）
        c.setFont(font_bold, 13)
        c.drawString(mm_to_pt(4), mm_to_pt(h_mm - 10), "FBA")
        c.setFont(font_zh, 8.5)
        c.drawRightString(mm_to_pt(97), mm_to_pt(h_mm - 10), f"纸箱编号 {box_no}，共 {total_boxes} 个纸箱 - 14kg")
        c.setLineWidth(1.2)
        c.line(mm_to_pt(4), mm_to_pt(h_mm - 12), mm_to_pt(97), mm_to_pt(h_mm - 12))

        # 中文版左侧为目的地，右侧为发货地
        c.setFont(font_zh, 7.5)
        c.drawString(mm_to_pt(4), mm_to_pt(h_mm - 16.5), "目的地：")
        c.setFont(font_zh, 7.0)
        c.drawString(mm_to_pt(4), mm_to_pt(h_mm - 20.5), "FBA: 虚构跨境卖家有限公司")
        c.drawString(mm_to_pt(4), mm_to_pt(h_mm - 24.0), "Amazon Mock FC")
        c.drawString(mm_to_pt(4), mm_to_pt(h_mm - 27.5), "200 Example Blvd, US 00001")

        c.setFont(font_zh, 7.5)
        c.drawString(mm_to_pt(54), mm_to_pt(h_mm - 16.5), "发货地：")
        c.setFont(font_zh, 7.0)
        c.drawString(mm_to_pt(54), mm_to_pt(h_mm - 20.5), "虚构测试商贸公司")
        c.drawString(mm_to_pt(54), mm_to_pt(h_mm - 24.0), "演示市模拟路88号")
        c.drawString(mm_to_pt(54), mm_to_pt(h_mm - 27.5), "中国")

        c.setFillColorRGB(0, 0, 0)
        c.rect(mm_to_pt(4), mm_to_pt(h_mm - 34.5), mm_to_pt(93), mm_to_pt(4.5), stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont(font_bold, 6.5)
        c.drawString(mm_to_pt(5.5), mm_to_pt(h_mm - 33.2), f"FBA STA (DEMO) - {warehouse}")

        c.setFillColorRGB(0, 0, 0)
        draw_barcode1d_on_reportlab(
            c=c,
            code=box_id,
            x_mm=4.0,
            y_top_mm=38.0,
            w_mm=67.0,
            h_mm=28.0,
            page_h_mm=h_mm,
            show_text=True,
            font_size_pt=7.5,
        )
        qr_img = generate_qrcode_pil(box_id, scale=4)
        c.drawImage(
            ImageReader(qr_img),
            mm_to_pt(74.0),
            mm_to_pt(h_mm - 64.0),
            width=mm_to_pt(22.0),
            height=mm_to_pt(22.0),
            preserveAspectRatio=True,
        )
        c.setFont(font_zh, 8)
        c.drawCentredString(mm_to_pt(50.8), mm_to_pt(h_mm - 88.0), "请不要遮住此标签")
        c.showPage()

    c.save()
    return buf.getvalue()


def build_synthetic_carrier_pdf(
    shipment_id: str | None = "FBA00DEMO01",
    warehouse: str = "DMO1",
    total_boxes: int = 2,
    route_name: str = "示例快运专线",
) -> bytes:
    """生成 100% 虚构货代箱唛 PDF（支持无编号场景以测试人工归属）。"""
    buf = io.BytesIO()
    w_mm, h_mm = 110.0, 120.0  # 故意加入外部留白以验证自动裁切居中落版
    c = Canvas(buf, pagesize=(mm_to_pt(w_mm), mm_to_pt(h_mm)))
    font_zh = ensure_reportlab_font(prefer_cjk=True, bold=False)
    font_bold = ensure_reportlab_font(prefer_cjk=False, bold=True)

    for ctn in range(1, total_boxes + 1):
        trk = f"TRK00DEMO{ctn:02d}"
        c.setLineWidth(1.5)
        c.rect(mm_to_pt(8), mm_to_pt(18), mm_to_pt(94), mm_to_pt(94))
        c.line(mm_to_pt(8), mm_to_pt(h_mm - 52), mm_to_pt(102), mm_to_pt(h_mm - 52))

        qr_val = f"{shipment_id or 'UNASSIGNED'}-CTN{ctn}"
        qr_img = generate_qrcode_pil(qr_val, scale=4)
        c.drawImage(
            ImageReader(qr_img),
            mm_to_pt(13),
            mm_to_pt(h_mm - 38),
            width=mm_to_pt(24),
            height=mm_to_pt(24),
            preserveAspectRatio=True,
        )
        c.setFont(font_bold, 11)
        c.drawString(mm_to_pt(15), mm_to_pt(h_mm - 46), f"CTNS:{ctn}/{total_boxes}")

        c.setFont(font_bold, 16)
        c.drawCentredString(mm_to_pt(72), mm_to_pt(h_mm - 23), warehouse)
        c.setFont(font_zh, 10)
        c.drawCentredString(mm_to_pt(72), mm_to_pt(h_mm - 36), route_name)

        c.setFont(font_bold, 12)
        if shipment_id:
            c.drawCentredString(mm_to_pt(55), mm_to_pt(h_mm - 62), shipment_id)
        else:
            c.drawCentredString(mm_to_pt(55), mm_to_pt(h_mm - 62), "ROUTE-ONLY-MARK")
        c.setFont(font_bold, 11)
        c.drawCentredString(mm_to_pt(55), mm_to_pt(h_mm - 71), "MADE IN CHINA")

        draw_barcode1d_on_reportlab(
            c=c,
            code=trk,
            x_mm=15.0,
            y_top_mm=75.0,
            w_mm=80.0,
            h_mm=20.0,
            page_h_mm=h_mm,
            show_text=True,
            font_size_pt=8.0,
        )
        c.showPage()

    c.save()
    return buf.getvalue()


def build_synthetic_product_pdf(
    fnsku: str = "X009DEMO01",
    title: str = "新品：演示硅胶地垫，大号灰色",
) -> bytes:
    """生成 100% 虚构亚马逊系统产品标签 PDF。"""
    buf = io.BytesIO()
    w_mm, h_mm = 50.0, 30.0
    c = Canvas(buf, pagesize=(mm_to_pt(w_mm), mm_to_pt(h_mm)))
    font_zh = ensure_reportlab_font(prefer_cjk=True, bold=False)

    draw_barcode1d_on_reportlab(
        c=c,
        code=fnsku,
        x_mm=3.0,
        y_top_mm=2.0,
        w_mm=44.0,
        h_mm=14.0,
        page_h_mm=h_mm,
        show_text=True,
        font_size_pt=8.0,
    )
    c.setFont(font_zh, 7.0)
    c.drawString(mm_to_pt(3), mm_to_pt(8.0), title)
    c.showPage()
    c.save()
    return buf.getvalue()
