/** 前后端一致的核心类型契约（画布元素坐标统一采用物理毫米 mm）。 */

export type TabKey = "box" | "editor" | "batches" | "hardware";
export type EditorMode = "sku_50x30" | "box_100x100";
export type BoxGroupBy = "shipment" | "sku";
export type BoxWorkMode = "paired" | "fba_only" | "carrier_only";
export type BoxOrderMode = "interleave" | "per_box_group" | "split_all";
export type BoxStageMode = "dual" | "compare";

export type ElementType = "barcode1d" | "qrcode" | "text" | "rect" | "line" | "mask" | "image";

export interface CanvasElement {
  id: string;
  type: ElementType;
  name?: string;
  x: number;
  y: number;
  w: number;
  h: number;
  rotate?: 0 | 90 | 180 | 270;
  locked?: boolean;
  code?: string;
  showText?: boolean;
  fontSize?: number;
  text?: string;
  lineHeight?: number;
  align?: "left" | "center" | "right";
  bold?: boolean;
  italic?: boolean;
  strokeWidth?: number;
  dashed?: boolean;
  fill?: string;
  imageDataUrl?: string;
}

export interface FbaRedactionOptions {
  redact_ship_from: boolean;
  redact_fba_company: boolean;
  redact_headers: boolean;
  auto_add_mic: boolean;
  offset_x_mm: number;
  offset_y_mm: number;
}

export interface FbaBoxMeta {
  file_id: string;
  file_name: string;
  page_index: number;
  shipment_id: string | null;
  box_id: string | null;
  box_index: number;
  total_boxes: number;
  warehouse_code: string | null;
  lang: "en" | "zh" | "unknown";
  weight_text?: string | null;
  sku_text?: string | null;
  is_mixed_sku?: boolean;
  qty?: number | null;
  has_made_in_china: boolean;
  mic_auto_added: boolean;
  redacted_regions_count: number;
  clean_preview_b64: string;
  raw_preview_b64: string;
  full_page_b64: string;
}

export interface CarrierBoxMeta {
  file_id: string;
  file_name: string;
  page_index: number;
  shipment_id: string | null;
  assigned_shipment_id: string | null;
  box_index: number;
  total_boxes: number;
  warehouse_code: string | null;
  forwarder_name?: string | null;
  preview_b64: string;
}

export interface UploadedFbaFile {
  file_id: string;
  file_name: string;
  page_count: number;
  shipment_id: string | null;
  warehouse_code: string | null;
  boxes: FbaBoxMeta[];
  pdf_b64: string;
  rawFile?: File;
}

export interface UploadedCarrierFile {
  file_id: string;
  file_name: string;
  page_count: number;
  shipment_id: string | null;
  warehouse_code: string | null;
  items: CarrierBoxMeta[];
  pdf_b64: string;
}

export interface PairingPairItem {
  box_index: number;
  shipment_id?: string;
  warehouse_code?: string | null;
  sku_text?: string | null;
  pair_key?: string;
  fba_box: FbaBoxMeta | null;
  carrier_box: CarrierBoxMeta | null;
  selected: boolean;
  copies: number;
  fba_copies: number;
  carrier_copies: number;
}

export interface BoxPrintPreferences {
  default_fba_copies: number;
  default_carrier_copies: number;
  group_by?: BoxGroupBy;
  insert_separator_pages?: boolean;
  order_mode: "interleave" | "per_box_group" | "split_all";
  work_mode: "paired" | "fba_only" | "carrier_only";
  redact_ship_from: boolean;
  redact_fba_company: boolean;
  redact_headers: boolean;
  auto_add_mic: boolean;
}

export interface PairingGroup {
  shipment_id: string;
  warehouse_code: string | null;
  group_kind?: "shipment" | "sku";
  display_label?: string;
  warehouses?: string[];
  shipment_ids?: string[];
  status: "matched" | "missing_carrier" | "missing_fba" | "mismatch_detail";
  issues: string[];
  pairs: PairingPairItem[];
}

export interface PrintQueueItem {
  seq: number;
  kind: "fba" | "carrier";
  shipment_id: string;
  box_index: number;
  copy_no: number;
  page_index: number;
  label: string;
  file_id: string;
  warehouse_code?: string;
  sku_text?: string;
  source_file_name?: string;
  source_page_no?: number;
  is_separator?: boolean;
  separator_title?: string;
  separator_detail?: string;
}

export interface SkuSummaryItem {
  sku_key: string;
  display_label: string;
  box_count: number;
  warehouses: string[];
  shipment_ids: string[];
  is_mixed: boolean;
  is_unrecognized: boolean;
}

export interface PairingResponse {
  groups: PairingGroup[];
  unassigned_carriers: CarrierBoxMeta[];
  active_shipment_id: string | null;
  group_by?: BoxGroupBy;
  sku_summary?: SkuSummaryItem[];
  can_print: boolean;
  issues: string[];
  queue: PrintQueueItem[];
  total_sheets: number;
}

export interface BackupSummary {
  skus_count: number;
  rules_count: number;
  profiles_count: number;
  batches_count: number;
  snapshot_files_count: number;
  snapshots_bytes: number;
  db_bytes: number;
}

export interface BackupExportResult {
  filename: string;
  size_bytes: number;
  counts: {
    skus: number;
    profiles: number;
    rules: number;
    batches: number;
    snapshots: number;
  };
  zip_b64: string;
}

export interface BackupImportResult {
  ok: boolean;
  mode: "merge" | "replace";
  restored: Record<string, number>;
  snapshots_restored: number;
  pre_import_backup_name: string;
}

export interface SkuTemplate {
  id: string;
  sku: string;
  fnsku: string;
  title_raw: string;
  title_clean: string;
  widthMm: number;
  heightMm: number;
  layoutType: "double" | "single";
  elements: CanvasElement[];
  defaultQty: number;
  updated_at: string;
}

export interface CalibrationProfile {
  spec_key: string;
  label_width_mm: number;
  label_height_mm: number;
  cols: number;
  col_gap_mm: number;
  row_gap_mm: number;
  safe_width_mm: number;
  safe_height_mm: number;
  offset_x_mm: number;
  offset_y_mm: number;
  darkness: number;
  print_speed: number;
  preferred_channel: "tspl_raw" | "os_driver" | "pdf_export";
  printer_name: string;
  protocol: "tspl" | "zpl";
  dpi: 203 | 300;
  connection_type: "os_queue" | "network_tcp";
  network_host: string;
  network_port: number;
  tspl_direction?: 0 | 1;
  invert_bitmap?: boolean;
}

export interface PrintBatchRecord {
  id: string;
  batch_type: string;
  shipment_id: string;
  warehouse_code: string;
  spec_key: string;
  total_units_or_boxes: number;
  copies_per_box: number;
  order_mode: string;
  channel: string;
  summary: string;
  source_files: string[];
  overlay_elements: CanvasElement[];
  snapshot_dir: string;
  created_at: string;
}

export interface PrinterDevice {
  name: string;
  system: string;
  is_default: boolean;
  is_recommended: boolean;
  status: string;
  status_detail?: string;
  suggested_protocol: "tspl" | "zpl" | "os_driver";
  suggested_dpi: 203 | 300;
  is_thermal_hint: boolean;
  brand_label?: string;
  usage_tip?: string;
}

export interface CarrierRule {
  id: string;
  name: string;
  shipment_regex: string;
  warehouse_regex: string;
  ctn_regex: string;
  default_rotate: number;
  enabled: boolean;
}

export interface BatchSkuItem {
  sku: string;
  fnsku: string;
  title: string;
  qty: number;
}
