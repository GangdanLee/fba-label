import { useEffect, useRef, useState } from "react";
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Collapse,
  Group,
  Modal,
  NumberInput,
  Paper,
  Radio,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { ChevronDown, ChevronUp, Download, Info, Plus, Trash2, Upload } from "lucide-react";
import * as api from "../api/client";
import { useWorkbenchStore } from "../store/useWorkbenchStore";
import type { BackupSummary, CalibrationProfile } from "../types";

export function HardwareView() {
  const { profiles, printers, saveProfile, createProfile, removeProfile, refreshPrinters, initApp } = useWorkbenchStore();
  const [backupSummary, setBackupSummary] = useState<BackupSummary | null>(null);
  const [includeSnapshots, setIncludeSnapshots] = useState(false);
  const [importMode, setImportMode] = useState<"merge" | "replace">("merge");
  const [backupBusy, setBackupBusy] = useState(false);
  const backupFileRef = useRef<HTMLInputElement>(null);

  const loadBackupSummary = async () => {
    try {
      setBackupSummary(await api.fetchBackupSummary());
    } catch {
      // 忽略统计拉取失败
    }
  };

  useEffect(() => {
    void loadBackupSummary();
  }, [profiles.length]);
  const [previewMeta, setPreviewMeta] = useState<{ img: string; dpi: number; protocol: string }>({
    img: "",
    dpi: 203,
    protocol: "tspl",
  });
  const [netStatus, setNetStatus] = useState<Record<string, { ok: boolean; message: string }>>({});
  const [testingSpec, setTestingSpec] = useState<string | null>(null);
  const [draftEdits, setDraftEdits] = useState<Record<string, CalibrationProfile>>({});
  const [showCompatGuide, setShowCompatGuide] = useState(false);
  const [expandedAdv, setExpandedAdv] = useState<Record<string, boolean>>({});
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newWidth, setNewWidth] = useState(40);
  const [newHeight, setNewHeight] = useState(30);
  const [newCols, setNewCols] = useState<1 | 2>(2);
  const [newColGap, setNewColGap] = useState(2);
  const [newSpecKey, setNewSpecKey] = useState("40x30_double");
  const [newProtocol, setNewProtocol] = useState<"tspl" | "zpl">("tspl");
  const [newDpi, setNewDpi] = useState<203 | 300>(203);
  const [newDarkness, setNewDarkness] = useState(8);

  const getProf = (p: CalibrationProfile) => draftEdits[p.spec_key] || p;

  const updateField = <K extends keyof CalibrationProfile>(
    base: CalibrationProfile,
    key: K,
    val: CalibrationProfile[K],
  ) => {
    setDraftEdits((prev) => ({
      ...prev,
      [base.spec_key]: { ...(prev[base.spec_key] || base), [key]: val },
    }));
  };

  const applyPrinterSelection = (base: CalibrationProfile, selectedName: string) => {
    const cur = getProf(base);
    const dev = printers.find((d) => d.name === selectedName);
    if (!dev) {
      updateField(base, "printer_name", selectedName);
      return;
    }
    const nextPatch: Partial<CalibrationProfile> = {
      printer_name: selectedName,
      dpi: dev.suggested_dpi,
    };
    if (dev.suggested_protocol === "os_driver") {
      nextPatch.preferred_channel = "os_driver";
    } else {
      nextPatch.protocol = dev.suggested_protocol;
      if (cur.preferred_channel === "os_driver") {
        nextPatch.preferred_channel = "tspl_raw";
      }
    }
    setDraftEdits((prev) => ({
      ...prev,
      [base.spec_key]: { ...cur, ...nextPatch },
    }));
    notifications.show({
      title: `已匹配 ${dev.name}`,
      message: `自动预填建议：${dev.suggested_protocol.toUpperCase()} · ${dev.suggested_dpi}dpi（可随时手动修改）`,
      color: "blue",
    });
  };

  const handleTestNetwork = async (p: CalibrationProfile) => {
    setTestingSpec(p.spec_key);
    try {
      const res = await api.testNetworkPrinter(p.network_host, p.network_port || 9100);
      setNetStatus((prev) => ({ ...prev, [p.spec_key]: { ok: res.ok, message: res.message } }));
      notifications.show({
        title: res.ok ? "网口热敏机连通正常" : "网口连接失败",
        message: res.message,
        color: res.ok ? "green" : "red",
      });
    } finally {
      setTestingSpec(null);
    }
  };

  const handleTestCard = async (specKey: string) => {
    const res = await api.generateCalibrationCard(specKey);
    setPreviewMeta({
      img: res.preview_203dpi_b64,
      dpi: res.dpi ?? 203,
      protocol: res.protocol ?? "tspl",
    });
    api.downloadBase64Pdf(res.pdf_b64, `Calibration_${specKey}.pdf`);
  };

  const applyCustomPreset = (w: number, h: number, cols: 1 | 2, gap: number, key: string) => {
    setNewWidth(w);
    setNewHeight(h);
    setNewCols(cols);
    setNewColGap(gap);
    setNewSpecKey(key);
  };

  const handleCreateProfile = async () => {
    const cleanKey = newSpecKey.trim() || `${Math.round(newWidth)}x${Math.round(newHeight)}_${newCols >= 2 ? "double" : "single"}`;
    if (profiles.some((item) => item.spec_key === cleanKey)) {
      notifications.show({
        title: "规格编码已存在",
        message: `${cleanKey} 已在当前校准列表中，请直接修改其卡片参数或更换编码`,
        color: "orange",
      });
      return;
    }
    setCreating(true);
    try {
      await createProfile({
        spec_key: cleanKey,
        label_width_mm: Number(newWidth) || 40,
        label_height_mm: Number(newHeight) || 30,
        cols: newCols,
        col_gap_mm: newCols >= 2 ? Number(newColGap) || 2 : 0,
        row_gap_mm: 2,
        safe_width_mm: Math.max(10, (Number(newWidth) || 40) - 4),
        safe_height_mm: Math.max(10, (Number(newHeight) || 30) - 4),
        offset_x_mm: 0,
        offset_y_mm: 0,
        darkness: Number(newDarkness) || 8,
        print_speed: 4,
        preferred_channel: "tspl_raw",
        printer_name: "",
        protocol: newProtocol,
        dpi: newDpi,
        connection_type: "os_queue",
        network_host: "",
        network_port: 9100,
        tspl_direction: 1,
        invert_bitmap: false,
      });
      setAddModalOpen(false);
    } catch (err) {
      notifications.show({ title: "创建失败", message: (err as Error).message, color: "red" });
    } finally {
      setCreating(false);
    }
  };

  const handleSaveProfile = async (prof: CalibrationProfile) => {
    await saveProfile(prof);
    setDraftEdits((prev) => {
      const next = { ...prev };
      delete next[prof.spec_key];
      return next;
    });
  };

  const handleExportBackup = async () => {
    setBackupBusy(true);
    try {
      const res = await api.exportSystemBackup(includeSnapshots);
      api.downloadBase64File(res.zip_b64, res.filename, "application/zip");
      notifications.show({
        title: "已导出本地配置备份包",
        message: `包含 ${res.counts.skus} 个模板、${res.counts.rules} 条规则、${res.counts.profiles} 个纸卷校准`,
        color: "green",
      });
    } catch (err) {
      notifications.show({ title: "备份导出失败", message: (err as Error).message, color: "red" });
    } finally {
      setBackupBusy(false);
    }
  };

  const handleImportBackupFile = async (file: File) => {
    setBackupBusy(true);
    try {
      const res = await api.importSystemBackup(file, importMode);
      setDraftEdits({});
      await initApp({ discardSavedDraft: importMode === "replace" });
      await loadBackupSummary();
      notifications.show({
        title: "配置备份恢复成功",
        message: `已${res.mode === "merge" ? "合并" : "覆盖"}恢复 ${res.restored.skus ?? 0} 个模板与 ${res.restored.rules ?? 0} 条规则（旧库留底：${res.pre_import_backup_name}）`,
        color: "green",
      });
    } catch (err) {
      notifications.show({ title: "导入恢复失败", message: (err as Error).message, color: "red" });
    } finally {
      setBackupBusy(false);
    }
  };

  const handleRemoveProfile = async (specKey: string) => {
    try {
      await removeProfile(specKey);
      setDraftEdits((prev) => {
        const next = { ...prev };
        delete next[specKey];
        return next;
      });
    } catch (err) {
      notifications.show({ title: "删除失败", message: (err as Error).message, color: "red" });
    }
  };

  const printerOptions = [
    { value: "", label: "自动选择推荐热敏机" },
    ...printers.map((d) => ({
      value: d.name,
      label: `${d.name} (${d.suggested_protocol.toUpperCase()}·${d.suggested_dpi}dpi · ${
        d.status === "offline" ? "离线" : d.status === "disabled" ? "停用" : "就绪"
      })`,
    })),
  ];

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: 24, maxWidth: 1060, margin: "0 auto", width: "100%" }}>
      <Paper withBorder p="md" radius="md" mb="md">
        <Group justify="space-between" mb="xs">
          <div>
            <Text fw={700}>通用打印机探测与多机协议路由</Text>
            <Text size="xs" c="dimmed">
              支持 TSPL2（TSC / 芯烨 / 佳博 / 汉印 / Rollo）、ZPL II（斑马 Zebra / 工业机）、系统原生驱动与局域网 TCP 9100 直连；可为外箱与产品标绑定不同设备免换纸。
            </Text>
          </div>
          <Group gap="xs">
            <Button
              size="xs"
              variant="subtle"
              leftSection={<Info size={13} />}
              onClick={() => setShowCompatGuide((prev) => !prev)}
            >
              芯烨 / 佳博适配说明
            </Button>
            <Button size="xs" variant="light" leftSection={<Plus size={13} />} onClick={() => setAddModalOpen(true)}>
              新增纸卷规格
            </Button>
            <Button size="xs" variant="default" onClick={() => void refreshPrinters()}>
              刷新设备列表
            </Button>
          </Group>
        </Group>
        <Stack gap={6}>
          <Group gap="xs">
            {printers.length === 0 ? (
              <Badge color="gray" variant="light">
                当前环境未检测到本机驱动打印机（仍可使用局域网 TCP 9100、离线干跑与导出 PDF）
              </Badge>
            ) : (
              printers.map((d) => {
                const statusLabel =
                  d.status === "offline" ? " · 离线" : d.status === "disabled" ? " · 已停用" : " · 就绪";
                const badgeColor =
                  d.status === "offline"
                    ? "red"
                    : d.status === "disabled"
                      ? "gray"
                      : d.is_thermal_hint
                        ? "green"
                        : "blue";
                return (
                  <Badge
                    key={d.name}
                    color={badgeColor}
                    variant="light"
                    title={d.usage_tip || d.status_detail || undefined}
                  >
                    {d.name} ({d.system})
                    {d.brand_label ? ` · ${d.brand_label}` : ""}
                    {d.is_default ? " · 默认" : ""}
                    {` · 建议 ${d.suggested_protocol.toUpperCase()} ${d.suggested_dpi}dpi`}
                    {statusLabel}
                  </Badge>
                );
              })
            )}
          </Group>
          {printers
            .filter((d) => d.status_detail || d.usage_tip)
            .map((d) => (
              <Text key={`${d.name}-detail`} size="xs" c={d.status === "offline" ? "red" : "dimmed"}>
                {d.name}：{d.status_detail ? `${d.status_detail} ` : ""}
                {d.usage_tip}
              </Text>
            ))}
          <Collapse expanded={showCompatGuide}>
            <Alert color="blue" variant="light" mt={4} p="xs" title="芯烨 XP-420B / 佳博 (Gprinter) / 兼容热敏机快速适配指南">
              <Stack gap={4}>
                <Text size="xs">
                  1. <strong>芯烨 XP-420B 等机型</strong>：均原生支持 <strong>TSPL2 协议 (203dpi)</strong>；请确认机器处于「标签模式 (TSPL)」而非小票 ESC/POS 模式（开机长按走纸键或使用官网诊断工具切换）。Windows 若系统未自动创建队列，可选用官方 XP-420B 或兼容的 4BARCODE 4B-2054A 驱动，或直接走「局域网 TCP 9100」。
                </Text>
                <Text size="xs">
                  2. <strong>佳博 (GP-1324D / GP-1134T / GP-3120TU 等)</strong>：本软件每次出纸自动注入 <code>REFERENCE 0,0</code> 与 <code>SET TEAR ON</code> 消除遗留偏移，负 X/Y 偏移改为画布内像素安全平移防止错乱；300dpi 机型请在下方将 DPI 设为 300。
                </Text>
                <Text size="xs">
                  3. <strong>macOS AirPrint 驱动兜底</strong>：若 macOS 队列使用 AirPrint 驱动导致「裸指令直出」报 format 不支持，可在下方切换为「系统原生驱动打印」或使用通用 Raw CUPS 队列。
                </Text>
              </Stack>
            </Alert>
          </Collapse>
        </Stack>
      </Paper>

      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
        {profiles.map((rawProf) => {
          const p = getProf(rawProf);
          const isTcp = p.connection_type === "network_tcp";
          const isBuiltin = p.spec_key === "50x30_double" || p.spec_key === "100x100_single";
          const cardTitle =
            p.spec_key === "50x30_double"
              ? "50×30mm 双排产品标纸卷"
              : p.spec_key === "100x100_single"
                ? "100×100mm 单排外箱标纸卷"
                : `${p.label_width_mm}×${p.label_height_mm}mm ${p.cols >= 2 ? "双排" : "单排"}自定义纸卷`;
          const curNetStatus = netStatus[p.spec_key];
          const isDirty = Boolean(draftEdits[p.spec_key]);
          const advOpen = Boolean(expandedAdv[p.spec_key]);
          return (
            <Card key={p.spec_key} withBorder radius="md" p="md">
              <Group justify="space-between" mb="sm" wrap="nowrap">
                <Text fw={700} truncate>
                  {cardTitle}
                </Text>
                <Group gap={6} wrap="nowrap">
                  {isDirty && (
                    <Badge color="orange" variant="filled" size="xs">
                      未保存
                    </Badge>
                  )}
                  <Badge color="gray" variant="outline" size="xs">
                    {isTcp ? `TCP ${p.network_host || "未填IP"}:${p.network_port}` : p.printer_name || "自动选机"}
                  </Badge>
                  <Badge color={p.cols >= 2 ? "blue" : "green"} variant="light">
                    {p.spec_key}
                  </Badge>
                  {!isBuiltin && (
                    <ActionIcon
                      size="xs"
                      variant="subtle"
                      color="red"
                      aria-label={`删除纸卷规格 ${p.spec_key}`}
                      title="删除自定义规格"
                      onClick={() => void handleRemoveProfile(p.spec_key)}
                    >
                      <Trash2 size={13} />
                    </ActionIcon>
                  )}
                </Group>
              </Group>

              <Stack gap="xs">
                <SimpleGrid cols={2}>
                  <Select
                    label="连接方式"
                    value={p.connection_type || "os_queue"}
                    data={[
                      { value: "os_queue", label: "本机已安装打印机" },
                      { value: "network_tcp", label: "局域网 TCP 9100 直连" },
                    ]}
                    onChange={(v) =>
                      updateField(rawProf, "connection_type", (v as CalibrationProfile["connection_type"]) || "os_queue")
                    }
                  />

                  {!isTcp ? (
                    <Select
                      label="绑定目标打印机"
                      value={p.printer_name || ""}
                      data={printerOptions}
                      onChange={(v) => applyPrinterSelection(rawProf, v ?? "")}
                    />
                  ) : (
                    <NumberInput
                      label="TCP 端口"
                      min={1}
                      max={65535}
                      value={p.network_port || 9100}
                      onChange={(v) => updateField(rawProf, "network_port", Math.min(65535, Math.max(1, Number(v) || 9100)))}
                    />
                  )}
                </SimpleGrid>

                {isTcp && (
                  <Group align="flex-end" gap="xs">
                    <TextInput
                      label="网口打印机 IP / 主机名"
                      placeholder="例如 192.168.1.88"
                      style={{ flex: 1 }}
                      value={p.network_host || ""}
                      onChange={(e) => updateField(rawProf, "network_host", e.currentTarget.value)}
                    />
                    <Button
                      size="xs"
                      variant="light"
                      loading={testingSpec === p.spec_key}
                      onClick={() => void handleTestNetwork(p)}
                    >
                      测试连通
                    </Button>
                  </Group>
                )}

                {isTcp && curNetStatus && (
                  <Alert color={curNetStatus.ok ? "green" : "red"} p={6}>
                    <Text size="xs">{curNetStatus.message}</Text>
                  </Alert>
                )}

                <SimpleGrid cols={2}>
                  <Select
                    label="指令协议"
                    value={p.protocol || "tspl"}
                    data={[
                      { value: "tspl", label: "TSPL2（TSC / 芯烨 / 佳博 / 汉印）" },
                      { value: "zpl", label: "ZPL II（斑马 Zebra / 工业机）" },
                    ]}
                    onChange={(v) => updateField(rawProf, "protocol", (v as CalibrationProfile["protocol"]) || "tspl")}
                  />
                  <Select
                    label="打印头精度 (DPI)"
                    value={String(p.dpi || 203)}
                    data={[
                      { value: "203", label: "203 dpi（8 点/mm）" },
                      { value: "300", label: "300 dpi（12 点/mm）" },
                    ]}
                    onChange={(v) => updateField(rawProf, "dpi", (Number(v) === 300 ? 300 : 203) as 203 | 300)}
                  />
                </SimpleGrid>

                <SimpleGrid cols={2}>
                  <NumberInput
                    label="水平偏移 X (mm)"
                    step={0.2}
                    decimalScale={1}
                    value={p.offset_x_mm}
                    onChange={(v) => updateField(rawProf, "offset_x_mm", Number(v) || 0)}
                  />
                  <NumberInput
                    label="垂直偏移 Y (mm)"
                    step={0.2}
                    decimalScale={1}
                    value={p.offset_y_mm}
                    onChange={(v) => updateField(rawProf, "offset_y_mm", Number(v) || 0)}
                  />
                </SimpleGrid>

                <SimpleGrid cols={2}>
                  <NumberInput
                    label="行间隙 GAP (mm)"
                    step={0.5}
                    min={0}
                    max={10}
                    decimalScale={1}
                    value={p.row_gap_mm}
                    onChange={(v) => updateField(rawProf, "row_gap_mm", Number(v) || 2)}
                  />
                  <NumberInput
                    label="打印浓度 (0~15)"
                    min={1}
                    max={15}
                    value={p.darkness}
                    onChange={(v) => updateField(rawProf, "darkness", Number(v) || 8)}
                  />
                </SimpleGrid>

                <Select
                  label="首选出纸通道"
                  data={[
                    { value: "tspl_raw", label: "裸指令直出（TSPL / ZPL）" },
                    { value: "os_driver", label: "系统原生驱动打印（Brother / 办公机兜底）" },
                    { value: "pdf_export", label: "仅导出 PDF 文件" },
                  ]}
                  value={p.preferred_channel}
                  onChange={(v) =>
                    updateField(rawProf, "preferred_channel", (v as CalibrationProfile["preferred_channel"]) || "tspl_raw")
                  }
                />

                <div>
                  <Button
                    size="compact-xs"
                    variant="subtle"
                    color="gray"
                    rightSection={advOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                    onClick={() => setExpandedAdv((prev) => ({ ...prev, [p.spec_key]: !prev[p.spec_key] }))}
                  >
                    进阶兼容参数（芯烨 / 佳博微调）
                  </Button>
                  <Collapse expanded={advOpen}>
                    <Paper withBorder p="xs" mt={6} radius="sm" bg="var(--bg-subtle)">
                      <Stack gap="xs">
                        <SimpleGrid cols={2}>
                          <Select
                            label="出纸方向 (DIRECTION)"
                            size="xs"
                            value={String(p.tspl_direction ?? 1)}
                            data={[
                              { value: "1", label: "1 · 正向标准出纸（推荐）" },
                              { value: "0", label: "0 · 倒转 180° 出纸" },
                            ]}
                            onChange={(v) => updateField(rawProf, "tspl_direction", Number(v) === 0 ? 0 : 1)}
                          />
                          <NumberInput
                            label="打印速度 (SPEED 1~8)"
                            size="xs"
                            min={1}
                            max={8}
                            value={p.print_speed || 4}
                            onChange={(v) => updateField(rawProf, "print_speed", Math.min(8, Math.max(1, Number(v) || 4)))}
                          />
                        </SimpleGrid>
                        <Checkbox
                          size="xs"
                          label="位图反色补偿（仅当个别国产固件印出黑底白字反白时开启）"
                          checked={Boolean(p.invert_bitmap)}
                          onChange={(e) => updateField(rawProf, "invert_bitmap", e.currentTarget.checked)}
                        />
                      </Stack>
                    </Paper>
                  </Collapse>
                </div>

                <Group justify="flex-end" mt="xs">
                  <Button size="xs" variant="default" onClick={() => void handleTestCard(p.spec_key)}>
                    下载校准测试卡 PDF
                  </Button>
                  <Button size="xs" onClick={() => void handleSaveProfile(p)}>
                    保存校准参数
                  </Button>
                </Group>
              </Stack>
            </Card>
          );
        })}
      </SimpleGrid>

      {previewMeta.img && (
        <Paper withBorder p="md" mt="md" radius="md">
          <Text fw={600} size="sm" mb="xs">
            {previewMeta.dpi}dpi {previewMeta.protocol.toUpperCase()} 校准卡点阵仿真预览（已同步触发 PDF 下载）
          </Text>
          <img
            src={previewMeta.img}
            alt={`${previewMeta.dpi}dpi 校准卡仿真预览`}
            style={{ maxWidth: 360, border: "1px solid var(--border-strong)", borderRadius: 4, background: "#fff" }}
          />
        </Paper>
      )}

      <Paper withBorder p="md" mt="md" radius="md">
        <Group justify="space-between" mb="xs" wrap="wrap" gap="xs">
          <div>
            <Text fw={700}>本机配置与模板一键备份 / 多机迁移</Text>
            <Text size="xs" c="dimmed">
              将 SKU 自由排版模板、货代箱唛解析规则、打印机校准参数与外箱配比偏好打包为 ZIP 迁移至其他电脑（导入前自动创建回滚数据库副本）。
            </Text>
          </div>
          {backupSummary && (
            <Group gap={6} wrap="wrap">
              <Badge size="xs" variant="light" color="blue">
                SKU 模板 {backupSummary.skus_count} 个
              </Badge>
              <Badge size="xs" variant="light" color="teal">
                货代规则 {backupSummary.rules_count} 条
              </Badge>
              <Badge size="xs" variant="light" color="indigo">
                校准档 {backupSummary.profiles_count} 个
              </Badge>
              <Badge size="xs" variant="light" color="gray">
                历史批次 {backupSummary.batches_count} 条
              </Badge>
            </Group>
          )}
        </Group>

        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md" mt="sm">
          <Paper withBorder p="sm" radius="sm" bg="var(--bg-subtle)">
            <Stack gap="xs">
              <Text size="xs" fw={700}>
                导出本地配置备份 ZIP
              </Text>
              <Checkbox
                size="xs"
                label="同时打包历史打印批次与 PDF 快照（文件体积较大，换机完整迁移时勾选）"
                checked={includeSnapshots}
                onChange={(e) => setIncludeSnapshots(e.currentTarget.checked)}
              />
              <Button
                size="xs"
                leftSection={<Download size={13} />}
                loading={backupBusy}
                onClick={() => void handleExportBackup()}
              >
                导出配置备份 ZIP
              </Button>
            </Stack>
          </Paper>

          <Paper withBorder p="sm" radius="sm" bg="var(--bg-subtle)">
            <Stack gap="xs">
              <Text size="xs" fw={700}>
                从备份 ZIP 导入恢复
              </Text>
              <Radio.Group value={importMode} onChange={(v) => setImportMode(v as "merge" | "replace")}>
                <Group gap="md">
                  <Radio size="xs" value="merge" label="增量合并（推荐：保留现有，同名覆盖更新）" />
                  <Radio size="xs" value="replace" label="完全替换（清空后重建为备份状态）" />
                </Group>
              </Radio.Group>
              <Button
                size="xs"
                variant="default"
                leftSection={<Upload size={13} />}
                loading={backupBusy}
                onClick={() => backupFileRef.current?.click()}
              >
                选择备份 ZIP 导入恢复
              </Button>
              <input
                ref={backupFileRef}
                type="file"
                accept=".zip,application/zip"
                style={{ display: "none" }}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void handleImportBackupFile(file);
                  e.target.value = "";
                }}
              />
            </Stack>
          </Paper>
        </SimpleGrid>
      </Paper>

      <Modal opened={addModalOpen} onClose={() => setAddModalOpen(false)} title="新增自定义纸卷规格" size="md" centered>
        <Stack gap="sm">
          <Text size="xs" c="dimmed">
            选择常用热敏纸预设或输入自定义尺寸，即可生成独立校准卡、绑定专属打印机与 DPI / 协议。
          </Text>

          <Group gap={6}>
            <Button size="compact-xs" variant="light" onClick={() => applyCustomPreset(40, 30, 2, 2, "40x30_double")}>
              40×30mm 双排
            </Button>
            <Button size="compact-xs" variant="light" onClick={() => applyCustomPreset(60, 40, 1, 0, "60x40_single")}>
              60×40mm 单排
            </Button>
            <Button size="compact-xs" variant="light" onClick={() => applyCustomPreset(70, 50, 1, 0, "70x50_single")}>
              70×50mm 单排
            </Button>
            <Button size="compact-xs" variant="light" onClick={() => applyCustomPreset(100, 150, 1, 0, "100x150_single")}>
              100×150mm 单排
            </Button>
          </Group>

          <SimpleGrid cols={2}>
            <NumberInput
              label="单张宽度 (mm)"
              min={20}
              max={160}
              value={newWidth}
              onChange={(v) => {
                const w = Number(v) || 40;
                setNewWidth(w);
                setNewSpecKey(`${Math.round(w)}x${Math.round(newHeight)}_${newCols >= 2 ? "double" : "single"}`);
              }}
            />
            <NumberInput
              label="单张高度 (mm)"
              min={15}
              max={200}
              value={newHeight}
              onChange={(v) => {
                const h = Number(v) || 30;
                setNewHeight(h);
                setNewSpecKey(`${Math.round(newWidth)}x${Math.round(h)}_${newCols >= 2 ? "double" : "single"}`);
              }}
            />
          </SimpleGrid>

          <SimpleGrid cols={2}>
            <Select
              label="排版列数"
              value={String(newCols)}
              data={[
                { value: "2", label: "双排并列" },
                { value: "1", label: "单排" },
              ]}
              onChange={(v) => {
                const cols = Number(v) === 2 ? 2 : 1;
                setNewCols(cols);
                if (cols === 1) setNewColGap(0);
                else if (newColGap <= 0) setNewColGap(2);
                setNewSpecKey(`${Math.round(newWidth)}x${Math.round(newHeight)}_${cols >= 2 ? "double" : "single"}`);
              }}
            />
            <NumberInput
              label="双排列间距 (mm)"
              min={0}
              max={10}
              step={0.5}
              decimalScale={1}
              disabled={newCols < 2}
              value={newCols >= 2 ? newColGap : 0}
              onChange={(v) => setNewColGap(Math.max(0, Number(v) || 0))}
            />
          </SimpleGrid>

          <TextInput
            label="规格唯一编码 (spec_key)"
            description="推荐格式：{宽}x{高}_double 或 {宽}x{高}_single，可附加机器标识"
            value={newSpecKey}
            onChange={(e) => setNewSpecKey(e.currentTarget.value)}
            styles={{ input: { fontFamily: "var(--mono)" } }}
          />

          <SimpleGrid cols={3}>
            <Select
              label="默认协议"
              value={newProtocol}
              data={[
                { value: "tspl", label: "TSPL2" },
                { value: "zpl", label: "ZPL II" },
              ]}
              onChange={(v) => setNewProtocol((v as "tspl" | "zpl") || "tspl")}
            />
            <Select
              label="默认精度 (DPI)"
              value={String(newDpi)}
              data={[
                { value: "203", label: "203 dpi" },
                { value: "300", label: "300 dpi" },
              ]}
              onChange={(v) => setNewDpi(Number(v) === 300 ? 300 : 203)}
            />
            <NumberInput
              label="默认浓度"
              min={1}
              max={15}
              value={newDarkness}
              onChange={(v) => setNewDarkness(Math.min(15, Math.max(1, Number(v) || 8)))}
            />
          </SimpleGrid>

          <Group justify="flex-end" mt="xs">
            <Button variant="default" onClick={() => setAddModalOpen(false)}>
              取消
            </Button>
            <Button loading={creating} onClick={() => void handleCreateProfile()}>
              创建并保存纸卷规格
            </Button>
          </Group>
        </Stack>
      </Modal>
    </div>
  );
}
