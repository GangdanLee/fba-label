import { create } from "zustand";
import { notifications } from "@mantine/notifications";
import * as api from "../api/client";
import type {
  BoxOrderMode,
  BoxStageMode,
  BoxWorkMode,
  CalibrationProfile,
  CanvasElement,
  EditorMode,
  FbaRedactionOptions,
  PairingResponse,
  PrintBatchRecord,
  PrinterDevice,
  SkuTemplate,
  TabKey,
  UploadedCarrierFile,
  UploadedFbaFile,
} from "../types";
import { createDefaultElementsForSpec } from "../utils/code128";
import { createFictionalCarrierDemoFile, createFictionalFbaDemoFile } from "../utils/demoFixtures";

export function resolveTargetPrinterKey(
  prof: CalibrationProfile | undefined,
  printers: PrinterDevice[],
): string {
  if (prof?.connection_type === "network_tcp") {
    const h = (prof.network_host || "").trim();
    return h ? `tcp://${h}:${prof.network_port || 9100}` : "tcp://unconfigured";
  }
  const assigned = (prof?.printer_name || "").trim();
  if (assigned) return `os:${assigned}`;
  const rec = printers.find((d) => d.is_recommended) || printers[0];
  return rec ? `os:${rec.name}` : "os:auto";
}

export interface PendingPrintJob {
  title: string;
  summaryDesc: string;
  specKey: string;
  batchType: "fnsku" | "box_paired" | "box_fba_only" | "box_carrier_only";
  shipmentId: string;
  warehouseCode: string;
  totalUnitsOrBoxes: number;
  copiesPerBox: number;
  orderMode: string;
  totalSheets: number;
  sourceFiles: string[];
  getPdfB64: () => Promise<string>;
}

const DEFAULT_DRAFT_TEMPLATE: SkuTemplate = {
  id: "draft_default_50x30",
  sku: "DEMO-SKU-01",
  fnsku: "X000DEMO01",
  title_raw: "New - Demo Product Item (DEMO-SKU-01)",
  title_clean: "New - Demo Product Item (DEMO-SKU-01)",
  widthMm: 50,
  heightMm: 30,
  layoutType: "double",
  elements: createDefaultElementsForSpec(50, 30, "X000DEMO01", "New - Demo Product Item (DEMO-SKU-01)"),
  defaultQty: 120,
  updated_at: "",
};

interface WorkbenchState {
  activeTab: TabKey;
  lastPrintedSpec: string;
  profiles: CalibrationProfile[];
  printers: PrinterDevice[];
  batches: PrintBatchRecord[];
  templates: SkuTemplate[];

  // 外箱模块
  fbaFiles: UploadedFbaFile[];
  carrierFiles: UploadedCarrierFile[];
  manualAssignments: Record<string, string>;
  workMode: BoxWorkMode;
  orderMode: BoxOrderMode;
  stageMode: BoxStageMode;
  showSafeFrame: boolean;
  defaultCopies: number;
  boxCopies: Record<string, number>;
  selectedBoxKeys: Record<string, boolean>;
  forceUnlocked: boolean;
  redactionOptions: FbaRedactionOptions;
  pairing: PairingResponse;
  activeGroupId: string | null;
  activeBoxIndex: number;
  boxBusy: boolean;

  // 标签设计器
  editorMode: EditorMode;
  draftSku: SkuTemplate;
  boxOverlayElements: CanvasElement[];
  selectedElementId: string | null;
  historyPast: CanvasElement[][];
  historyFuture: CanvasElement[][];
  zoom: number;
  snapGrid: boolean;
  showGrid: boolean;
  editorSim203: boolean;
  editorSim203B64: string;
  fnskuQty: number;
  colGapMm: number;

  // 弹窗状态
  printModalOpen: boolean;
  pendingPrintJob: PendingPrintJob | null;

  // Actions
  setActiveTab: (tab: TabKey) => void;
  initApp: () => Promise<void>;
  setLastPrintedSpec: (specKey: string) => Promise<void>;
  toggleQuickSpecSwitch: () => Promise<void>;
  getExpectedSpecKey: () => string;
  getCalibrationForSpec: (specKey: string) => CalibrationProfile | undefined;

  // 外箱 Actions
  uploadFbaFiles: (files: File[]) => Promise<void>;
  uploadCarrierFiles: (files: File[]) => Promise<void>;
  removeFbaFile: (fileId: string) => Promise<void>;
  removeCarrierFile: (fileId: string) => Promise<void>;
  clearBoxWorkspace: () => void;
  setManualAssignment: (carrierFileId: string, shipmentId: string) => Promise<void>;
  updateRedactionOption: <K extends keyof FbaRedactionOptions>(key: K, val: FbaRedactionOptions[K]) => Promise<void>;
  setWorkMode: (mode: BoxWorkMode) => Promise<void>;
  setOrderMode: (mode: BoxOrderMode) => Promise<void>;
  setStageMode: (mode: BoxStageMode) => void;
  setShowSafeFrame: (v: boolean) => void;
  setDefaultCopies: (n: number) => Promise<void>;
  setSingleBoxCopies: (shipmentId: string, boxIdx: number, copies: number) => Promise<void>;
  toggleSingleBoxSelected: (shipmentId: string, boxIdx: number, selected: boolean) => Promise<void>;
  setActiveGroupId: (sid: string) => void;
  setActiveBoxIndex: (idx: number) => void;
  recomputePairing: () => Promise<void>;
  loadFictionalDemo: (scenario: "dual_mix" | "unassigned" | "clear") => Promise<void>;

  // 设计器 Actions
  setEditorMode: (mode: EditorMode) => void;
  selectElement: (id: string | null) => void;
  pushHistory: () => void;
  undo: () => void;
  redo: () => void;
  moveElementLayer: (id: string, dir: "up" | "down") => void;
  clearBoxOverlays: () => void;
  setZoom: (z: number) => void;
  setSnapGrid: (v: boolean) => void;
  setShowGrid: (v: boolean) => void;
  setEditorSim203: (v: boolean) => Promise<void>;
  setFnskuQty: (q: number) => void;
  updateActiveElements: (updater: (els: CanvasElement[]) => CanvasElement[], recordHistory?: boolean) => void;
  updateDraftMeta: (patch: Partial<SkuTemplate>) => void;
  selectTemplate: (tpl: SkuTemplate) => void;
  createNewTemplate: (opts: { sku: string; fnsku: string; widthMm: number; heightMm: number; layoutType: "double" | "single" }) => void;
  saveDraftTemplate: () => Promise<void>;
  removeTemplate: (id: string) => Promise<void>;
  importProductPdf: (file: File) => Promise<void>;

  // 打印弹窗与硬件 Actions
  openPrintJob: (job: PendingPrintJob) => void;
  closePrintModal: () => void;
  saveProfile: (prof: CalibrationProfile) => Promise<void>;
  createProfile: (prof: CalibrationProfile) => Promise<void>;
  removeProfile: (specKey: string) => Promise<void>;
  refreshPrinters: () => Promise<void>;
  refreshBatches: () => Promise<void>;
  deleteBatchRecord: (id: string) => Promise<void>;
}

const EMPTY_PAIRING: PairingResponse = {
  groups: [],
  unassigned_carriers: [],
  active_shipment_id: null,
  can_print: false,
  issues: [],
  queue: [],
  total_sheets: 0,
};

export const useWorkbenchStore = create<WorkbenchState>((set, get) => ({
  activeTab: "box",
  lastPrintedSpec: "100x100_single",
  profiles: [],
  printers: [],
  batches: [],
  templates: [],

  fbaFiles: [],
  carrierFiles: [],
  manualAssignments: {},
  workMode: "paired",
  orderMode: "interleave",
  stageMode: "dual",
  showSafeFrame: true,
  defaultCopies: 4,
  boxCopies: {},
  selectedBoxKeys: {},
  forceUnlocked: false,
  redactionOptions: {
    redact_ship_from: true,
    redact_fba_company: true,
    redact_headers: false,
    auto_add_mic: true,
    offset_x_mm: 0,
    offset_y_mm: 0,
  },
  pairing: EMPTY_PAIRING,
  activeGroupId: null,
  activeBoxIndex: 1,
  boxBusy: false,

  editorMode: "sku_50x30",
  draftSku: DEFAULT_DRAFT_TEMPLATE,
  boxOverlayElements: [],
  selectedElementId: null,
  historyPast: [],
  historyFuture: [],
  zoom: 1.25,
  snapGrid: true,
  showGrid: true,
  editorSim203: false,
  editorSim203B64: "",
  fnskuQty: 120,
  colGapMm: 2.0,

  printModalOpen: false,
  pendingPrintJob: null,

  setActiveTab: (tab) => set({ activeTab: tab }),

  initApp: async () => {
    try {
      const [profiles, specState, templates, batches, printers] = await Promise.all([
        api.fetchProfiles(),
        api.fetchSpecState(),
        api.fetchTemplates(),
        api.fetchBatches(),
        api.fetchPrinters().catch(() => []),
      ]);
      const prof50 = profiles.find((p) => p.spec_key === "50x30_double");
      set({
        profiles,
        lastPrintedSpec: specState.last_printed_spec || "100x100_single",
        templates,
        batches,
        printers,
        colGapMm: prof50 ? prof50.col_gap_mm : 2.0,
      });
    } catch (err) {
      notifications.show({
        title: "连接后端服务提示",
        message: err instanceof Error ? err.message : "请确认后端服务已在本地启动",
        color: "red",
      });
    }
  },

  getExpectedSpecKey: () => {
    const s = get();
    if (s.activeTab === "box" || (s.activeTab === "editor" && s.editorMode === "box_100x100")) {
      return "100x100_single";
    }
    return `${s.draftSku.widthMm}x${s.draftSku.heightMm}_${s.draftSku.layoutType}`;
  },

  getCalibrationForSpec: (specKey) => {
    const { profiles } = get();
    const exact = profiles.find((p) => p.spec_key === specKey);
    if (exact) return exact;
    if (specKey.endsWith("_double")) return profiles.find((p) => p.spec_key === "50x30_double");
    return profiles.find((p) => p.spec_key === "100x100_single");
  },

  setLastPrintedSpec: async (specKey) => {
    const res = await api.updateSpecState(specKey);
    set({ lastPrintedSpec: res.last_printed_spec });
  },

  toggleQuickSpecSwitch: async () => {
    const s = get();
    const target = s.getExpectedSpecKey();
    const skuSpec = `${s.draftSku.widthMm}x${s.draftSku.heightMm}_${s.draftSku.layoutType}`;
    const next = s.lastPrintedSpec !== target ? target : target === "100x100_single" ? skuSpec : "100x100_single";
    await get().setLastPrintedSpec(next);
    notifications.show({ title: "纸卷记录已更新", message: `当前登记纸卷：${next}`, color: "blue" });
  },

  recomputePairing: async () => {
    const s = get();
    const allFba = s.fbaFiles.flatMap((f) => f.boxes);
    const allCar = s.carrierFiles.flatMap((f) => f.items);
    if (allFba.length === 0 && allCar.length === 0) {
      set({ pairing: EMPTY_PAIRING, activeGroupId: null, activeBoxIndex: 1 });
      return;
    }
    const res = await api.pairBoxes({
      fba_boxes: allFba,
      carrier_boxes: allCar,
      manual_assignments: s.manualAssignments,
      work_mode: s.workMode,
      order_mode: s.orderMode,
      default_copies: s.defaultCopies,
      box_copies: s.boxCopies,
      selected_keys: s.selectedBoxKeys,
      force_unlocked: s.forceUnlocked,
      active_shipment_id: s.activeGroupId,
    });
    const latest = get();
    if (s.activeGroupId && latest.activeGroupId && s.activeGroupId !== latest.activeGroupId) {
      return;
    }
    const nextActiveId =
      res.groups.find((g) => g.shipment_id === latest.activeGroupId)?.shipment_id ?? res.active_shipment_id;
    const activeGroup = res.groups.find((g) => g.shipment_id === nextActiveId);
    const firstBoxIdx = activeGroup?.pairs[0]?.box_index ?? 1;
    const hasCurBox = activeGroup?.pairs.some((p) => p.box_index === latest.activeBoxIndex);
    set({
      pairing: res,
      activeGroupId: nextActiveId,
      activeBoxIndex: hasCurBox ? latest.activeBoxIndex : firstBoxIdx,
    });
  },

  uploadFbaFiles: async (files) => {
    if (!files.length) return;
    set({ boxBusy: true });
    try {
      const opts = get().redactionOptions;
      const uploaded: UploadedFbaFile[] = [];
      for (const f of files) {
        uploaded.push(await api.processFbaFile(f, opts));
      }
      set((state) => ({
        fbaFiles: [
          ...state.fbaFiles.filter((old) => !uploaded.some((u) => u.shipment_id && u.shipment_id === old.shipment_id)),
          ...uploaded,
        ],
        activeGroupId: uploaded[0].shipment_id || state.activeGroupId,
      }));
      await get().recomputePairing();
      notifications.show({
        title: "外箱标处理完成",
        message: `已物理擦除敏感字段并居中落版 ${uploaded.reduce((a, b) => a + b.page_count, 0)} 箱`,
        color: "green",
      });
    } catch (err) {
      notifications.show({ title: "外箱 PDF 处理失败", message: (err as Error).message, color: "red" });
    } finally {
      set({ boxBusy: false });
    }
  },

  uploadCarrierFiles: async (files) => {
    if (!files.length) return;
    set({ boxBusy: true });
    try {
      const uploaded: UploadedCarrierFile[] = [];
      for (const f of files) {
        uploaded.push(await api.processCarrierFile(f));
      }
      set((state) => ({
        carrierFiles: [
          ...state.carrierFiles.filter((old) => !uploaded.some((u) => u.shipment_id && u.shipment_id === old.shipment_id)),
          ...uploaded,
        ],
      }));
      await get().recomputePairing();
      notifications.show({
        title: "货代箱唛导入成功",
        message: `已按 FBA 编号自动归类与 98×98mm 裁切`,
        color: "green",
      });
    } catch (err) {
      notifications.show({ title: "货代箱唛处理失败", message: (err as Error).message, color: "red" });
    } finally {
      set({ boxBusy: false });
    }
  },

  removeFbaFile: async (fileId) => {
    set((s) => ({ fbaFiles: s.fbaFiles.filter((f) => f.file_id !== fileId) }));
    await get().recomputePairing();
  },

  removeCarrierFile: async (fileId) => {
    set((s) => {
      const nextManual = { ...s.manualAssignments };
      delete nextManual[fileId];
      return { carrierFiles: s.carrierFiles.filter((f) => f.file_id !== fileId), manualAssignments: nextManual };
    });
    await get().recomputePairing();
  },

  setManualAssignment: async (carrierFileId, shipmentId) => {
    set((s) => {
      const next = { ...s.manualAssignments };
      if (!shipmentId) delete next[carrierFileId];
      else next[carrierFileId] = shipmentId;
      return { manualAssignments: next };
    });
    await get().recomputePairing();
  },

  updateRedactionOption: async (key, val) => {
    set((s) => ({ redactionOptions: { ...s.redactionOptions, [key]: val } }));
    const curFiles = get().fbaFiles;
    if (!curFiles.some((f) => f.rawFile)) return;
    set({ boxBusy: true });
    try {
      const opts = get().redactionOptions;
      const refreshed: UploadedFbaFile[] = [];
      for (const f of curFiles) {
        if (f.rawFile) refreshed.push(await api.processFbaFile(f.rawFile, opts));
        else refreshed.push(f);
      }
      set({ fbaFiles: refreshed });
      await get().recomputePairing();
    } finally {
      set({ boxBusy: false });
    }
  },

  setWorkMode: async (mode) => {
    set({ workMode: mode });
    await get().recomputePairing();
  },

  setOrderMode: async (mode) => {
    set({ orderMode: mode });
    await get().recomputePairing();
  },

  setStageMode: (mode) => set({ stageMode: mode }),
  setShowSafeFrame: (v) => set({ showSafeFrame: v }),

  setDefaultCopies: async (n) => {
    const val = Math.max(1, Math.min(20, n));
    set({ defaultCopies: val, boxCopies: {} });
    await get().recomputePairing();
  },

  setSingleBoxCopies: async (shipmentId, boxIdx, copies) => {
    const key = `${shipmentId}:${boxIdx}`;
    set((s) => ({ boxCopies: { ...s.boxCopies, [key]: Math.max(1, Math.min(20, copies)) } }));
    await get().recomputePairing();
  },

  toggleSingleBoxSelected: async (shipmentId, boxIdx, selected) => {
    const key = `${shipmentId}:${boxIdx}`;
    set((s) => ({ selectedBoxKeys: { ...s.selectedBoxKeys, [key]: selected } }));
    await get().recomputePairing();
  },

  setActiveGroupId: (sid) => {
    const g = get().pairing.groups.find((x) => x.shipment_id === sid);
    set({ activeGroupId: sid, activeBoxIndex: g?.pairs[0]?.box_index ?? 1 });
    void get().recomputePairing();
  },

  setActiveBoxIndex: (idx) => set({ activeBoxIndex: idx }),

  loadFictionalDemo: async (scenario) => {
    if (scenario === "clear") {
      get().clearBoxWorkspace();
      return;
    }
    set({ boxBusy: true, fbaFiles: [], carrierFiles: [], manualAssignments: {} });
    try {
      const f1 = createFictionalFbaDemoFile("FBA00DEMO01", "DMO1", 2);
      const f2 = createFictionalFbaDemoFile("FBA00DEMO02", "DMO2", 2);
      const c1 = createFictionalCarrierDemoFile("FBA00DEMO01", "DMO1", 2);
      const c2 =
        scenario === "unassigned"
          ? createFictionalCarrierDemoFile(null, "DMO1", 2)
          : createFictionalCarrierDemoFile("FBA00DEMO02", "DMO2", 2);

      const opts = get().redactionOptions;
      const [fbaRes1, fbaRes2, carRes1, carRes2] = await Promise.all([
        api.processFbaFile(f1, opts),
        api.processFbaFile(f2, opts),
        api.processCarrierFile(c1),
        api.processCarrierFile(c2),
      ]);
      set({
        fbaFiles: scenario === "unassigned" ? [fbaRes1] : [fbaRes1, fbaRes2],
        carrierFiles: scenario === "unassigned" ? [carRes2] : [carRes1, carRes2],
        activeGroupId: "FBA00DEMO01",
      });
      await get().recomputePairing();
      notifications.show({
        title: "已加载虚构演示文件",
        message: "全部演示 PDF 由前端即时合成并通过后端真实 PyMuPDF 脱敏配对",
        color: "blue",
      });
    } finally {
      set({ boxBusy: false });
    }
  },

  clearBoxWorkspace: () =>
    set({
      fbaFiles: [],
      carrierFiles: [],
      manualAssignments: {},
      pairing: EMPTY_PAIRING,
      activeGroupId: null,
      activeBoxIndex: 1,
      boxOverlayElements: [],
    }),

  setEditorMode: (mode) => set({ editorMode: mode, selectedElementId: null, historyPast: [], historyFuture: [], editorSim203: false }),
  selectElement: (id) => set({ selectedElementId: id }),

  pushHistory: () => {
    const s = get();
    const cur = s.editorMode === "sku_50x30" ? s.draftSku.elements : s.boxOverlayElements;
    const snap = cur.map((e) => ({ ...e }));
    const nextPast = [...s.historyPast.slice(-39), snap];
    set({ historyPast: nextPast, historyFuture: [] });
  },

  undo: () => {
    const s = get();
    if (!s.historyPast.length) return;
    const cur = s.editorMode === "sku_50x30" ? s.draftSku.elements : s.boxOverlayElements;
    const prev = s.historyPast[s.historyPast.length - 1];
    const nextPast = s.historyPast.slice(0, -1);
    const nextFuture = [cur.map((e) => ({ ...e })), ...s.historyFuture];
    const keptSel = s.selectedElementId && prev.some((e) => e.id === s.selectedElementId) ? s.selectedElementId : null;
    if (s.editorMode === "sku_50x30") {
      const bc = prev.find((e) => e.type === "barcode1d");
      set({
        draftSku: { ...s.draftSku, fnsku: bc?.code || s.draftSku.fnsku, elements: prev },
        historyPast: nextPast,
        historyFuture: nextFuture,
        selectedElementId: keptSel,
      });
    } else {
      set({ boxOverlayElements: prev, historyPast: nextPast, historyFuture: nextFuture, selectedElementId: keptSel });
    }
  },

  redo: () => {
    const s = get();
    if (!s.historyFuture.length) return;
    const cur = s.editorMode === "sku_50x30" ? s.draftSku.elements : s.boxOverlayElements;
    const nxt = s.historyFuture[0];
    const nextFuture = s.historyFuture.slice(1);
    const nextPast = [...s.historyPast, cur.map((e) => ({ ...e }))];
    const keptSel = s.selectedElementId && nxt.some((e) => e.id === s.selectedElementId) ? s.selectedElementId : null;
    if (s.editorMode === "sku_50x30") {
      const bc = nxt.find((e) => e.type === "barcode1d");
      set({
        draftSku: { ...s.draftSku, fnsku: bc?.code || s.draftSku.fnsku, elements: nxt },
        historyPast: nextPast,
        historyFuture: nextFuture,
        selectedElementId: keptSel,
      });
    } else {
      set({ boxOverlayElements: nxt, historyPast: nextPast, historyFuture: nextFuture, selectedElementId: keptSel });
    }
  },

  moveElementLayer: (id, dir) => {
    get().updateActiveElements((arr) => {
      const idx = arr.findIndex((e) => e.id === id);
      if (idx < 0) return arr;
      const target = dir === "up" ? idx + 1 : idx - 1;
      if (target < 0 || target >= arr.length) return arr;
      const next = [...arr];
      const [item] = next.splice(idx, 1);
      next.splice(target, 0, item);
      return next;
    }, true);
  },

  clearBoxOverlays: () => {
    const cur = get().boxOverlayElements;
    if (!cur.length) return;
    get().pushHistory();
    set({ boxOverlayElements: [], selectedElementId: null });
  },

  setZoom: (z) => set({ zoom: z }),
  setSnapGrid: (v) => set({ snapGrid: v }),
  setShowGrid: (v) => set({ showGrid: v }),

  setEditorSim203: async (v) => {
    set({ editorSim203: v });
    if (!v) return;
    const s = get();
    const specKey =
      s.editorMode === "sku_50x30" ? `${s.draftSku.widthMm}x${s.draftSku.heightMm}_${s.draftSku.layoutType}` : "100x100_single";
    const prof = s.getCalibrationForSpec(specKey);
    const res = await api.renderFnskuPreview({
      elements: s.editorMode === "sku_50x30" ? s.draftSku.elements : s.boxOverlayElements,
      widthMm: s.editorMode === "sku_50x30" ? s.draftSku.widthMm : 100,
      heightMm: s.editorMode === "sku_50x30" ? s.draftSku.heightMm : 100,
      layoutType: s.editorMode === "sku_50x30" ? s.draftSku.layoutType : "single",
      colGapMm: prof?.col_gap_mm ?? s.colGapMm,
      offsetXMm: prof?.offset_x_mm ?? 0,
      offsetYMm: prof?.offset_y_mm ?? 0,
      qty: s.editorMode === "sku_50x30" && s.draftSku.layoutType === "double" ? 2 : 1,
      dpi: prof?.dpi ?? 203,
    });
    set({ editorSim203B64: res.preview_203dpi_b64 });
  },

  setFnskuQty: (q) => set({ fnskuQty: Math.max(1, Math.min(9999, q || 1)) }),

  updateActiveElements: (updater, recordHistory = false) => {
    if (recordHistory) get().pushHistory();
    const s = get();
    if (s.editorMode === "sku_50x30") {
      const nextEls = updater(s.draftSku.elements);
      const bc = nextEls.find((e) => e.type === "barcode1d");
      set({
        draftSku: {
          ...s.draftSku,
          fnsku: bc?.code || s.draftSku.fnsku,
          elements: nextEls,
        },
      });
    } else {
      set({ boxOverlayElements: updater(s.boxOverlayElements) });
    }
  },

  updateDraftMeta: (patch) => set((s) => ({ draftSku: { ...s.draftSku, ...patch } })),

  selectTemplate: (tpl) =>
    set({
      editorMode: "sku_50x30",
      draftSku: { ...tpl, elements: tpl.elements.map((e) => ({ ...e })) },
      fnskuQty: tpl.defaultQty || 60,
      selectedElementId: null,
      historyPast: [],
      historyFuture: [],
      editorSim203: false,
    }),

  createNewTemplate: ({ sku, fnsku, widthMm, heightMm, layoutType }) => {
    const cleanSku = sku.trim() || "NEW-SKU-01";
    const cleanFnsku = fnsku.trim() || "X000NEW001";
    const newTpl: SkuTemplate = {
      id: `draft_${Date.now()}`,
      sku: cleanSku,
      fnsku: cleanFnsku,
      title_raw: `New - ${cleanSku}`,
      title_clean: `New - ${cleanSku}`,
      widthMm,
      heightMm,
      layoutType,
      elements: createDefaultElementsForSpec(widthMm, heightMm, cleanFnsku, `New - ${cleanSku}`),
      defaultQty: 60,
      updated_at: "",
    };
    set({
      editorMode: "sku_50x30",
      draftSku: newTpl,
      selectedElementId: null,
      historyPast: [],
      historyFuture: [],
      editorSim203: false,
    });
    notifications.show({ title: "已新建空白标签", message: `${cleanSku} (${widthMm}×${heightMm}mm)`, color: "blue" });
  },

  saveDraftTemplate: async () => {
    const s = get();
    const saved = await api.saveTemplate({
      id: s.draftSku.id.startsWith("draft_") ? undefined : s.draftSku.id,
      sku: s.draftSku.sku,
      fnsku: s.draftSku.fnsku,
      title_raw: s.draftSku.title_raw || s.draftSku.sku,
      title_clean: s.draftSku.title_clean || s.draftSku.sku,
      widthMm: s.draftSku.widthMm,
      heightMm: s.draftSku.heightMm,
      layoutType: s.draftSku.layoutType,
      elements: s.draftSku.elements,
      defaultQty: s.fnskuQty,
    });
    const list = await api.fetchTemplates();
    set({ draftSku: saved, templates: list });
    notifications.show({ title: "模板已保存到本地库", message: `${saved.sku} (${saved.widthMm}×${saved.heightMm}mm)`, color: "green" });
  },

  removeTemplate: async (id) => {
    await api.deleteTemplate(id);
    const list = await api.fetchTemplates();
    set({ templates: list });
    notifications.show({ title: "已删除模板", message: "已从本地模板库移除", color: "gray" });
  },

  importProductPdf: async (file) => {
    const parsed = await api.parseFnskuPdf(file);
    const s = get();
    const newTpl: SkuTemplate = {
      id: `draft_${Date.now()}`,
      sku: parsed.fnsku,
      fnsku: parsed.fnsku,
      title_raw: parsed.title_raw,
      title_clean: parsed.title_clean,
      widthMm: s.draftSku.widthMm,
      heightMm: s.draftSku.heightMm,
      layoutType: s.draftSku.layoutType,
      elements: createDefaultElementsForSpec(s.draftSku.widthMm, s.draftSku.heightMm, parsed.fnsku, parsed.title_clean),
      defaultQty: s.fnskuQty,
      updated_at: "",
    };
    set({ editorMode: "sku_50x30", draftSku: newTpl, selectedElementId: null, historyPast: [], historyFuture: [] });
    notifications.show({ title: "已解析亚马逊产品标", message: `FNSKU ${parsed.fnsku} · 已自动清洗中文成色`, color: "green" });
  },

  openPrintJob: (job) => set({ printModalOpen: true, pendingPrintJob: job }),
  closePrintModal: () => set({ printModalOpen: false, pendingPrintJob: null }),

  saveProfile: async (prof) => {
    const saved = await api.updateProfile(prof);
    const list = await api.fetchProfiles();
    set({
      profiles: list,
      colGapMm: saved.spec_key === "50x30_double" ? saved.col_gap_mm : get().colGapMm,
    });
    notifications.show({ title: "校准参数已保存", message: `${saved.spec_key} 已写入 SQLite`, color: "green" });
  },

  createProfile: async (prof) => {
    const saved = await api.createCalibrationProfile(prof);
    const list = await api.fetchProfiles();
    set({ profiles: list });
    notifications.show({
      title: "自定义纸卷规格已创建",
      message: `${saved.label_width_mm}×${saved.label_height_mm}mm (${saved.spec_key}) 已添加到校准档`,
      color: "green",
    });
  },

  removeProfile: async (specKey) => {
    await api.deleteCalibrationProfile(specKey);
    const list = await api.fetchProfiles();
    set({ profiles: list });
    notifications.show({
      title: "自定义纸卷规格已删除",
      message: `${specKey} 已从校准档移除`,
      color: "gray",
    });
  },

  refreshPrinters: async () => {
    const printers = await api.fetchPrinters().catch(() => []);
    set({ printers });
  },

  refreshBatches: async () => {
    const batches = await api.fetchBatches();
    set({ batches });
  },

  deleteBatchRecord: async (id) => {
    await api.deleteBatch(id);
    const batches = await api.fetchBatches();
    set({ batches });
    notifications.show({ title: "已删除打印记录", message: "记录及对应 PDF 快照已移除", color: "gray" });
  },
}));
