import { useState } from "react";
import { Badge, Button, Card, Group, Paper, Stack, Text, TextInput } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { Download, Printer, Search, Trash2 } from "lucide-react";
import * as api from "../api/client";
import { useWorkbenchStore } from "../store/useWorkbenchStore";

export function BatchesView() {
  const { batches, openPrintJob, deleteBatchRecord } = useWorkbenchStore();
  const [query, setQuery] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  const kw = query.trim().toLowerCase();
  const filtered = kw
    ? batches.filter(
        (b) =>
          b.shipment_id.toLowerCase().includes(kw) ||
          b.warehouse_code.toLowerCase().includes(kw) ||
          b.summary.toLowerCase().includes(kw) ||
          b.spec_key.toLowerCase().includes(kw),
      )
    : batches;

  const handleDownload = async (batchId: string) => {
    setBusyId(batchId);
    try {
      const snap = await api.fetchBatchPdf(batchId);
      api.downloadBase64Pdf(snap.pdf_b64, snap.filename);
      notifications.show({ title: "已下载历史 PDF 快照", message: snap.filename, color: "green" });
    } catch (err) {
      notifications.show({ title: "无法下载快照", message: (err as Error).message, color: "red" });
    } finally {
      setBusyId(null);
    }
  };

  const handleReprint = async (b: (typeof batches)[number]) => {
    setBusyId(b.id);
    try {
      const snap = await api.fetchBatchPdf(b.id);
      const validType = (["fnsku", "box_paired", "box_fba_only", "box_carrier_only"].includes(b.batch_type)
        ? b.batch_type
        : "fnsku") as "fnsku" | "box_paired" | "box_fba_only" | "box_carrier_only";
      openPrintJob({
        title: `一键补打 · ${b.shipment_id}`,
        summaryDesc: `[补打] ${b.summary}`,
        specKey: b.spec_key,
        batchType: validType,
        shipmentId: b.shipment_id,
        warehouseCode: b.warehouse_code,
        totalUnitsOrBoxes: b.total_units_or_boxes,
        copiesPerBox: b.copies_per_box,
        orderMode: b.order_mode,
        totalSheets: snap.page_count ?? b.total_units_or_boxes * b.copies_per_box,
        sourceFiles: b.source_files,
        getPdfB64: async () => snap.pdf_b64,
      });
    } catch (err) {
      notifications.show({ title: "补打失败", message: (err as Error).message, color: "red" });
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: 24, maxWidth: 960, margin: "0 auto", width: "100%" }}>
      <Group justify="space-between" mb="md" wrap="nowrap">
        <div>
          <Text fw={700} size="lg">
            历史打印批次与补打记录
          </Text>
          <Text size="sm" c="dimmed">
            记录来自本地 SQLite（`print_batches` 表），支持搜索复盘、快照下载与一键补打。
          </Text>
        </div>
        <Group gap="xs">
          {batches.length > 0 && (
            <TextInput
              size="xs"
              w={220}
              leftSection={<Search size={13} />}
              placeholder="搜索货件号 / SKU / 仓点..."
              value={query}
              onChange={(e) => setQuery(e.currentTarget.value)}
            />
          )}
          <Badge variant="light" color="blue">
            共 {batches.length} 条记录
          </Badge>
        </Group>
      </Group>

      {batches.length === 0 ? (
        <Paper withBorder p="xl" ta="center" radius="md">
          <Text fw={600} mb={4}>
            暂无打印记录
          </Text>
          <Text size="sm" c="dimmed">
            完成产品标签或外箱配对打印任务后，系统会自动归档每次用量、纸卷规格、文件来源与 PDF 快照。
          </Text>
        </Paper>
      ) : filtered.length === 0 ? (
        <Paper withBorder p="lg" ta="center" radius="md">
          <Text size="sm" c="dimmed">
            未找到匹配「{query}」的打印记录。
          </Text>
        </Paper>
      ) : (
        <Stack gap="sm">
          {filtered.map((b) => {
            const hasSnapshot = Boolean(b.snapshot_dir);
            return (
              <Card key={b.id} withBorder radius="md" p="md">
                <Group justify="space-between" align="center" wrap="nowrap">
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <Group gap="xs" mb={4}>
                      <Badge variant="light" color={b.spec_key.includes("100") ? "green" : "blue"}>
                        {b.spec_key}
                      </Badge>
                      <Text fw={700}>{b.shipment_id}</Text>
                      {b.warehouse_code !== "-" && (
                        <Badge variant="outline" color="gray">
                          仓点 {b.warehouse_code}
                        </Badge>
                      )}
                    </Group>
                    <Text size="sm">{b.summary}</Text>
                    <Text size="xs" c="dimmed" mt={4}>
                      渠道：{b.channel} · 数量：{b.total_units_or_boxes} · 套数：{b.copies_per_box} · {b.created_at}
                    </Text>
                  </div>
                  <Group gap="xs" wrap="nowrap">
                    <Button
                      size="xs"
                      variant="light"
                      leftSection={<Printer size={13} />}
                      loading={busyId === b.id}
                      disabled={!hasSnapshot}
                      title={hasSnapshot ? "复用快照弹窗一键补打" : "旧记录未包含 PDF 快照"}
                      onClick={() => void handleReprint(b)}
                    >
                      一键补打
                    </Button>
                    <Button
                      size="xs"
                      variant="default"
                      leftSection={<Download size={13} />}
                      loading={busyId === b.id}
                      disabled={!hasSnapshot}
                      onClick={() => void handleDownload(b.id)}
                    >
                      下载 PDF
                    </Button>
                    <Button
                      size="xs"
                      variant="subtle"
                      color="red"
                      aria-label={`删除记录 ${b.shipment_id}`}
                      onClick={() => void deleteBatchRecord(b.id)}
                    >
                      <Trash2 size={14} />
                    </Button>
                  </Group>
                </Group>
              </Card>
            );
          })}
        </Stack>
      )}
    </div>
  );
}
