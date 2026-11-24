import type {
  BackupExportResult,
  BackupImportResult,
  BackupSummary,
  BatchSkuItem,
  BoxGroupBy,
  BoxPaperSize,
  BoxPrintPreferences,
  CalibrationProfile,
  CanvasElement,
  CarrierRule,
  FbaRedactionOptions,
  PairingGroup,
  PairingResponse,
  PrintBatchRecord,
  PrinterDevice,
  PrintQueueItem,
  SkuTemplate,
  UploadedCarrierFile,
  UploadedFbaFile,
} from "../types";

async function apiJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let msg = `请求失败 (${res.status})`;
    try {
      const err = await res.json();
      if (err && typeof err.detail === "string") msg = err.detail;
    } catch {
      // 保持默认错误提示
    }
    throw new Error(msg);
  }
  return (await res.json()) as T;
}

export async function processFbaFile(
  file: File,
  opts: FbaRedactionOptions,
  paperSize: BoxPaperSize = "100x100",
): Promise<UploadedFbaFile> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("redact_ship_from", String(opts.redact_ship_from));
  fd.append("redact_fba_company", String(opts.redact_fba_company));
  fd.append("redact_headers", String(opts.redact_headers));
  fd.append("auto_add_mic", String(opts.auto_add_mic));
  fd.append("awd_apply_redaction", String(Boolean(opts.awd_apply_redaction)));
  fd.append("paper_size", paperSize);
  fd.append("offset_x_mm", String(opts.offset_x_mm));
  fd.append("offset_y_mm", String(opts.offset_y_mm));

  const res = await apiJson<UploadedFbaFile>("/api/box/process-fba", { method: "POST", body: fd });
  return { ...res, rawFile: file };
}

export async function processCarrierFile(
  file: File,
  paperSize: BoxPaperSize = "100x100",
  offsetX = 0,
  offsetY = 0,
): Promise<UploadedCarrierFile> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("paper_size", paperSize);
  fd.append("offset_x_mm", String(offsetX));
  fd.append("offset_y_mm", String(offsetY));
  const res = await apiJson<UploadedCarrierFile>("/api/box/process-carrier", { method: "POST", body: fd });
  return { ...res, rawFile: file };
}

export async function pairBoxes(payload: {
  fba_boxes: UploadedFbaFile["boxes"];
  carrier_boxes: UploadedCarrierFile["items"];
  manual_assignments: Record<string, string>;
  group_by?: BoxGroupBy;
  insert_separator_pages?: boolean;
  work_mode: "paired" | "fba_only" | "carrier_only";
  order_mode: "interleave" | "per_box_group" | "split_all";
  default_copies: number;
  box_copies: Record<string, number>;
  default_fba_copies?: number;
  default_carrier_copies?: number;
  box_fba_copies?: Record<string, number>;
  box_carrier_copies?: Record<string, number>;
  selected_keys: Record<string, boolean>;
  force_unlocked: boolean;
  active_shipment_id?: string | null;
}): Promise<PairingResponse> {
  return apiJson<PairingResponse>("/api/box/pair", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function exportMergedBoxPdf(payload: {
  fba_pdfs_b64: Record<string, string>;
  carrier_pdfs_b64: Record<string, string>;
  queue: PrintQueueItem[];
  overlay_elements?: CanvasElement[];
  paper_size?: BoxPaperSize;
}): Promise<{ page_count: number; pdf_b64: string }> {
  return apiJson<{ page_count: number; pdf_b64: string }>("/api/box/export-merged-pdf", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function exportBoxManifestCsv(payload: {
  queue: PrintQueueItem[];
  title?: string;
}): Promise<{ filename: string; row_count: number; csv_b64: string }> {
  return apiJson("/api/box/export-manifest-csv", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function exportBoxSkuZip(payload: {
  fba_pdfs_b64: Record<string, string>;
  carrier_pdfs_b64: Record<string, string>;
  groups: PairingGroup[];
  group_by?: BoxGroupBy;
  work_mode: "paired" | "fba_only" | "carrier_only";
  order_mode: "interleave" | "per_box_group" | "split_all";
  insert_separator_pages: boolean;
  force_unlocked?: boolean;
  overlay_elements?: CanvasElement[];
  paper_size?: BoxPaperSize;
}): Promise<{
  filename: string;
  file_count: number;
  total_pages: number;
  group_by?: string;
  skipped_groups?: string[];
  zip_b64: string;
}> {
  return apiJson("/api/box/export-sku-zip", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function parseFnskuPdf(file: File): Promise<{ fnsku: string; title_raw: string; title_clean: string }> {
  const fd = new FormData();
  fd.append("file", file);
  return apiJson("/api/fnsku/parse-pdf", { method: "POST", body: fd });
}

export async function renderFnskuPreview(payload: {
  elements: CanvasElement[];
  widthMm: number;
  heightMm: number;
  layoutType: "double" | "single";
  colGapMm: number;
  offsetXMm: number;
  offsetYMm: number;
  qty: number;
  dpi?: 203 | 300;
}): Promise<{ page_count: number; dpi?: number; pdf_b64: string; preview_203dpi_b64: string }> {
  return apiJson("/api/fnsku/render-preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function fetchTemplates(): Promise<SkuTemplate[]> {
  return apiJson<SkuTemplate[]>("/api/fnsku/templates");
}

export async function saveTemplate(payload: {
  id?: string;
  sku: string;
  fnsku: string;
  title_raw: string;
  title_clean: string;
  widthMm: number;
  heightMm: number;
  layoutType: "double" | "single";
  elements: CanvasElement[];
  defaultQty: number;
}): Promise<SkuTemplate> {
  return apiJson<SkuTemplate>("/api/fnsku/templates", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteTemplate(skuId: string): Promise<void> {
  await apiJson(`/api/fnsku/templates/${encodeURIComponent(skuId)}`, { method: "DELETE" });
}

export async function fetchBatches(): Promise<PrintBatchRecord[]> {
  return apiJson<PrintBatchRecord[]>("/api/batches");
}

export async function fetchBatchPdf(
  batchId: string,
): Promise<{ batch_id: string; filename: string; page_count?: number; pdf_b64: string }> {
  return apiJson(`/api/batches/${encodeURIComponent(batchId)}/pdf`);
}

export async function deleteBatch(batchId: string): Promise<void> {
  await apiJson(`/api/batches/${encodeURIComponent(batchId)}`, { method: "DELETE" });
}

export async function fetchPrinters(): Promise<PrinterDevice[]> {
  return apiJson<PrinterDevice[]>("/api/hardware/printers");
}

export async function fetchProfiles(): Promise<CalibrationProfile[]> {
  return apiJson<CalibrationProfile[]>("/api/hardware/profiles");
}

export async function updateProfile(profile: CalibrationProfile): Promise<CalibrationProfile> {
  return apiJson<CalibrationProfile>(`/api/hardware/profiles/${encodeURIComponent(profile.spec_key)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(profile),
  });
}

export async function fetchSpecState(): Promise<{ last_printed_spec: string }> {
  return apiJson<{ last_printed_spec: string }>("/api/hardware/spec-state");
}

export async function updateSpecState(lastPrintedSpec: string): Promise<{ last_printed_spec: string }> {
  return apiJson<{ last_printed_spec: string }>("/api/hardware/spec-state", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ last_printed_spec: lastPrintedSpec }),
  });
}

export async function generateCalibrationCard(specKey: string): Promise<{
  spec_key: string;
  dpi?: number;
  protocol?: string;
  pdf_b64: string;
  preview_203dpi_b64: string;
}> {
  return apiJson("/api/hardware/calibration-card", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ spec_key: specKey }),
  });
}

export async function testNetworkPrinter(
  host: string,
  port = 9100,
): Promise<{ ok: boolean; host: string; port: number; latency_ms?: number; message: string }> {
  return apiJson("/api/hardware/test-network", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ host, port }),
  });
}

export async function executePrint(payload: {
  pdf_b64: string;
  spec_key: string;
  channel: string;
  printer_name: string;
  dry_run?: boolean;
  protocol?: "tspl" | "zpl";
  dpi?: 203 | 300;
  connection_type?: "os_queue" | "network_tcp";
  network_host?: string;
  network_port?: number;
  batch: {
    batch_type: "fnsku" | "box_paired" | "box_fba_only" | "box_carrier_only";
    shipment_id: string;
    warehouse_code: string;
    spec_key: string;
    total_units_or_boxes: number;
    copies_per_box: number;
    order_mode: string;
    channel: string;
    summary: string;
    source_files?: string[];
    overlay_elements?: CanvasElement[];
  };
}): Promise<{
  ok: boolean;
  page_count?: number;
  protocol?: string;
  dpi?: number;
  connection_type?: string;
  tspl_bytes_len: number;
  tspl_commands: number;
  command_headers?: string[];
  printer_result: Record<string, unknown>;
  batch: PrintBatchRecord;
  last_printed_spec: string;
}> {
  return apiJson("/api/hardware/execute-print", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function downloadBase64File(b64: string, fileName: string, mimeType = "application/octet-stream"): void {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
  const blob = new Blob([bytes], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function downloadBase64Pdf(pdfB64: string, fileName: string): void {
  downloadBase64File(pdfB64, fileName, "application/pdf");
}

export async function fetchCarrierRules(): Promise<CarrierRule[]> {
  return apiJson<CarrierRule[]>("/api/box/carrier-rules");
}

export async function saveCarrierRule(rule: CarrierRule): Promise<CarrierRule> {
  return apiJson<CarrierRule>("/api/box/carrier-rules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(rule),
  });
}

export async function deleteCarrierRule(ruleId: string): Promise<void> {
  await apiJson(`/api/box/carrier-rules/${encodeURIComponent(ruleId)}`, { method: "DELETE" });
}

export async function testCarrierRules(payload: {
  sample_text: string;
  file_name: string;
  rules?: CarrierRule[];
}): Promise<{ shipment_id: string | null; warehouse_code: string | null; box_index: number; total_boxes: number }> {
  return apiJson("/api/box/carrier-rules/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function createCalibrationProfile(profile: CalibrationProfile): Promise<CalibrationProfile> {
  return apiJson<CalibrationProfile>("/api/hardware/profiles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(profile),
  });
}

export async function deleteCalibrationProfile(specKey: string): Promise<void> {
  await apiJson(`/api/hardware/profiles/${encodeURIComponent(specKey)}`, { method: "DELETE" });
}

export function getFnskuCsvTemplateUrl(): string {
  return "/api/fnsku/csv-template";
}

export async function parseFnskuCsv(
  file: File,
): Promise<{ items: BatchSkuItem[]; total_skus: number; total_labels: number; warnings: string[] }> {
  const fd = new FormData();
  fd.append("file", file);
  return apiJson("/api/fnsku/parse-csv", { method: "POST", body: fd });
}

export async function renderFnskuBatch(payload: {
  templateElements: CanvasElement[];
  items: BatchSkuItem[];
  widthMm: number;
  heightMm: number;
  layoutType: "double" | "single";
  colGapMm: number;
  offsetXMm: number;
  offsetYMm: number;
  dpi?: 203 | 300;
  pageBreakBetweenSkus: boolean;
}): Promise<{
  page_count: number;
  total_labels: number;
  total_skus: number;
  dpi: number;
  pdf_b64: string;
  preview_203dpi_b64: string;
}> {
  return apiJson("/api/fnsku/render-batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function fetchBoxPreferences(): Promise<BoxPrintPreferences> {
  return apiJson<BoxPrintPreferences>("/api/box/preferences");
}

export async function saveBoxPreferences(prefs: BoxPrintPreferences): Promise<BoxPrintPreferences> {
  return apiJson<BoxPrintPreferences>("/api/box/preferences", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(prefs),
  });
}

export async function fetchBackupSummary(): Promise<BackupSummary> {
  return apiJson<BackupSummary>("/api/system/backup/summary");
}

export async function exportSystemBackup(includeSnapshots: boolean): Promise<BackupExportResult> {
  return apiJson<BackupExportResult>("/api/system/backup/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ include_snapshots: includeSnapshots }),
  });
}

export async function importSystemBackup(
  file: File,
  mode: "merge" | "replace",
): Promise<BackupImportResult> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("mode", mode);
  return apiJson<BackupImportResult>("/api/system/backup/import", {
    method: "POST",
    body: fd,
  });
}
