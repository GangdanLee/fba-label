import { Button, Select, useMantineColorScheme } from "@mantine/core";
import { spotlight } from "@mantine/spotlight";
import * as api from "../api/client";
import classes from "../styles/Studio.module.css";
import { resolveTargetPrinterKey, useWorkbenchStore } from "../store/useWorkbenchStore";

function formatSpecShort(specKey: string): string {
  const m = specKey.match(/^(\d+)x(\d+)_(double|single)$/);
  if (m) return `${m[1]}×${m[2]} ${m[3] === "double" ? "双排" : "单排"}`;
  return specKey === "50x30_double" ? "50×30 双排" : "100×100 单排";
}

export function StudioHeader() {
  const { colorScheme } = useMantineColorScheme();
  const {
    activeTab,
    lastPrintedSpec,
    getExpectedSpecKey,
    getCalibrationForSpec,
    toggleQuickSpecSwitch,
    pairing,
    activeGroupId,
    editorMode,
    draftSku,
    boxOverlayElements,
    batches,
    printers,
    loadFictionalDemo,
    openPrintJob,
    fbaFiles,
    carrierFiles,
    orderMode,
    workMode,
    defaultCopies,
    fbaCopies,
    carrierCopies,
    fnskuQty,
    colGapMm,
  } = useWorkbenchStore();

  const expectedSpec = getExpectedSpecKey();
  const checkMismatch = activeTab === "box" || activeTab === "editor";
  const sameDevice =
    resolveTargetPrinterKey(getCalibrationForSpec(lastPrintedSpec), printers) ===
    resolveTargetPrinterKey(getCalibrationForSpec(expectedSpec), printers);
  const isMismatch = checkMismatch && lastPrintedSpec !== expectedSpec && sameDevice;

  let pageTitle = "外箱标签配对";
  let crumb = "100×100mm 单排 · 等待导入本地 PDF";
  if (activeTab === "box") {
    if (activeGroupId) {
      crumb = `100×100mm · 当前货件 ${activeGroupId} (${pairing.groups.length}组)`;
    } else if (pairing.unassigned_carriers.length > 0) {
      crumb = `有 ${pairing.unassigned_carriers.length} 份无编号箱唛待归属`;
    }
  } else if (activeTab === "editor") {
    pageTitle = "标签设计";
    crumb =
      editorMode === "sku_50x30"
        ? `${draftSku.widthMm}×${draftSku.heightMm}mm ${draftSku.layoutType === "double" ? "双排" : "单排"} · ${draftSku.sku}`
        : "100×100mm 外箱调整";
  } else if (activeTab === "batches") {
    pageTitle = "打印记录与补打";
    crumb = `共 ${batches.length} 条记录`;
  } else {
    pageTitle = "打印机设置与校准";
    crumb = "TSPL2 / ZPL II · 203 / 300 dpi · 多机绑定";
  }

  const handleHeaderPrint = () => {
    if (activeTab === "box") {
      if (!pairing.can_print || !pairing.active_shipment_id) return;
      const g = pairing.groups.find((x) => x.shipment_id === pairing.active_shipment_id);
      const comboLabel =
        workMode === "fba_only"
          ? `仅FBA×${fbaCopies}`
          : workMode === "carrier_only"
            ? `仅箱唛×${carrierCopies}`
            : `FBA×${fbaCopies}+唛×${carrierCopies}`;
      openPrintJob({
        title: `打印外箱任务 · ${pairing.active_shipment_id}`,
        summaryDesc: `${pairing.active_shipment_id}（${comboLabel}，共 ${pairing.total_sheets} 张）`,
        specKey: "100x100_single",
        batchType: workMode === "fba_only" ? "box_fba_only" : workMode === "carrier_only" ? "box_carrier_only" : "box_paired",
        shipmentId: pairing.active_shipment_id,
        warehouseCode: g?.warehouse_code || "-",
        totalUnitsOrBoxes: g?.pairs.filter((p) => p.selected).length || 1,
        copiesPerBox: defaultCopies,
        orderMode,
        totalSheets: pairing.total_sheets,
        sourceFiles: [...fbaFiles.map((f) => f.file_name), ...carrierFiles.map((f) => f.file_name)],
        getPdfB64: async () => {
          const fbaMap: Record<string, string> = {};
          const carMap: Record<string, string> = {};
          fbaFiles.forEach((f) => (fbaMap[f.file_id] = f.pdf_b64));
          carrierFiles.forEach((f) => (carMap[f.file_id] = f.pdf_b64));
          const merged = await api.exportMergedBoxPdf({
            fba_pdfs_b64: fbaMap,
            carrier_pdfs_b64: carMap,
            queue: pairing.queue,
            overlay_elements: boxOverlayElements,
          });
          return merged.pdf_b64;
        },
      });
    } else if (activeTab === "editor" && editorMode === "sku_50x30") {
      const specKey = `${draftSku.widthMm}x${draftSku.heightMm}_${draftSku.layoutType}`;
      const cal = getCalibrationForSpec(specKey);
      openPrintJob({
        title: `打印产品标签 · ${draftSku.sku}`,
        summaryDesc: `${draftSku.sku} · ${fnskuQty} 张 (${formatSpecShort(specKey)})`,
        specKey,
        batchType: "fnsku",
        shipmentId: draftSku.sku,
        warehouseCode: "-",
        totalUnitsOrBoxes: fnskuQty,
        copiesPerBox: 1,
        orderMode: draftSku.layoutType,
        totalSheets: draftSku.layoutType === "double" ? Math.ceil(fnskuQty / 2) : fnskuQty,
        sourceFiles: [draftSku.sku],
        getPdfB64: async () => {
          const rendered = await api.renderFnskuPreview({
            elements: draftSku.elements,
            widthMm: draftSku.widthMm,
            heightMm: draftSku.heightMm,
            layoutType: draftSku.layoutType,
            colGapMm: cal?.col_gap_mm ?? colGapMm,
            offsetXMm: cal?.offset_x_mm ?? 0,
            offsetYMm: cal?.offset_y_mm ?? 0,
            qty: fnskuQty,
            dpi: cal?.dpi ?? 203,
          });
          return rendered.pdf_b64;
        },
      });
    }
  };

  const showPrintBtn = activeTab === "box" || (activeTab === "editor" && editorMode === "sku_50x30");
  const printDisabled = activeTab === "box" && (!pairing.can_print || pairing.total_sheets === 0);

  return (
    <header className={classes.studioHeader}>
      <div className={classes.hdrLeft}>
        <div className={classes.hdrTitle}>{pageTitle}</div>
        <div className={classes.hdrCrumb}>{crumb}</div>
      </div>

      <div className={classes.hdrRight}>
        {activeTab === "box" && (
          <Select
            aria-label="加载虚构演示或清空工作区"
            size="xs"
            w={138}
            placeholder="演示开关"
            data={[
              { value: "clear", label: "空白工作区" },
              { value: "dual_mix", label: "示例：双票配对" },
              { value: "unassigned", label: "示例：无编号箱唛" },
            ]}
            onChange={(val) => {
              if (val === "clear" || val === "dual_mix" || val === "unassigned") {
                void loadFictionalDemo(val);
              }
            }}
          />
        )}

        <Button
          variant="default"
          size="xs"
          onClick={() => spotlight.open()}
          aria-label="打开快捷操作面板"
          title="快捷操作 (Cmd/Ctrl + K)"
          styles={{ root: { fontFamily: "var(--mono)" } }}
        >
          ⌘K
        </Button>

        <button
          type="button"
          className={`${classes.specPill} ${isMismatch ? classes.specPillMismatch : ""}`}
          onClick={() => void toggleQuickSpecSwitch()}
          title={
            isMismatch
              ? `当前页面为 ${formatSpecShort(expectedSpec)}，与已装纸卷不同；点击登记换纸完成`
              : "当前已装纸卷与页面规格一致；点击可切换登记"
          }
        >
          <span
            style={{
              width: 7,
              height: 7,
              borderRadius: "50%",
              background: checkMismatch ? (isMismatch ? "#d97706" : "#16a34a") : "#64748b",
              flexShrink: 0,
            }}
            aria-hidden="true"
          />
          <span>
            纸卷：<strong>{formatSpecShort(lastPrintedSpec)}</strong>
          </span>
        </button>

        {showPrintBtn && (
          <Button size="xs" color={colorScheme === "dark" ? "blue" : "dark"} disabled={printDisabled} onClick={handleHeaderPrint}>
            {activeTab === "box" ? `打印外箱 (${pairing.total_sheets}张)` : "打印产品标签"}
          </Button>
        )}
      </div>
    </header>
  );
}
