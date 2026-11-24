"""Pydantic v2 请求、响应与核心领域模型（所有坐标统一采用物理毫米 mm）。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CanvasElement(BaseModel):
    """统一画布元素模型：用于产品标排版及外箱标叠层精修。"""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    type: Literal["barcode1d", "qrcode", "text", "rect", "line", "mask", "image"]
    name: str | None = None
    x: float = 0.0
    y: float = 0.0
    w: float = 20.0
    h: float = 10.0
    rotate: Literal[0, 90, 180, 270] = 0
    locked: bool = False

    # 一体化条形码与可读编码（禁止拆分独立文本，修改 code 时同步联动）
    code: str | None = None
    show_text: bool = Field(default=True, alias="showText")
    font_size: float = Field(default=8.5, alias="fontSize")

    # 文本元素属性
    text: str | None = None
    line_height: float = Field(default=1.25, alias="lineHeight")
    align: Literal["left", "center", "right"] = "left"
    bold: bool = False
    italic: bool = False

    # 矢量边框 / 分割线 / 图片叠加属性
    stroke_width: float = Field(default=0.4, alias="strokeWidth")
    dashed: bool = False
    fill: str | None = None
    image_data_url: str | None = Field(default=None, alias="imageDataUrl")


class FbaRedactionOptions(BaseModel):
    """FBA 外箱标语义脱敏与落版参数。"""

    redact_ship_from: bool = True
    redact_fba_company: bool = True
    redact_headers: bool = False
    auto_add_mic: bool = True
    safe_width_mm: float = 98.0
    safe_height_mm: float = 98.0
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0


class FbaBoxMeta(BaseModel):
    """单箱 FBA 外箱标解析元数据。"""

    file_id: str = ""
    file_name: str = ""
    page_index: int = 0
    shipment_id: str | None = None
    box_id: str | None = None
    box_index: int = 1
    total_boxes: int = 1
    warehouse_code: str | None = None
    lang: Literal["en", "zh", "unknown"] = "en"
    weight_text: str | None = None
    sku_text: str | None = None
    qty: int | None = None
    has_made_in_china: bool = False
    mic_auto_added: bool = False
    redacted_regions_count: int = 0
    clean_preview_b64: str = ""
    raw_preview_b64: str = ""
    full_page_b64: str = ""


class CarrierBoxMeta(BaseModel):
    """单页货代箱唛解析元数据。"""

    file_id: str = ""
    file_name: str = ""
    page_index: int = 0
    shipment_id: str | None = None
    assigned_shipment_id: str | None = None
    box_index: int = 1
    total_boxes: int = 1
    warehouse_code: str | None = None
    forwarder_name: str | None = None
    preview_b64: str = ""

    @property
    def effective_shipment_id(self) -> str | None:
        return (self.assigned_shipment_id or self.shipment_id or "").strip() or None


class FbaProcessResponse(BaseModel):
    """FBA 外箱 PDF 批量处理结果。"""

    file_id: str
    file_name: str
    page_count: int
    shipment_id: str | None
    warehouse_code: str | None
    boxes: list[FbaBoxMeta]
    pdf_b64: str


class CarrierProcessResponse(BaseModel):
    """货代箱唛 PDF 批量处理结果。"""

    file_id: str
    file_name: str
    page_count: int
    shipment_id: str | None
    warehouse_code: str | None
    items: list[CarrierBoxMeta]
    pdf_b64: str


class PairingPairItem(BaseModel):
    """组内按箱号绑定的一对（或单边）标签项。"""

    box_index: int
    fba_box: FbaBoxMeta | None = None
    carrier_box: CarrierBoxMeta | None = None
    selected: bool = True
    copies: int = 4


class PairingGroup(BaseModel):
    """按 FBA 编号隔离的配对分组。"""

    shipment_id: str
    warehouse_code: str | None = None
    status: Literal["matched", "missing_carrier", "missing_fba", "mismatch_detail"]
    issues: list[str] = Field(default_factory=list)
    pairs: list[PairingPairItem] = Field(default_factory=list)


class PrintQueueItem(BaseModel):
    """最终出纸队列单项。"""

    seq: int
    kind: Literal["fba", "carrier"]
    shipment_id: str
    box_index: int
    copy_no: int
    page_index: int
    label: str
    file_id: str = ""


class PairingRequest(BaseModel):
    """外箱与箱唛自动/人工配对与排期请求。"""

    fba_boxes: list[FbaBoxMeta] = Field(default_factory=list)
    carrier_boxes: list[CarrierBoxMeta] = Field(default_factory=list)
    manual_assignments: dict[str, str] = Field(
        default_factory=dict,
        description="映射 file_id（或 file_id:page_index）到目标 FBA 货件编号",
    )
    work_mode: Literal["paired", "fba_only", "carrier_only"] = "paired"
    order_mode: Literal["interleave", "per_box_group", "split_all"] = "interleave"
    default_copies: int = 4
    box_copies: dict[str, int] = Field(default_factory=dict)
    selected_keys: dict[str, bool] = Field(default_factory=dict)
    force_unlocked: bool = False
    active_shipment_id: str | None = None


class PairingResponse(BaseModel):
    """配对分组与校验、队列结果。"""

    groups: list[PairingGroup]
    unassigned_carriers: list[CarrierBoxMeta]
    active_shipment_id: str | None = None
    can_print: bool = False
    issues: list[str] = Field(default_factory=list)
    queue: list[PrintQueueItem] = Field(default_factory=list)
    total_sheets: int = 0


class SkuTemplateUpsert(BaseModel):
    """创建或更新产品标签模板。"""

    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    sku: str
    fnsku: str
    title_raw: str = ""
    title_clean: str = ""
    width_mm: float = Field(default=50.0, alias="widthMm")
    height_mm: float = Field(default=30.0, alias="heightMm")
    layout_type: Literal["double", "single"] = Field(default="double", alias="layoutType")
    elements: list[CanvasElement] = Field(default_factory=list)
    default_qty: int = Field(default=60, alias="defaultQty")


class SkuTemplate(SkuTemplateUpsert):
    id: str
    updated_at: str


class BarcodeReadabilityReport(BaseModel):
    """203dpi 条码模块宽度与可读性评估。"""

    code: str
    total_modules: int
    dots_per_module: float
    min_dots_per_module: int
    level: Literal["safe", "warn", "danger"]
    message: str


class FnskuRenderRequest(BaseModel):
    """产品标签自由排版实时渲染与拼版请求。"""

    model_config = ConfigDict(populate_by_name=True)

    elements: list[CanvasElement]
    width_mm: float = Field(default=50.0, alias="widthMm")
    height_mm: float = Field(default=30.0, alias="heightMm")
    layout_type: Literal["double", "single"] = Field(default="double", alias="layoutType")
    col_gap_mm: float = Field(default=2.0, alias="colGapMm")
    offset_x_mm: float = Field(default=0.0, alias="offsetXMm")
    offset_y_mm: float = Field(default=0.0, alias="offsetYMm")
    qty: int = 2
    dpi: Literal[203, 300] = 203
    overlay_box_clean: bool = False


class BatchSkuItem(BaseModel):
    """CSV / 批量套打单款 SKU 明细条目。"""

    sku: str = ""
    fnsku: str = Field(..., min_length=1, max_length=64)
    title: str = ""
    qty: int = Field(default=1, ge=1, le=9999)


class FnskuBatchRenderRequest(BaseModel):
    """多 SKU 批量标签排版渲染请求。"""

    model_config = ConfigDict(populate_by_name=True)

    template_elements: list[CanvasElement] = Field(..., alias="templateElements")
    items: list[BatchSkuItem] = Field(..., min_length=1, max_length=500)
    width_mm: float = Field(default=50.0, alias="widthMm")
    height_mm: float = Field(default=30.0, alias="heightMm")
    layout_type: Literal["double", "single"] = Field(default="double", alias="layoutType")
    col_gap_mm: float = Field(default=2.0, alias="colGapMm")
    offset_x_mm: float = Field(default=0.0, alias="offsetXMm")
    offset_y_mm: float = Field(default=0.0, alias="offsetYMm")
    dpi: Literal[203, 300] = 203
    page_break_between_skus: bool = Field(default=True, alias="pageBreakBetweenSkus")


class CalibrationProfile(BaseModel):
    """纸卷规格硬件校准与打印机绑定参数。"""

    spec_key: str
    label_width_mm: float
    label_height_mm: float
    cols: int = 1
    col_gap_mm: float = 0.0
    row_gap_mm: float = 2.0
    safe_width_mm: float = 98.0
    safe_height_mm: float = 98.0
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    darkness: int = 8
    print_speed: int = 4
    preferred_channel: Literal["tspl_raw", "os_driver", "pdf_export"] = "tspl_raw"
    printer_name: str = ""
    protocol: Literal["tspl", "zpl"] = "tspl"
    dpi: Literal[203, 300] = 203
    connection_type: Literal["os_queue", "network_tcp"] = "os_queue"
    network_host: str = ""
    network_port: int = Field(default=9100, ge=1, le=65535)


class SpecStateUpdate(BaseModel):
    """更新当前打印机已装纸卷规格记忆。"""

    last_printed_spec: str


class PrintBatchCreate(BaseModel):
    batch_type: Literal["fnsku", "box_paired", "box_fba_only", "box_carrier_only"]
    shipment_id: str
    warehouse_code: str = "-"
    spec_key: str
    total_units_or_boxes: int
    copies_per_box: int = 1
    order_mode: str = "interleave"
    channel: str = "tspl_raw"
    summary: str
    source_files: list[str] = Field(default_factory=list)
    overlay_elements: list[CanvasElement] = Field(default_factory=list)
    snapshot_dir: str = ""


class PrintBatchRecord(BaseModel):
    id: str
    batch_type: str
    shipment_id: str
    warehouse_code: str
    spec_key: str
    total_units_or_boxes: int
    copies_per_box: int
    order_mode: str
    channel: str
    summary: str
    source_files: list[str] = Field(default_factory=list)
    overlay_elements: list[CanvasElement] = Field(default_factory=list)
    snapshot_dir: str = ""
    created_at: str


class PrinterDevice(BaseModel):
    name: str
    system: str
    is_default: bool = False
    is_recommended: bool = False
    status: str = "ready"
    status_detail: str = ""
    suggested_protocol: Literal["tspl", "zpl", "os_driver"] = "tspl"
    suggested_dpi: Literal[203, 300] = 203
    is_thermal_hint: bool = False


class CarrierRule(BaseModel):
    id: str = ""
    name: str
    shipment_regex: str = ""
    warehouse_regex: str = ""
    ctn_regex: str = ""
    default_rotate: int = 0
    enabled: bool = True


class AnyDictResponse(BaseModel):
    ok: bool = True
    data: dict[str, Any] = Field(default_factory=dict)
