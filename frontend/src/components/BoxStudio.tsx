import { useRef, useState, type DragEvent } from "react";
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Checkbox,
  Divider,
  Group,
  NumberInput,
  Paper,
  Radio,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { AlertTriangle, ArrowLeftRight, Pencil, RotateCcw, SlidersHorizontal, Upload, X } from "lucide-react";
import * as api from "../api/client";
import classes from "../styles/Studio.module.css";
import { useWorkbenchStore } from "../store/useWorkbenchStore";
import { CarrierRulesModal } from "./CarrierRulesModal";

export function BoxStudio() {
  const {
    fbaFiles,
    carrierFiles,
    manualAssignments,
    groupBy,
    insertSeparatorPages,
    workMode,
    orderMode,
    stageMode,
    showSafeFrame,
    defaultCopies,
    fbaCopies,
    carrierCopies,
    boxFbaCopies,
    boxCarrierCopies,
    prefsSavedAt,
    redactionOptions,
    pairing,
    forceUnlocked,
    activeGroupId,
    activeBoxIndex,
    activeBoxKey,
    boxBusy,
    boxOverlayElements,
    uploadFbaFiles,
    uploadCarrierFiles,
    removeFbaFile,
    removeCarrierFile,
    clearBoxWorkspace,
    setManualAssignment,
    updateRedactionOption,
    setGroupBy,
    setInsertSeparatorPages,
    setWorkMode,
    setOrderMode,
    setStageMode,
    setShowSafeFrame,
    setCopyCombo,
    setSingleBoxPairCopies,
    resetBoxPairCustomCopies,
    toggleSingleBoxSelected,
    selectAllBoxes,
    setActiveGroupId,
    setActiveBoxIndex,
    loadFictionalDemo,
    openPrintJob,
    setActiveTab,
    setEditorMode,
  } = useWorkbenchStore();

  const fbaInputRef = useRef<HTMLInputElement>(null);
  const carInputRef = useRef<HTMLInputElement>(null);
  const [splitPct, setSplitPct] = useState(50);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [dragZone, setDragZone] = useState<"fba" | "carrier" | null>(null);

  const handleDropPdf = (zone: "fba" | "carrier", e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragZone(null);
    const allFiles = Array.from(e.dataTransfer?.files || []);
    const pdfs = allFiles.filter(
      (f) => f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf"),
    );
    if (!pdfs.length) {
      if (allFiles.length > 0) {
        notifications.show({
          title: "文件格式不支持",
          message: "请拖入 .pdf 格式的外箱标签或货代箱唛文件",
          color: "orange",
        });
      }
      return;
    }
    if (zone === "fba") void uploadFbaFiles(pdfs);
    else void uploadCarrierFiles(pdfs);
  };

  const activeGroup = pairing.groups.find((g) => g.shipment_id === activeGroupId) || pairing.groups[0] || null;
  const activePair =
    activeGroup?.pairs.find(
      (p) => (p.pair_key || `${p.shipment_id || activeGroup.shipment_id}:${p.box_index}`) === activeBoxKey,
    ) ||
    activeGroup?.pairs.find((p) => p.box_index === activeBoxIndex) ||
    activeGroup?.pairs[0] ||
    null;
  const knownShipments = Array.from(
    new Set(
      [
        ...fbaFiles.map((f) => f.shipment_id),
        ...(pairing.group_by === "sku"
          ? pairing.groups.flatMap((g) => g.shipment_ids || [])
          : pairing.groups.map((g) => g.shipment_id)),
      ].filter((x): x is string => Boolean(x && !x.startsWith("__"))),
    ),
  );
  const groupIds = knownShipments.map((sid) => ({ value: sid, label: `归属到 ${sid}` }));

  const handleExportMerged = async () => {
    if (!pairing.can_print || pairing.queue.length === 0) return;
    const fbaMap: Record<string, string> = {};
    const carMap: Record<string, string> = {};
    fbaFiles.forEach((f) => (fbaMap[f.file_id] = f.pdf_b64));
    carrierFiles.forEach((f) => (carMap[f.file_id] = f.pdf_b64));
    const res = await api.exportMergedBoxPdf({
      fba_pdfs_b64: fbaMap,
      carrier_pdfs_b64: carMap,
      queue: pairing.queue,
      overlay_elements: boxOverlayElements,
    });
    const safeName = (activeGroup?.display_label || activeGroup?.shipment_id || "FBA_Box").replace(/[\\/:*?"<>|\s]+/g, "_");
    api.downloadBase64Pdf(res.pdf_b64, `${safeName}_${res.page_count}pages.pdf`);
    notifications.show({ title: "已导出合并 PDF", message: `共 ${res.page_count} 页 (100×100mm)`, color: "green" });
  };

  const handleExportManifestCsv = async () => {
    if (!pairing.can_print || pairing.queue.length === 0) return;
    const title = activeGroup?.display_label || activeGroup?.shipment_id || "FBA_Queue";
    const res = await api.exportBoxManifestCsv({ queue: pairing.queue, title });
    api.downloadBase64File(res.csv_b64, res.filename, "text/csv;charset=utf-8");
    notifications.show({ title: "已导出核对明细 CSV", message: `共 ${res.row_count} 行出纸记录`, color: "green" });
  };

  const handleExportSkuZip = async () => {
    if (!pairing.groups.length) return;
    const fbaMap: Record<string, string> = {};
    const carMap: Record<string, string> = {};
    fbaFiles.forEach((f) => (fbaMap[f.file_id] = f.pdf_b64));
    carrierFiles.forEach((f) => (carMap[f.file_id] = f.pdf_b64));
    try {
      const res = await api.exportBoxSkuZip({
        fba_pdfs_b64: fbaMap,
        carrier_pdfs_b64: carMap,
        groups: pairing.groups,
        group_by: groupBy,
        work_mode: workMode,
        order_mode: orderMode,
        insert_separator_pages: insertSeparatorPages,
        force_unlocked: forceUnlocked,
        overlay_elements: boxOverlayElements,
      });
      api.downloadBase64File(res.zip_b64, res.filename, "application/zip");
      const byShipment = res.group_by === "shipment";
      const skippedCount = res.skipped_groups?.length || 0;
      const skipSuffix = skippedCount > 0 ? `；已安全跳过 ${skippedCount} 个未配平组 (${res.skipped_groups?.join(", ")})` : "";
      notifications.show({
        title: byShipment ? "已导出按货件拆分 ZIP 包" : "已导出按 SKU 拆分 ZIP 包",
        message: `包含 ${res.file_count} 份独立 PDF（共 ${res.total_pages} 页）与核对明细 CSV${skipSuffix}`,
        color: skippedCount > 0 ? "teal" : "green",
      });
    } catch (err) {
      notifications.show({ title: "打包 ZIP 失败", message: (err as Error).message, color: "red" });
    }
  };

  const handleOpenPrint = () => {
    if (!pairing.can_print || !activeGroup) return;
    const groupTitle = activeGroup.display_label || activeGroup.shipment_id;
    const comboDesc =
      workMode === "fba_only"
        ? `仅FBA×${fbaCopies}`
        : workMode === "carrier_only"
          ? `仅箱唛×${carrierCopies}`
          : `FBA×${fbaCopies}+唛×${carrierCopies}`;
    openPrintJob({
      title: `打印外箱任务 · ${groupTitle}`,
      summaryDesc: `${groupTitle}（${comboDesc}，共 ${pairing.total_sheets} 张）`,
      specKey: "100x100_single",
      batchType: workMode === "fba_only" ? "box_fba_only" : workMode === "carrier_only" ? "box_carrier_only" : "box_paired",
      shipmentId: groupTitle,
      warehouseCode: activeGroup.warehouse_code || "-",
      totalUnitsOrBoxes: activeGroup.pairs.filter((p) => p.selected).length,
      copiesPerBox: Math.max(1, defaultCopies, fbaCopies, carrierCopies),
      orderMode,
      totalSheets: pairing.total_sheets,
      sourceFiles: [...fbaFiles.map((f) => f.file_name), ...carrierFiles.map((f) => f.file_name)],
      getPdfB64: async () => {
        const fbaMap: Record<string, string> = {};
        const carMap: Record<string, string> = {};
        fbaFiles.forEach((f) => (fbaMap[f.file_id] = f.pdf_b64));
        carrierFiles.forEach((f) => (carMap[f.file_id] = f.pdf_b64));
        const res = await api.exportMergedBoxPdf({
          fba_pdfs_b64: fbaMap,
          carrier_pdfs_b64: carMap,
          queue: pairing.queue,
          overlay_elements: boxOverlayElements,
        });
        return res.pdf_b64;
      },
    });
  };

  return (
    <div className={classes.threePaneStudio}>
      {/* 左栏：双通道 PDF 导入、多票配对组、箱号队列 */}
      <div className={classes.leftPanel}>
        <div className={classes.paneSec}>
          <div className={classes.secTitle}>
            <span>① 亚马逊外箱 PDF</span>
            <Group gap={4}>
              {(fbaFiles.length > 0 || carrierFiles.length > 0) && (
                <Button size="compact-xs" variant="subtle" color="gray" onClick={clearBoxWorkspace}>
                  清空全部
                </Button>
              )}
              <Badge size="xs" variant="light" color="blue">
                {fbaFiles.length} 份
              </Badge>
            </Group>
          </div>
          <div
            className={classes.importSlot}
            role="button"
            tabIndex={0}
            style={dragZone === "fba" ? { borderColor: "var(--accent)", background: "var(--accent-soft)" } : undefined}
            onClick={() => fbaInputRef.current?.click()}
            onKeyDown={(e) => e.key === "Enter" && fbaInputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              e.stopPropagation();
              if (dragZone !== "fba") setDragZone("fba");
            }}
            onDragLeave={() => setDragZone((z) => (z === "fba" ? null : z))}
            onDrop={(e) => handleDropPdf("fba", e)}
          >
            <Text size="xs" fw={600}>
              点击选取或拖入外箱标 PDF
            </Text>
            <Text size="xs" c="dimmed">
              自动物理擦除隐私并裁切至 98×98mm
            </Text>
            <input
              ref={fbaInputRef}
              type="file"
              accept=".pdf,application/pdf"
              multiple
              style={{ display: "none" }}
              onChange={(e) => {
                if (e.target.files) void uploadFbaFiles(Array.from(e.target.files));
                e.target.value = "";
              }}
            />
          </div>
          <Stack gap={4}>
            {fbaFiles.map((f) => (
              <Paper key={f.file_id} withBorder p={6} radius="sm">
                <Group justify="space-between" wrap="nowrap" gap={4}>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <Text size="xs" fw={600} truncate>
                      {f.file_name}
                    </Text>
                    <Group gap={4} mt={2}>
                      <Badge size="xs" variant="light" color="blue">
                        {f.shipment_id || "未识别号"}
                      </Badge>
                      <Badge size="xs" variant="light" color="green">
                        {f.page_count} 箱 · 98×98
                      </Badge>
                    </Group>
                  </div>
                  <ActionIcon
                    size="xs"
                    variant="subtle"
                    color="red"
                    aria-label={`移除文件 ${f.file_name}`}
                    onClick={() => void removeFbaFile(f.file_id)}
                  >
                    <X size={13} />
                  </ActionIcon>
                </Group>
              </Paper>
            ))}
          </Stack>
        </div>

        <div className={classes.paneSec}>
          <div className={classes.secTitle}>
            <span>② 货代箱唛 PDF</span>
            <Group gap={6} wrap="nowrap">
              <Button
                size="compact-xs"
                variant="subtle"
                leftSection={<SlidersHorizontal size={12} />}
                onClick={() => setRulesOpen(true)}
              >
                解析规则
              </Button>
              <Badge size="xs" variant="light" color="green">
                {carrierFiles.length} 份
              </Badge>
            </Group>
          </div>
          <div
            className={classes.importSlot}
            role="button"
            tabIndex={0}
            style={dragZone === "carrier" ? { borderColor: "var(--accent)", background: "var(--accent-soft)" } : undefined}
            onClick={() => carInputRef.current?.click()}
            onKeyDown={(e) => e.key === "Enter" && carInputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              e.stopPropagation();
              if (dragZone !== "carrier") setDragZone("carrier");
            }}
            onDragLeave={() => setDragZone((z) => (z === "carrier" ? null : z))}
            onDrop={(e) => handleDropPdf("carrier", e)}
          >
            <Text size="xs" fw={600}>
              点击选取或拖入货代箱唛 PDF
            </Text>
            <Text size="xs" c="dimmed">
              按 FBA 编号自动与外箱标逐箱配对
            </Text>
            <input
              ref={carInputRef}
              type="file"
              accept=".pdf,application/pdf"
              multiple
              style={{ display: "none" }}
              onChange={(e) => {
                if (e.target.files) void uploadCarrierFiles(Array.from(e.target.files));
                e.target.value = "";
              }}
            />
          </div>
          <Stack gap={4}>
            {carrierFiles.map((f) => {
              const unassigned = !f.shipment_id;
              return (
                <Paper
                  key={f.file_id}
                  withBorder
                  p={6}
                  radius="sm"
                  style={unassigned ? { borderColor: "var(--warning)", background: "var(--warning-soft)" } : undefined}
                >
                  <Group justify="space-between" wrap="nowrap" gap={4}>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <Text size="xs" fw={600} truncate>
                        {f.file_name}
                      </Text>
                      <Group gap={4} mt={2}>
                        <Badge size="xs" variant="light" color={unassigned ? "orange" : "green"}>
                          {f.shipment_id || manualAssignments[f.file_id] || "未带 FBA 编号"}
                        </Badge>
                        <Badge size="xs" variant="light" color="gray">
                          {f.page_count} 页
                        </Badge>
                      </Group>
                    </div>
                    <ActionIcon
                      size="xs"
                      variant="subtle"
                      color="red"
                      aria-label={`移除文件 ${f.file_name}`}
                      onClick={() => void removeCarrierFile(f.file_id)}
                    >
                      <X size={13} />
                    </ActionIcon>
                  </Group>
                  {unassigned && (
                    <Select
                      mt={6}
                      size="xs"
                      aria-label={`为 ${f.file_name} 选择归属 FBA 货件`}
                      placeholder={groupIds.length ? "选择归属货件..." : "请先导入亚马逊外箱 PDF"}
                      data={groupIds}
                      value={manualAssignments[f.file_id] || null}
                      onChange={(val) => void setManualAssignment(f.file_id, val || "")}
                    />
                  )}
                </Paper>
              );
            })}
          </Stack>
        </div>

        <div className={classes.paneSec}>
          <div className={classes.secTitle}>
            <span>打印范围与归集维度</span>
          </div>
          <SegmentedControl
            fullWidth
            size="xs"
            mb={6}
            value={groupBy}
            onChange={(val) => void setGroupBy(val as typeof groupBy)}
            data={[
              { value: "shipment", label: "按货件分组" },
              { value: "sku", label: "按 SKU 跨仓" },
            ]}
          />
          <SegmentedControl
            fullWidth
            size="xs"
            mb={8}
            value={workMode}
            onChange={(val) => void setWorkMode(val as typeof workMode)}
            data={[
              { value: "paired", label: "成对配对" },
              { value: "fba_only", label: "仅打外箱" },
              { value: "carrier_only", label: "仅打箱唛" },
            ]}
          />
          <Stack gap={6}>
            {pairing.groups.map((g) => {
              const active = activeGroup?.shipment_id === g.shipment_id;
              const isSkuGrp = g.group_kind === "sku";
              const labelText = g.display_label || g.shipment_id;
              return (
                <Paper
                  key={g.shipment_id}
                  withBorder
                  p={8}
                  radius="sm"
                  style={{
                    cursor: "pointer",
                    borderColor: active ? "var(--accent)" : undefined,
                    background: active ? "var(--accent-soft)" : undefined,
                  }}
                  onClick={() => setActiveGroupId(g.shipment_id)}
                >
                  <Group justify="space-between" mb={2} wrap="nowrap" gap={4}>
                    <Text size="xs" fw={700} ff="var(--mono)" truncate>
                      {labelText}
                    </Text>
                    <Badge size="xs" color={g.status === "matched" ? "green" : "orange"} variant="light" style={{ flexShrink: 0 }}>
                      {g.status === "matched" ? "编号配对一致" : g.status === "missing_carrier" ? "缺箱唛" : g.status === "missing_fba" ? "缺外箱" : "存在差异"}
                    </Badge>
                  </Group>
                  {isSkuGrp ? (
                    <Group gap={4} mt={2} wrap="wrap">
                      {(g.warehouses && g.warehouses.length > 0 ? g.warehouses : ["-"]).map((wh) => (
                        <Badge key={wh} size="xs" variant="dot" color="blue">
                          {wh}
                        </Badge>
                      ))}
                      <Text size="xs" c="dimmed">
                        · {g.pairs.length} 箱 ({g.shipment_ids?.length || 1} 票)
                      </Text>
                    </Group>
                  ) : (
                    <Text size="xs" c="dimmed">
                      仓点 {g.warehouse_code || "-"} · {g.pairs.length} 箱
                    </Text>
                  )}
                </Paper>
              );
            })}
          </Stack>

          {pairing.issues.length > 0 && (
            <Alert mt={8} color="orange" p="xs" icon={<AlertTriangle size={14} />}>
              <Text size="xs">{pairing.issues.join("；")}</Text>
            </Alert>
          )}
        </div>

        {activeGroup && (
          <div style={{ padding: "8px 13px 14px" }}>
            <div className={classes.secTitle}>
              <span>箱号队列</span>
              {activeGroup.pairs.length > 0 && (
                <Button
                  size="compact-xs"
                  variant="subtle"
                  onClick={() => {
                    const allChecked = activeGroup.pairs.every((item) => item.selected);
                    void selectAllBoxes(activeGroup.shipment_id, !allChecked);
                  }}
                >
                  {activeGroup.pairs.every((item) => item.selected) ? "取消全选" : "全选"}
                </Button>
              )}
            </div>
            <Stack gap={6}>
              {activeGroup.pairs.map((p) => {
                const realSid = p.shipment_id || activeGroup.shipment_id;
                const pairKey = p.pair_key || `${realSid}:${p.box_index}`;
                const active = activePair
                  ? (activePair.pair_key || `${activePair.shipment_id || activeGroup.shipment_id}:${activePair.box_index}`) === pairKey
                  : false;
                const isCustom = boxFbaCopies[pairKey] !== undefined || boxCarrierCopies[pairKey] !== undefined;
                const curFba = p.fba_copies ?? fbaCopies;
                const curCar = p.carrier_copies ?? carrierCopies;
                return (
                  <Paper
                    key={pairKey}
                    withBorder
                    p={8}
                    radius="sm"
                    style={{
                      cursor: "pointer",
                      opacity: p.selected ? 1 : 0.55,
                      borderColor: active ? "var(--accent)" : undefined,
                      background: active ? "var(--accent-soft)" : undefined,
                    }}
                    onClick={() => setActiveBoxIndex(p.box_index, pairKey)}
                  >
                    <Group justify="space-between" wrap="nowrap" mb={4}>
                      <Group gap={5} wrap="nowrap">
                        <Checkbox
                          aria-label={`勾选第 ${p.box_index} 箱`}
                          checked={p.selected}
                          onChange={(e) => void toggleSingleBoxSelected(realSid, p.box_index, e.currentTarget.checked)}
                          onClick={(e) => e.stopPropagation()}
                        />
                        <Text size="xs" fw={600} style={{ whiteSpace: "nowrap" }}>
                          第 {p.box_index} 箱
                        </Text>
                        {activeGroup.group_kind === "sku" && (
                          <Badge size="xs" variant="light" color="indigo" title={`货件 ${realSid}`}>
                            {p.warehouse_code || realSid.slice(-5)}
                          </Badge>
                        )}
                        {isCustom && (
                          <Badge size="xs" variant="light" color="orange">
                            自定义
                          </Badge>
                        )}
                      </Group>
                      {isCustom && (
                        <Tooltip label="恢复为全局配比">
                          <ActionIcon
                            size="xs"
                            variant="subtle"
                            color="gray"
                            aria-label={`恢复第 ${p.box_index} 箱默认配比`}
                            onClick={(e) => {
                              e.stopPropagation();
                              void resetBoxPairCustomCopies(realSid, p.box_index);
                            }}
                          >
                            <RotateCcw size={12} />
                          </ActionIcon>
                        </Tooltip>
                      )}
                    </Group>
                    <Group gap={6} grow wrap="nowrap" onClick={(e) => e.stopPropagation()}>
                      <Group gap={4} wrap="nowrap">
                        <Badge size="xs" color="blue" variant="light" style={{ flexShrink: 0 }}>
                          FBA
                        </Badge>
                        <NumberInput
                          aria-label={`第 ${p.box_index} 箱 FBA 张数`}
                          size="xs"
                          min={0}
                          max={20}
                          disabled={workMode === "carrier_only"}
                          value={curFba}
                          onChange={(v) =>
                            void setSingleBoxPairCopies(realSid, p.box_index, Number(v) || 0, curCar)
                          }
                        />
                      </Group>
                      <Group gap={4} wrap="nowrap">
                        <Badge size="xs" color="green" variant="light" style={{ flexShrink: 0 }}>
                          唛
                        </Badge>
                        <NumberInput
                          aria-label={`第 ${p.box_index} 箱箱唛张数`}
                          size="xs"
                          min={0}
                          max={20}
                          disabled={workMode === "fba_only"}
                          value={curCar}
                          onChange={(v) =>
                            void setSingleBoxPairCopies(realSid, p.box_index, curFba, Number(v) || 0)
                          }
                        />
                      </Group>
                    </Group>
                  </Paper>
                );
              })}
            </Stack>
          </div>
        )}
      </div>

      {/* 中栏大舞台 */}
      <div className={classes.centerStage}>
        <div className={classes.stageTopbar}>
          <div className={classes.stageFloatBar}>
            <SegmentedControl
              size="xs"
              value={stageMode}
              onChange={(v) => setStageMode(v as typeof stageMode)}
              data={[
                { value: "dual", label: "双联配对" },
                { value: "compare", label: "原图与处理对比" },
              ]}
            />
            <Checkbox label="显示留白边距" size="xs" checked={showSafeFrame} onChange={(e) => setShowSafeFrame(e.currentTarget.checked)} />
          </div>

          {activePair?.fba_box && workMode !== "carrier_only" && (
            <Group gap={6}>
              {boxOverlayElements.length > 0 && (
                <Badge size="xs" color="blue" variant="light">
                  已叠加 {boxOverlayElements.length} 项
                </Badge>
              )}
              <Button
                size="xs"
                variant="default"
                leftSection={<Pencil size={13} />}
                onClick={() => {
                  setEditorMode("box_100x100");
                  setActiveTab("editor");
                }}
              >
                调整这张标签
              </Button>
            </Group>
          )}
        </div>

        <div className={classes.stageViewport}>
          {!activeGroup ? (
            <Paper withBorder p={36} radius="lg" maw={520} m="auto" ta="center" shadow="sm">
              <Text fw={700} size="md" mb={6}>
                {pairing.unassigned_carriers.length > 0 ? "已有无编号箱唛待归属到货件" : "导入本地外箱标与货代箱唛"}
              </Text>
              <Text size="xs" c="dimmed" mb="lg">
                从左侧导入本地亚马逊外箱标与货代箱唛 PDF，后端 PyMuPDF 自动物理抹除敏感文本、裁切居中至 98×98mm 并按 FBA 编号逐箱配对。
              </Text>
              <Group justify="center" gap="xs">
                <Button size="xs" leftSection={<Upload size={13} />} loading={boxBusy} onClick={() => fbaInputRef.current?.click()}>
                  导入亚马逊外箱 PDF
                </Button>
                <Button size="xs" variant="default" loading={boxBusy} onClick={() => carInputRef.current?.click()}>
                  导入货代箱唛 PDF
                </Button>
                <Button size="xs" variant="subtle" loading={boxBusy} onClick={() => void loadFictionalDemo("dual_mix")}>
                  试用虚构双票示例
                </Button>
              </Group>
            </Paper>
          ) : stageMode === "compare" && activePair?.fba_box && workMode !== "carrier_only" ? (
            <div className={`${classes.dualPaperRow} ${classes.dualPaperRowCompare}`}>
              <div className={classes.compareOrigCard}>
                <div className={classes.compareOrigSheet}>
                  <img src={activePair.fba_box.full_page_b64} alt="原始未裁切整页" />
                </div>
                <div className={classes.paperMeta}>
                  <Badge size="xs" color="orange" variant="light">
                    第1步 · 自动裁切
                  </Badge>
                  <span>识别有效区 → 98×98mm 居中</span>
                </div>
              </div>

              <div style={{ fontSize: 18, fontWeight: 700, color: "var(--accent)", flexShrink: 0 }}>→</div>

              <div className={classes.compareStage}>
                <div
                  className={classes.compareBox}
                  onMouseMove={(e) => {
                    if (e.buttons !== 1) return;
                    const rect = e.currentTarget.getBoundingClientRect();
                    setSplitPct(Math.max(5, Math.min(95, ((e.clientX - rect.left) / rect.width) * 100)));
                  }}
                  onClick={(e) => {
                    const rect = e.currentTarget.getBoundingClientRect();
                    setSplitPct(Math.max(5, Math.min(95, ((e.clientX - rect.left) / rect.width) * 100)));
                  }}
                >
                  <div className={classes.compareLayer}>
                    <img src={activePair.fba_box.raw_preview_b64} alt="处理前原图" />
                    <span className={`${classes.compareTag} ${classes.compareTagRaw}`}>原图（脱敏前）</span>
                  </div>
                  <div className={classes.compareLayer} style={{ clipPath: `inset(0 0 0 ${splitPct}%)` }}>
                    <img src={activePair.fba_box.clean_preview_b64} alt="物理脱敏后标签" />
                    <span className={`${classes.compareTag} ${classes.compareTagClean}`}>处理后（已擦除）</span>
                  </div>
                  {showSafeFrame && <div className={classes.safeGuideBox} />}
                  <div
                    style={{
                      position: "absolute",
                      top: 0,
                      bottom: 0,
                      left: `${splitPct}%`,
                      width: 2,
                      background: "#2563eb",
                      zIndex: 8,
                      pointerEvents: "none",
                    }}
                  />
                </div>
                <div className={classes.paperMeta}>拖动或点击对比物理脱敏前后效果 · {activePair.fba_box.box_id}</div>
              </div>
            </div>
          ) : (
            <div className={`${classes.dualPaperRow} ${workMode !== "paired" ? classes.dualPaperRowSingle : ""}`}>
              {workMode !== "carrier_only" &&
                (activePair?.fba_box ? (
                  <div className={classes.paperCard}>
                    <div className={classes.paperSheetSquare}>
                      <img src={activePair.fba_box.clean_preview_b64} alt={`外箱标 ${activePair.fba_box.box_id}`} />
                      {showSafeFrame && <div className={classes.safeGuideBox} />}
                    </div>
                    <div className={classes.paperMeta}>
                      <Badge size="xs" color="blue" variant="light">
                        亚马逊外箱标
                      </Badge>
                      <span>{activePair.fba_box.box_id} · 98×98mm</span>
                    </div>
                  </div>
                ) : (
                  <div className={classes.missingSlotCard} onClick={() => fbaInputRef.current?.click()}>
                    <Badge color="orange" variant="light">
                      缺同号外箱标
                    </Badge>
                    <Text size="sm" fw={700}>
                      尚缺 {activePair?.shipment_id || activeGroup.display_label || activeGroup.shipment_id} 的外箱 PDF
                    </Text>
                    <Text size="xs" c="dimmed">
                      点击补充导入同货件号外箱标
                    </Text>
                  </div>
                ))}

              {workMode === "paired" && (
                <div className={classes.pairBridgeBadge}>
                  <Badge size="xs" color={activePair?.fba_box && activePair?.carrier_box && activeGroup.status === "matched" ? "green" : "orange"} variant="light">
                    {activeGroup.status === "matched" ? "FBA 编号配对一致" : "待核对配对"}
                  </Badge>
                  <Text size="xs" fw={700} ff="var(--mono)">
                    {activePair?.shipment_id || activeGroup.display_label || activeGroup.shipment_id}
                  </Text>
                  {activeGroup.group_kind === "sku" && (
                    <Text size="xs" c="dimmed" truncate maw={140}>
                      {activeGroup.display_label || "SKU 归集"}
                    </Text>
                  )}
                  <ArrowLeftRight size={15} color="var(--accent)" />
                  <Text size="xs" c="dimmed">
                    {activePair?.fba_box && activePair?.carrier_box
                      ? `第 ${activePair.box_index} 箱 ↔ CTNS:${activePair.carrier_box.box_index}`
                      : "单边待匹配"}
                  </Text>
                </div>
              )}

              {workMode !== "fba_only" &&
                (activePair?.carrier_box ? (
                  <div className={classes.paperCard}>
                    <div className={classes.paperSheetSquare}>
                      <img src={activePair.carrier_box.preview_b64} alt={`货代箱唛 第 ${activePair.carrier_box.box_index} 箱`} />
                      {showSafeFrame && <div className={classes.safeGuideBox} />}
                    </div>
                    <div className={classes.paperMeta}>
                      <Badge size="xs" color="green" variant="light">
                        货代箱唛
                      </Badge>
                      <span>
                        CTNS:{activePair.carrier_box.box_index}/{activePair.carrier_box.total_boxes} ·{" "}
                        {activePair.carrier_box.warehouse_code || "-"}
                      </span>
                    </div>
                  </div>
                ) : (
                  <div className={classes.missingSlotCard} onClick={() => carInputRef.current?.click()}>
                    <Badge color="orange" variant="light">
                      缺同号货代箱唛
                    </Badge>
                    <Text size="sm" fw={700}>
                      尚缺 {activePair?.shipment_id || activeGroup.display_label || activeGroup.shipment_id} 的货代箱唛
                    </Text>
                    <Text size="xs" c="dimmed">
                      点击导入同号箱唛，或切换“仅打外箱”
                    </Text>
                  </div>
                ))}
            </div>
          )}
        </div>
      </div>

      {/* 右栏：独立配比组合、队列、脱敏规则与出纸 */}
      <div className={classes.rightPanel}>
        <div className={classes.secTitle}>
          <span>每箱标签配比</span>
          <Group gap={4} wrap="nowrap">
            <Badge size="xs" color="teal" variant="light" title="常用配比组合、顺序与脱敏规则已自动写入本机配置">
              {prefsSavedAt > 0 ? "已记住偏好" : "默认记忆"}
            </Badge>
            <Badge size="xs" color="blue" variant="light">
              共 {pairing.total_sheets} 张
            </Badge>
          </Group>
        </div>

        <Group gap={4} mb="xs" wrap="wrap">
          {[
            { fba: 2, car: 1, label: "2+1" },
            { fba: 2, car: 2, label: "2+2" },
            { fba: 4, car: 2, label: "4+2" },
            { fba: 4, car: 4, label: "4+4" },
            { fba: 1, car: 1, label: "1+1" },
          ].map((preset) => {
            const matched = fbaCopies === preset.fba && carrierCopies === preset.car;
            return (
              <Button
                key={preset.label}
                size="compact-xs"
                variant={matched ? "filled" : "light"}
                title={`默认每箱 FBA ${preset.fba} 张 + 货代箱唛 ${preset.car} 张`}
                onClick={() => void setCopyCombo(preset.fba, preset.car)}
              >
                {preset.label}
              </Button>
            );
          })}
        </Group>

        <SimpleGrid cols={2} spacing={6} mb="sm">
          <NumberInput
            aria-label="全局每箱 FBA 外箱张数"
            label={
              <Group gap={4}>
                <span style={{ width: 6, height: 6, borderRadius: 3, background: "#2563eb", display: "inline-block" }} />
                <span>FBA 外箱/箱</span>
              </Group>
            }
            size="xs"
            min={0}
            max={20}
            disabled={workMode === "carrier_only"}
            value={fbaCopies}
            onChange={(v) => void setCopyCombo(Number(v) || 0, carrierCopies)}
          />
          <NumberInput
            aria-label="全局每箱货代箱唛张数"
            label={
              <Group gap={4}>
                <span style={{ width: 6, height: 6, borderRadius: 3, background: "#16a34a", display: "inline-block" }} />
                <span>货代箱唛/箱</span>
              </Group>
            }
            size="xs"
            min={0}
            max={20}
            disabled={workMode === "fba_only"}
            value={carrierCopies}
            onChange={(v) => void setCopyCombo(fbaCopies, Number(v) || 0)}
          />
        </SimpleGrid>

        <Divider my="xs" />

        <div className={classes.secTitle}>
          <span>出纸顺序</span>
          {pairing.queue.length > 0 && (
            <Text size="xs" c="dimmed" ff="var(--mono)">
              F:{pairing.queue.filter((q) => !q.is_separator && q.kind === "fba").length} · M:
              {pairing.queue.filter((q) => !q.is_separator && q.kind === "carrier").length}
            </Text>
          )}
        </div>
        {(() => {
          const rounds = Math.max(1, Math.min(3, Math.max(fbaCopies, carrierCopies)));
          const seqTokens: string[] = [];
          for (let r = 1; r <= rounds; r += 1) {
            if (r <= fbaCopies) seqTokens.push("F1");
            if (r <= carrierCopies) seqTokens.push("M1");
          }
          if (Math.max(fbaCopies, carrierCopies) > 3) seqTokens.push("...");
          const interleaveExample = seqTokens.length ? `[${seqTokens.join(", ")}]` : "[F1, M1]";
          const perBoxExample = `[F1×${fbaCopies}, M1×${carrierCopies}]`;
          return (
            <Radio.Group value={orderMode} onChange={(v) => void setOrderMode(v as typeof orderMode)}>
              <Stack gap={6} mb="xs">
                <Radio size="xs" value="per_box_group" label={`按箱成组：${perBoxExample} 连续出纸`} />
                <Radio size="xs" value="interleave" label={`轮流交替：${interleaveExample} 逐轮交替`} />
                <Radio size="xs" value="split_all" label="分组先后：先打全部 FBA，再打全部箱唛" />
              </Stack>
            </Radio.Group>
          );
        })()}

        <Checkbox
          size="xs"
          mb="xs"
          label="切换仓库 / 货件时插入分隔提示页"
          checked={insertSeparatorPages}
          onChange={(e) => void setInsertSeparatorPages(e.currentTarget.checked)}
        />

        <Paper withBorder p={6} radius="sm" bg="var(--bg-subtle)" style={{ maxHeight: 84, overflowY: "auto" }}>
          <Group gap={4}>
            {pairing.queue.slice(0, 32).map((q) => (
              <Badge
                key={q.seq}
                size="xs"
                variant={q.is_separator ? "filled" : "light"}
                color={q.is_separator ? "orange" : q.kind === "fba" ? "blue" : "green"}
                ff="var(--mono)"
                title={q.is_separator ? q.separator_detail : `${q.shipment_id} ${q.warehouse_code || ""}`}
              >
                {q.seq}.{q.label}
              </Badge>
            ))}
            {pairing.queue.length > 32 && (
              <Badge size="xs" variant="outline" color="gray">
                +{pairing.queue.length - 32} 张...
              </Badge>
            )}
          </Group>
        </Paper>

        <Divider my="sm" />

        <div className={classes.secTitle}>
          <span>隐藏敏感信息（真实物理擦除）</span>
        </div>
        <Stack gap={6}>
          <Checkbox
            size="xs"
            label="隐藏发货人地址"
            checked={redactionOptions.redact_ship_from}
            onChange={(e) => void updateRedactionOption("redact_ship_from", e.currentTarget.checked)}
          />
          <Checkbox
            size="xs"
            label="隐藏公司名称（保留仓库地址）"
            checked={redactionOptions.redact_fba_company}
            onChange={(e) => void updateRedactionOption("redact_fba_company", e.currentTarget.checked)}
          />
          <Checkbox
            size="xs"
            label="连带隐藏发货地标题行"
            checked={redactionOptions.redact_headers}
            onChange={(e) => void updateRedactionOption("redact_headers", e.currentTarget.checked)}
          />
          <Checkbox
            size="xs"
            label="缺少 Made In China 时自动补印"
            checked={redactionOptions.auto_add_mic}
            onChange={(e) => void updateRedactionOption("auto_add_mic", e.currentTarget.checked)}
          />
        </Stack>

        <Stack gap={6} mt="auto" pt="md">
          <Button fullWidth disabled={!pairing.can_print || pairing.total_sheets === 0} onClick={handleOpenPrint}>
            打印所选标签 (100×100mm)
          </Button>
          <Button
            fullWidth
            variant="default"
            disabled={!pairing.can_print || pairing.total_sheets === 0}
            onClick={() => void handleExportMerged()}
          >
            导出合并 PDF
          </Button>
          <SimpleGrid cols={2} spacing={6}>
            <Button
              size="xs"
              variant="light"
              disabled={!pairing.can_print || pairing.queue.length === 0}
              onClick={() => void handleExportManifestCsv()}
            >
              导出核对 CSV
            </Button>
            <Button
              size="xs"
              variant="light"
              color="teal"
              disabled={!pairing.groups.length || !pairing.can_print}
              onClick={() => void handleExportSkuZip()}
            >
              按组打包 ZIP
            </Button>
          </SimpleGrid>
        </Stack>
      </div>
      <CarrierRulesModal opened={rulesOpen} onClose={() => setRulesOpen(false)} />
    </div>
  );
}
