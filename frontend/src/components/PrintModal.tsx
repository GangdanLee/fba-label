import { useEffect, useState } from "react";
import { Alert, Badge, Button, Checkbox, Group, Modal, Select, Stack, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import * as api from "../api/client";
import { resolveTargetPrinterKey, useWorkbenchStore } from "../store/useWorkbenchStore";

export function PrintModal() {
  const {
    printModalOpen,
    pendingPrintJob,
    closePrintModal,
    lastPrintedSpec,
    getCalibrationForSpec,
    printers,
    refreshBatches,
  } = useWorkbenchStore();

  const [channel, setChannel] = useState<string>("tspl_raw");
  const [printerOverride, setPrinterOverride] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [dryRun, setDryRun] = useState<boolean>(true);

  const matchedProfile = pendingPrintJob ? getCalibrationForSpec(pendingPrintJob.specKey) : undefined;
  const connType = matchedProfile?.connection_type || "os_queue";
  const protocol = matchedProfile?.protocol || "tspl";
  const dpi = matchedProfile?.dpi || 203;
  const networkHost = (matchedProfile?.network_host || "").trim();
  const networkPort = matchedProfile?.network_port || 9100;

  const defaultQueuePrinter =
    matchedProfile?.printer_name || printers.find((d) => d.is_recommended)?.name || printers[0]?.name || "";
  const selectedPrinter = connType === "network_tcp" ? "" : printerOverride || defaultQueuePrinter;
  const selectedPrinterDevice = printers.find((d) => d.name === selectedPrinter);
  const isPrinterReady = connType === "network_tcp" ? Boolean(networkHost) : selectedPrinterDevice?.status === "ready";

  useEffect(() => {
    if (!printModalOpen) return;
    setChannel(matchedProfile?.preferred_channel || "tspl_raw");
    setPrinterOverride(matchedProfile?.printer_name || printers.find((d) => d.is_recommended)?.name || printers[0]?.name || "");
    const readyNow =
      connType === "network_tcp"
        ? Boolean(networkHost)
        : Boolean(
            printers.find(
              (d) =>
                d.name ===
                (matchedProfile?.printer_name || printers.find((x) => x.is_recommended)?.name || printers[0]?.name || ""),
            )?.status === "ready",
          );
    setDryRun(!readyNow);
  }, [printModalOpen, matchedProfile?.preferred_channel, matchedProfile?.printer_name, connType, networkHost, printers]);

  if (!pendingPrintJob) return null;

  const lastProfile = getCalibrationForSpec(lastPrintedSpec);
  const currentEffectiveProf = matchedProfile
    ? { ...matchedProfile, printer_name: connType === "os_queue" ? selectedPrinter : matchedProfile.printer_name }
    : undefined;
  const sameDevice = resolveTargetPrinterKey(lastProfile, printers) === resolveTargetPrinterKey(currentEffectiveProf, printers);
  const isSpecSwitch = lastPrintedSpec !== pendingPrintJob.specKey && sameDevice;
  const isMultiPrinterFree = lastPrintedSpec !== pendingPrintJob.specKey && !sameDevice;
  const isPdfOnly = channel === "pdf_export";
  const protoLabel = protocol === "zpl" ? "ZPL II" : "TSPL2";

  const handleConfirm = async () => {
    setBusy(true);
    try {
      const pdfB64 = await pendingPrintJob.getPdfB64();
      if (isPdfOnly) {
        api.downloadBase64Pdf(pdfB64, `${pendingPrintJob.shipmentId}_${pendingPrintJob.specKey}.pdf`);
      }
      const res = await api.executePrint({
        pdf_b64: pdfB64,
        spec_key: pendingPrintJob.specKey,
        channel,
        printer_name: selectedPrinter,
        dry_run: isPdfOnly ? false : dryRun,
        protocol,
        dpi,
        connection_type: connType,
        network_host: networkHost,
        network_port: networkPort,
        batch: {
          batch_type: pendingPrintJob.batchType,
          shipment_id: pendingPrintJob.shipmentId,
          warehouse_code: pendingPrintJob.warehouseCode,
          spec_key: pendingPrintJob.specKey,
          total_units_or_boxes: pendingPrintJob.totalUnitsOrBoxes,
          copies_per_box: pendingPrintJob.copiesPerBox,
          order_mode: pendingPrintJob.orderMode,
          channel,
          summary: pendingPrintJob.summaryDesc,
          source_files: pendingPrintJob.sourceFiles,
        },
      });
      if (res.printer_result?.ok === false) {
        const errMsg = String(
          res.printer_result.hint || res.printer_result.error || res.printer_result.stderr || "打印机返回失败状态",
        );
        notifications.show({ title: "打印任务发送失败", message: errMsg, color: "red" });
        return;
      }
      await useWorkbenchStore.getState().setLastPrintedSpec(res.last_printed_spec);
      await refreshBatches();
      closePrintModal();
      const isOfflineDryrun = !isPdfOnly && (Boolean(res.printer_result?.offline_dryrun) || dryRun);
      const resProto = res.protocol === "zpl" ? "ZPL II" : "TSPL2";
      const resDpi = res.dpi || dpi;
      const pagesDone = res.page_count || pendingPrintJob.totalSheets;
      notifications.show({
        title: "打印任务已处理并归档",
        message: isPdfOnly
          ? `已导出标准 PDF（${pagesDone} 页）并写入打印记录（支持后续一键补打）`
          : channel === "os_driver" && !isOfflineDryrun
            ? `已通过系统原生打印驱动提交（共 ${pagesDone} 页）`
            : isOfflineDryrun
              ? `已离线干跑校验（未发送实体机）：${resProto} (${resDpi}dpi) ${res.tspl_commands} 页 / ${(res.tspl_bytes_len / 1024).toFixed(1)} KB`
              : `${resProto} (${resDpi}dpi) 指令发送成功 (${res.tspl_commands} 页 / ${(res.tspl_bytes_len / 1024).toFixed(1)} KB)`,
        color: "green",
      });
    } catch (err) {
      notifications.show({ title: "打印执行失败", message: (err as Error).message, color: "red" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal opened={printModalOpen} onClose={closePrintModal} title={pendingPrintJob.title} centered>
      <Stack gap="sm">
        {isSpecSwitch && (
          <Alert color="yellow" title="换纸提醒">
            同一台打印机上次规格为 <strong>{lastPrintedSpec}</strong>，本次需要 <strong>{pendingPrintJob.specKey}</strong>
            ，请确认已更换对应纸卷并调整导向片。
          </Alert>
        )}

        {isMultiPrinterFree && (
          <Alert color="teal" title="已分配至独立打印机（免换纸）">
            不同纸卷规格已各自绑定独立输出设备，无需频繁更换纸卷。
          </Alert>
        )}

        {!isPrinterReady && !isPdfOnly && (
          <Alert color="orange" title="离线干跑保护已开启">
            {connType === "network_tcp"
              ? "当前选择的网口 TCP 9100 模式尚未配置打印机 IP 地址，已默认开启离线干跑保护。"
              : selectedPrinterDevice
                ? `当前打印机 ${selectedPrinterDevice.name} 处于「${
                    selectedPrinterDevice.status === "offline" ? "离线" : selectedPrinterDevice.status
                  }」不可用状态${selectedPrinterDevice.status_detail ? `（${selectedPrinterDevice.status_detail}）` : ""}，已默认开启离线干跑保护，仅校验不发送至实体打印机。`
                : "未检测到就绪的物理打印机，已默认开启离线干跑保护，仅校验不发送至实体打印机。"}
          </Alert>
        )}

        <Group justify="space-between">
          <Text size="sm" c="dimmed">
            打印内容
          </Text>
          <Text size="sm" fw={600}>
            {pendingPrintJob.summaryDesc}
          </Text>
        </Group>

        <Group justify="space-between">
          <Text size="sm" c="dimmed">
            规格与协议精度
          </Text>
          <Group gap={6}>
            <Badge color="teal" variant="light">
              {protoLabel} · {dpi}dpi
            </Badge>
            <Badge color="blue" variant="light">
              {pendingPrintJob.specKey}
            </Badge>
          </Group>
        </Group>

        <Group justify="space-between">
          <Text size="sm" c="dimmed">
            预计出纸张数
          </Text>
          <Text size="sm" fw={700} ff="var(--mono)">
            {pendingPrintJob.totalSheets} 页
          </Text>
        </Group>

        {connType === "network_tcp" ? (
          <Group justify="space-between">
            <Text size="sm" c="dimmed">
              网口直连目标
            </Text>
            <Badge color={networkHost ? "indigo" : "gray"} variant="light" ff="var(--mono)">
              {networkHost ? `TCP ${networkHost}:${networkPort}` : "未配置 IP"}
            </Badge>
          </Group>
        ) : (
          printers.length > 0 && (
            <Select
              label="目标打印机"
              value={selectedPrinter}
              onChange={(v) => setPrinterOverride(v || "")}
              data={printers.map((d) => ({
                value: d.name,
                label: `${d.name} (${d.status === "offline" ? "离线" : d.status === "disabled" ? "停用" : "就绪"})`,
              }))}
            />
          )
        )}

        <Select
          label="执行通道"
          value={channel}
          onChange={(v) => setChannel(v || "tspl_raw")}
          data={[
            { value: "tspl_raw", label: `裸指令直出 + ${protoLabel} 干跑校验` },
            { value: "pdf_export", label: "导出标准 PDF 文件并归档" },
            ...(connType === "os_queue" ? [{ value: "os_driver", label: "通过系统原生驱动打印" }] : []),
          ]}
        />

        {!isPdfOnly && (
          <Checkbox
            label={`仅离线干跑校验（校验 ${protoLabel} 指令流并写入打印记录，不发送至实体打印机）`}
            checked={dryRun}
            onChange={(e) => setDryRun(e.currentTarget.checked)}
          />
        )}

        <Group justify="flex-end" mt="md">
          <Button variant="default" onClick={closePrintModal}>
            取消
          </Button>
          <Button loading={busy} onClick={() => void handleConfirm()}>
            确认执行并记入批次
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
