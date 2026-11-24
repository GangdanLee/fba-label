import { useEffect, useRef, useState } from "react";
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Checkbox,
  Group,
  Modal,
  NumberInput,
  Paper,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { Download, Plus, Printer, Trash2, Upload } from "lucide-react";
import * as api from "../api/client";
import { useWorkbenchStore } from "../store/useWorkbenchStore";
import type { BatchSkuItem } from "../types";

interface BatchSkuModalProps {
  opened: boolean;
  onClose: () => void;
}

export function BatchSkuModal({ opened, onClose }: BatchSkuModalProps) {
  const { draftSku, colGapMm, getCalibrationForSpec, openPrintJob } = useWorkbenchStore();
  const csvInputRef = useRef<HTMLInputElement>(null);

  const [items, setItems] = useState<BatchSkuItem[]>([
    {
      sku: draftSku.sku || "DEMO-SKU-01",
      fnsku: draftSku.fnsku || "X000DEMO01",
      title: draftSku.title_clean || "New - Demo Product Item",
      qty: 4,
    },
  ]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [pageBreakBetweenSkus, setPageBreakBetweenSkus] = useState(true);
  const [busy, setBusy] = useState(false);
  const [customDirty, setCustomDirty] = useState(false);

  useEffect(() => {
    if (!opened || customDirty) return;
    setItems([
      {
        sku: draftSku.sku || "DEMO-SKU-01",
        fnsku: draftSku.fnsku || "X000DEMO01",
        title: draftSku.title_clean || "New - Demo Product Item",
        qty: 4,
      },
    ]);
  }, [opened, customDirty, draftSku.id, draftSku.sku, draftSku.fnsku, draftSku.title_clean]);

  const specKey = `${draftSku.widthMm}x${draftSku.heightMm}_${draftSku.layoutType}`;
  const prof = getCalibrationForSpec(specKey);
  const effectiveDpi = prof?.dpi ?? 203;
  const effectiveGap = prof?.col_gap_mm ?? colGapMm;
  const effectiveOx = prof?.offset_x_mm ?? 0;
  const effectiveOy = prof?.offset_y_mm ?? 0;

  const validItems = items.filter((it) => it.fnsku.trim().length > 0 && it.qty >= 1);
  const totalLabels = validItems.reduce((sum, it) => sum + (Number(it.qty) || 0), 0);
  const estimatedPages =
    draftSku.layoutType === "single"
      ? totalLabels
      : pageBreakBetweenSkus
        ? validItems.reduce((sum, it) => sum + Math.ceil((Number(it.qty) || 0) / 2), 0)
        : Math.ceil(totalLabels / 2);

  const handleUploadCsv = async (file: File) => {
    setBusy(true);
    try {
      const res = await api.parseFnskuCsv(file);
      setItems(res.items);
      setWarnings(res.warnings || []);
      setCustomDirty(true);
      notifications.show({
        title: "CSV 清单解析成功",
        message: `共导入 ${res.total_skus} 款 SKU · ${res.total_labels} 张标签`,
        color: "green",
      });
    } catch (err) {
      notifications.show({ title: "CSV 解析失败", message: (err as Error).message, color: "red" });
    } finally {
      setBusy(false);
    }
  };

  const updateRow = <K extends keyof BatchSkuItem>(idx: number, key: K, val: BatchSkuItem[K]) => {
    setCustomDirty(true);
    setItems((prev) => prev.map((it, i) => (i === idx ? { ...it, [key]: val } : it)));
  };

  const buildBatchReq = () => ({
    templateElements: draftSku.elements,
    items: validItems.map((it) => ({
      sku: (it.sku || it.fnsku).trim(),
      fnsku: it.fnsku.trim().toUpperCase(),
      title: it.title.trim(),
      qty: Math.max(1, Math.min(9999, Number(it.qty) || 1)),
    })),
    widthMm: draftSku.widthMm,
    heightMm: draftSku.heightMm,
    layoutType: draftSku.layoutType,
    colGapMm: effectiveGap,
    offsetXMm: effectiveOx,
    offsetYMm: effectiveOy,
    dpi: effectiveDpi,
    pageBreakBetweenSkus,
  });

  const handleExportBatchPdf = async () => {
    if (!validItems.length) {
      notifications.show({ title: "清单为空", message: "请至少保留 1 行有效 FNSKU 条目", color: "orange" });
      return;
    }
    setBusy(true);
    try {
      const res = await api.renderFnskuBatch(buildBatchReq());
      api.downloadBase64Pdf(res.pdf_b64, `Batch_SKU_${validItems.length}skus_${res.total_labels}pcs.pdf`);
      notifications.show({
        title: "已导出批量 SKU PDF",
        message: `共 ${res.total_skus} 款 · ${res.total_labels} 张（${res.page_count} 页 · ${res.dpi}dpi）`,
        color: "green",
      });
    } catch (err) {
      notifications.show({ title: "导出失败", message: (err as Error).message, color: "red" });
    } finally {
      setBusy(false);
    }
  };

  const handlePrintBatch = () => {
    if (!validItems.length) {
      notifications.show({ title: "清单为空", message: "请至少保留 1 行有效 FNSKU 条目", color: "orange" });
      return;
    }
    const reqPayload = buildBatchReq();
    const firstLabel = validItems[0].sku || validItems[0].fnsku;
    const shipmentTitle = validItems.length === 1 ? firstLabel : `BATCH-${validItems.length}SKUS`;
    onClose();
    openPrintJob({
      title: `批量打印产品标签 · ${validItems.length} 款 SKU`,
      summaryDesc: `${validItems.length} 款 SKU · 共 ${totalLabels} 张 (${draftSku.widthMm}×${draftSku.heightMm}mm)`,
      specKey,
      batchType: "fnsku",
      shipmentId: shipmentTitle,
      warehouseCode: "-",
      totalUnitsOrBoxes: totalLabels,
      copiesPerBox: 1,
      orderMode: pageBreakBetweenSkus ? `${draftSku.layoutType}_sku_break` : draftSku.layoutType,
      totalSheets: estimatedPages,
      sourceFiles: validItems.map((it) => `${it.sku || it.fnsku}×${it.qty}`),
      getPdfB64: async () => {
        const res = await api.renderFnskuBatch(reqPayload);
        return res.pdf_b64;
      },
    });
  };

  return (
    <Modal opened={opened} onClose={onClose} title="CSV / 多 SKU 批量套打产品标签" size="xl" centered>
      <Stack gap="sm">
        <Group justify="space-between" wrap="wrap">
          <Group gap="xs">
            <Button
              size="xs"
              leftSection={<Upload size={13} />}
              loading={busy}
              onClick={() => csvInputRef.current?.click()}
            >
              上传 CSV 清单
            </Button>
            <input
              ref={csvInputRef}
              type="file"
              accept=".csv,.tsv,.txt,text/csv"
              style={{ display: "none" }}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void handleUploadCsv(file);
                e.target.value = "";
              }}
            />
            <Button
              component="a"
              href={api.getFnskuCsvTemplateUrl()}
              download="fnsku_batch_template.csv"
              size="xs"
              variant="default"
              leftSection={<Download size={13} />}
            >
              下载 CSV 模板
            </Button>
            <Button
              size="xs"
              variant="light"
              leftSection={<Plus size={13} />}
              onClick={() => {
                setCustomDirty(true);
                setItems((prev) => [...prev, { sku: "", fnsku: "", title: "", qty: 2 }]);
              }}
            >
              添加一行
            </Button>
          </Group>

          <Group gap={6}>
            <Badge color="blue" variant="light">
              模板：{draftSku.widthMm}×{draftSku.heightMm}mm {draftSku.layoutType === "double" ? "双排" : "单排"}
            </Badge>
            <Badge color="teal" variant="light">
              共 {validItems.length} 款 · {totalLabels} 张 · {estimatedPages} 页
            </Badge>
          </Group>
        </Group>

        {warnings.length > 0 && (
          <Alert color="orange" p={8}>
            <Text size="xs">{warnings.join("；")}</Text>
          </Alert>
        )}

        <Paper withBorder radius="sm" style={{ maxHeight: 300, overflowY: "auto" }}>
          <Table striped highlightOnHover verticalSpacing={6} horizontalSpacing="xs">
            <Table.Thead>
              <Table.Tr>
                <Table.Th style={{ width: 150 }}>SKU</Table.Th>
                <Table.Th style={{ width: 145 }}>FNSKU 条码 *</Table.Th>
                <Table.Th>商品描述（自动套用样式）</Table.Th>
                <Table.Th style={{ width: 90 }}>数量</Table.Th>
                <Table.Th style={{ width: 42 }} />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {items.map((row, idx) => (
                <Table.Tr key={idx}>
                  <Table.Td>
                    <TextInput
                      size="xs"
                      placeholder="SKU"
                      aria-label={`第 ${idx + 1} 行 SKU`}
                      value={row.sku}
                      onChange={(e) => updateRow(idx, "sku", e.currentTarget.value)}
                    />
                  </Table.Td>
                  <Table.Td>
                    <TextInput
                      size="xs"
                      placeholder="X000..."
                      aria-label={`第 ${idx + 1} 行 FNSKU`}
                      styles={{ input: { fontFamily: "var(--mono)" } }}
                      value={row.fnsku}
                      onChange={(e) => updateRow(idx, "fnsku", e.currentTarget.value)}
                    />
                  </Table.Td>
                  <Table.Td>
                    <TextInput
                      size="xs"
                      placeholder="留空则沿用画布文本"
                      aria-label={`第 ${idx + 1} 行 商品描述`}
                      value={row.title}
                      onChange={(e) => updateRow(idx, "title", e.currentTarget.value)}
                    />
                  </Table.Td>
                  <Table.Td>
                    <NumberInput
                      size="xs"
                      min={1}
                      max={9999}
                      aria-label={`第 ${idx + 1} 行 数量`}
                      value={row.qty}
                      onChange={(v) => updateRow(idx, "qty", Math.max(1, Number(v) || 1))}
                    />
                  </Table.Td>
                  <Table.Td>
                    <ActionIcon
                      size="xs"
                      variant="subtle"
                      color="red"
                      aria-label={`删除第 ${idx + 1} 行`}
                      onClick={() => setItems((prev) => prev.filter((_, i) => i !== idx))}
                    >
                      <Trash2 size={13} />
                    </ActionIcon>
                  </Table.Td>
                </Table.Tr>
              ))}
              {items.length === 0 && (
                <Table.Tr>
                  <Table.Td colSpan={5}>
                    <Text size="xs" c="dimmed" ta="center" py="sm">
                      当前清单为空，请点击「上传 CSV 清单」或「添加一行」。
                    </Text>
                  </Table.Td>
                </Table.Tr>
              )}
            </Table.Tbody>
          </Table>
        </Paper>

        <Group justify="space-between" align="center" wrap="wrap">
          {draftSku.layoutType === "double" ? (
            <Checkbox
              size="xs"
              label="不同 SKU 间强制换行（奇数张右侧留白防错贴）"
              checked={pageBreakBetweenSkus}
              onChange={(e) => setPageBreakBetweenSkus(e.currentTarget.checked)}
            />
          ) : (
            <Text size="xs" c="dimmed">
              当前模板为单排布局，将逐款按顺序连续打印。
            </Text>
          )}

          <Group gap="xs">
            <Button
              size="xs"
              variant="subtle"
              color="gray"
              onClick={() => {
                setCustomDirty(false);
                setItems([]);
              }}
              disabled={items.length === 0}
            >
              清空清单
            </Button>
            <Button size="xs" variant="default" loading={busy} onClick={() => void handleExportBatchPdf()}>
              导出批量 PDF
            </Button>
            <Button size="xs" leftSection={<Printer size={13} />} loading={busy} onClick={handlePrintBatch}>
              打印批量标签
            </Button>
          </Group>
        </Group>
      </Stack>
    </Modal>
  );
}
