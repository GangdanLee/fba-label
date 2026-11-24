import { useRef, useState } from "react";
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
  Stack,
  Text,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { AlertTriangle, ArrowLeftRight, Pencil, SlidersHorizontal, Upload, X } from "lucide-react";
import * as api from "../api/client";
import classes from "../styles/Studio.module.css";
import { useWorkbenchStore } from "../store/useWorkbenchStore";
import { CarrierRulesModal } from "./CarrierRulesModal";

export function BoxStudio() {
  const {
    fbaFiles,
    carrierFiles,
    manualAssignments,
    workMode,
    orderMode,
    stageMode,
    showSafeFrame,
    defaultCopies,
    redactionOptions,
    pairing,
    activeGroupId,
    activeBoxIndex,
    boxBusy,
    boxOverlayElements,
    uploadFbaFiles,
    uploadCarrierFiles,
    removeFbaFile,
    removeCarrierFile,
    clearBoxWorkspace,
    setManualAssignment,
    updateRedactionOption,
    setWorkMode,
    setOrderMode,
    setStageMode,
    setShowSafeFrame,
    setDefaultCopies,
    setSingleBoxCopies,
    toggleSingleBoxSelected,
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

  const activeGroup = pairing.groups.find((g) => g.shipment_id === activeGroupId) || pairing.groups[0] || null;
  const activePair = activeGroup?.pairs.find((p) => p.box_index === activeBoxIndex) || activeGroup?.pairs[0] || null;
  const groupIds = pairing.groups.map((g) => ({ value: g.shipment_id, label: `归属到 ${g.shipment_id}` }));

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
    api.downloadBase64Pdf(res.pdf_b64, `${activeGroup?.shipment_id || "FBA_Box"}_${res.page_count}pages.pdf`);
    notifications.show({ title: "已导出合并 PDF", message: `共 ${res.page_count} 页 (100×100mm)`, color: "green" });
  };

  const handleOpenPrint = () => {
    if (!pairing.can_print || !activeGroup) return;
    openPrintJob({
      title: `打印外箱任务 · ${activeGroup.shipment_id}`,
      summaryDesc: `${activeGroup.shipment_id}（${pairing.total_sheets} 张）`,
      specKey: "100x100_single",
      batchType: workMode === "fba_only" ? "box_fba_only" : workMode === "carrier_only" ? "box_carrier_only" : "box_paired",
      shipmentId: activeGroup.shipment_id,
      warehouseCode: activeGroup.warehouse_code || "-",
      totalUnitsOrBoxes: activeGroup.pairs.filter((p) => p.selected).length,
      copiesPerBox: defaultCopies,
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
            onClick={() => fbaInputRef.current?.click()}
            onKeyDown={(e) => e.key === "Enter" && fbaInputRef.current?.click()}
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
            onClick={() => carInputRef.current?.click()}
            onKeyDown={(e) => e.key === "Enter" && carInputRef.current?.click()}
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
            <span>打印范围与货件分组</span>
          </div>
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
                  <Group justify="space-between" mb={2}>
                    <Text size="xs" fw={700} ff="var(--mono)">
                      {g.shipment_id}
                    </Text>
                    <Badge size="xs" color={g.status === "matched" ? "green" : "orange"} variant="light">
                      {g.status === "matched" ? "编号配对一致" : g.status === "missing_carrier" ? "缺箱唛" : g.status === "missing_fba" ? "缺外箱" : "存在差异"}
                    </Badge>
                  </Group>
                  <Text size="xs" c="dimmed">
                    仓点 {g.warehouse_code || "-"} · {g.pairs.length} 箱
                  </Text>
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
            </div>
            <Stack gap={6}>
              {activeGroup.pairs.map((p) => {
                const active = activePair?.box_index === p.box_index;
                return (
                  <Paper
                    key={p.box_index}
                    withBorder
                    p={8}
                    radius="sm"
                    style={{
                      cursor: "pointer",
                      opacity: p.selected ? 1 : 0.55,
                      borderColor: active ? "var(--accent)" : undefined,
                      background: active ? "var(--accent-soft)" : undefined,
                    }}
                    onClick={() => setActiveBoxIndex(p.box_index)}
                  >
                    <Group justify="space-between" wrap="nowrap">
                      <Group gap={6}>
                        <Checkbox
                          aria-label={`勾选第 ${p.box_index} 箱`}
                          checked={p.selected}
                          onChange={(e) => void toggleSingleBoxSelected(activeGroup.shipment_id, p.box_index, e.currentTarget.checked)}
                          onClick={(e) => e.stopPropagation()}
                        />
                        <Text size="xs" fw={600}>
                          第 {p.box_index} 箱
                        </Text>
                      </Group>
                      <NumberInput
                        aria-label={`第 ${p.box_index} 箱套数`}
                        size="xs"
                        w={62}
                        min={1}
                        max={20}
                        value={p.copies}
                        onClick={(e) => e.stopPropagation()}
                        onChange={(v) => void setSingleBoxCopies(activeGroup.shipment_id, p.box_index, Number(v) || 1)}
                      />
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
                      尚缺 {activeGroup.shipment_id} 的外箱 PDF
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
                    {activeGroup.shipment_id}
                  </Text>
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
                      尚缺 {activeGroup.shipment_id} 的货代箱唛
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

      {/* 右栏：套数、队列、脱敏规则与出纸 */}
      <div className={classes.rightPanel}>
        <div className={classes.secTitle}>
          <span>每箱打印套数（建议 3~5 面）</span>
          <Badge size="xs" color="blue" variant="light">
            共 {pairing.total_sheets} 张
          </Badge>
        </div>

        <Group gap={6} mb="sm" wrap="nowrap">
          <SegmentedControl
            size="xs"
            style={{ flex: 1 }}
            value={String(defaultCopies)}
            onChange={(v) => void setDefaultCopies(Number(v))}
            data={[
              { value: "1", label: "1套" },
              { value: "3", label: "3套" },
              { value: "4", label: "4套" },
              { value: "5", label: "5套" },
            ]}
          />
          <NumberInput
            aria-label="自定义每箱打印套数"
            size="xs"
            w={62}
            min={1}
            max={20}
            value={defaultCopies}
            onChange={(v) => void setDefaultCopies(Number(v) || 1)}
          />
        </Group>

        <Divider my="xs" />

        <div className={classes.secTitle}>
          <span>出纸顺序</span>
        </div>
        <Radio.Group value={orderMode} onChange={(v) => void setOrderMode(v as typeof orderMode)}>
          <Stack gap={6} mb="xs">
            <Radio size="xs" value="interleave" label="贴面交替：[外箱1, 箱唛1] × 套数" />
            <Radio size="xs" value="per_box_group" label="同箱紧邻：[外箱1×套数, 箱唛1×套数]" />
            <Radio size="xs" value="split_all" label="分组先后：先打全部外箱，再打箱唛" />
          </Stack>
        </Radio.Group>

        <Paper withBorder p={6} radius="sm" bg="var(--bg-subtle)" style={{ maxHeight: 84, overflowY: "auto" }}>
          <Group gap={4}>
            {pairing.queue.slice(0, 32).map((q) => (
              <Badge key={q.seq} size="xs" variant="light" color={q.kind === "fba" ? "blue" : "green"} ff="var(--mono)">
                {q.seq}.{q.label}
              </Badge>
            ))}
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
        </Stack>
      </div>
      <CarrierRulesModal opened={rulesOpen} onClose={() => setRulesOpen(false)} />
    </div>
  );
}
