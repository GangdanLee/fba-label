import { useEffect, useState } from "react";
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Checkbox,
  Divider,
  Group,
  Modal,
  Paper,
  Stack,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { Pencil, Play, Plus, Trash2 } from "lucide-react";
import * as api from "../api/client";
import type { CarrierRule } from "../types";

interface CarrierRulesModalProps {
  opened: boolean;
  onClose: () => void;
}

const EMPTY_RULE: CarrierRule = {
  id: "",
  name: "",
  shipment_regex: "",
  warehouse_regex: "",
  ctn_regex: "",
  default_rotate: 0,
  enabled: true,
};

export function CarrierRulesModal({ opened, onClose }: CarrierRulesModalProps) {
  const [rules, setRules] = useState<CarrierRule[]>([]);
  const [draft, setDraft] = useState<CarrierRule>({ ...EMPTY_RULE });
  const [sampleFileName, setSampleFileName] = useState("FBA99CUST1_货代箱唛_LAX9.pdf");
  const [sampleText, setSampleText] = useState("SHIP_NO: FBA99CUST1\nDEST: LAX9\nCARTON 2 OF 5");
  const [testResult, setTestResult] = useState<{
    shipment_id: string | null;
    warehouse_code: string | null;
    box_index: number;
    total_boxes: number;
  } | null>(null);
  const [busy, setBusy] = useState(false);

  const loadRules = async () => {
    try {
      const list = await api.fetchCarrierRules();
      setRules(list);
    } catch (err) {
      notifications.show({ title: "加载规则失败", message: (err as Error).message, color: "red" });
    }
  };

  useEffect(() => {
    if (opened) {
      void loadRules();
      setTestResult(null);
    }
  }, [opened]);

  const handleSaveRule = async () => {
    if (!draft.name.trim()) {
      notifications.show({ title: "请填写规则名称", message: "例如：顺丰/美森箱唛规则", color: "orange" });
      return;
    }
    setBusy(true);
    try {
      const saved = await api.saveCarrierRule(draft);
      await loadRules();
      setDraft({ ...EMPTY_RULE });
      notifications.show({ title: "解析规则已保存", message: `规则「${saved.name}」立即对新导入箱唛生效`, color: "green" });
    } catch (err) {
      notifications.show({ title: "保存失败", message: (err as Error).message, color: "red" });
    } finally {
      setBusy(false);
    }
  };

  const handleToggleEnabled = async (rule: CarrierRule, enabled: boolean) => {
    try {
      await api.saveCarrierRule({ ...rule, enabled });
      await loadRules();
    } catch (err) {
      notifications.show({ title: "更新状态失败", message: (err as Error).message, color: "red" });
    }
  };

  const handleDeleteRule = async (rule: CarrierRule) => {
    try {
      await api.deleteCarrierRule(rule.id);
      if (draft.id === rule.id) setDraft({ ...EMPTY_RULE });
      await loadRules();
      notifications.show({ title: "已删除解析规则", message: rule.name, color: "gray" });
    } catch (err) {
      notifications.show({ title: "删除失败", message: (err as Error).message, color: "red" });
    }
  };

  const handleTest = async () => {
    setBusy(true);
    try {
      const effectiveRules = draft.name.trim()
        ? [draft, ...rules.filter((r) => r.id !== draft.id)]
        : rules;
      const res = await api.testCarrierRules({
        sample_text: sampleText,
        file_name: sampleFileName,
        rules: effectiveRules,
      });
      setTestResult(res);
    } catch (err) {
      notifications.show({ title: "正则测试失败", message: (err as Error).message, color: "red" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal opened={opened} onClose={onClose} title="货代箱唛自定义解析规则与测试器" size="lg" centered>
      <Stack gap="sm">
        <Text size="xs" c="dimmed">
          自定义启用的规则将优先于内置通用正则运行；支持一键填写非标准货代字段（如 SHIP_NO / 目的仓 / CARTON X OF Y）并在线测试提取结果。
        </Text>

        <Stack gap={6} mah={190} style={{ overflowY: "auto" }}>
          {rules.map((r) => {
            const isBuiltin = r.id === "rule_default";
            return (
              <Paper key={r.id} withBorder p="xs" radius="sm">
                <Group justify="space-between" wrap="nowrap">
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <Group gap={6}>
                      <Text size="xs" fw={700}>
                        {r.name}
                      </Text>
                      {isBuiltin && (
                        <Badge size="xs" variant="light" color="gray">
                          内置兜底
                        </Badge>
                      )}
                      {!r.enabled && (
                        <Badge size="xs" variant="light" color="orange">
                          已停用
                        </Badge>
                      )}
                    </Group>
                    <Text size="xs" c="dimmed" ff="var(--mono)" truncate>
                      FBA: {r.shipment_regex || "-"} | 仓: {r.warehouse_regex || "-"} | 箱: {r.ctn_regex || "-"}
                    </Text>
                  </div>
                  <Group gap={6} wrap="nowrap">
                    <Checkbox
                      size="xs"
                      aria-label={`启用规则 ${r.name}`}
                      checked={r.enabled}
                      onChange={(e) => void handleToggleEnabled(r, e.currentTarget.checked)}
                    />
                    <ActionIcon
                      size="xs"
                      variant="subtle"
                      aria-label={`编辑规则 ${r.name}`}
                      onClick={() => setDraft({ ...r })}
                    >
                      <Pencil size={13} />
                    </ActionIcon>
                    {!isBuiltin && (
                      <ActionIcon
                        size="xs"
                        variant="subtle"
                        color="red"
                        aria-label={`删除规则 ${r.name}`}
                        onClick={() => void handleDeleteRule(r)}
                      >
                        <Trash2 size={13} />
                      </ActionIcon>
                    )}
                  </Group>
                </Group>
              </Paper>
            );
          })}
        </Stack>

        <Divider label={draft.id ? `编辑规则：${draft.name}` : "新增自定义解析规则"} labelPosition="left" />

        <Group grow>
          <TextInput
            label="规则名称"
            size="xs"
            placeholder="例如：顺丰货代专线规则"
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.currentTarget.value })}
          />
          <TextInput
            label="货件号正则（捕获组1）"
            size="xs"
            placeholder="例如：SHIP_NO[:：\s]*([A-Z0-9]+)"
            styles={{ input: { fontFamily: "var(--mono)" } }}
            value={draft.shipment_regex}
            onChange={(e) => setDraft({ ...draft, shipment_regex: e.currentTarget.value })}
          />
        </Group>

        <Group grow>
          <TextInput
            label="仓点正则（捕获组1）"
            size="xs"
            placeholder="例如：DEST[:：\s]*([A-Z]{3}\d)"
            styles={{ input: { fontFamily: "var(--mono)" } }}
            value={draft.warehouse_regex}
            onChange={(e) => setDraft({ ...draft, warehouse_regex: e.currentTarget.value })}
          />
          <TextInput
            label="箱号正则（捕获组1=第X箱, 组2=总箱数）"
            size="xs"
            placeholder="例如：CARTON\s*(\d+)\s*OF\s*(\d+)"
            styles={{ input: { fontFamily: "var(--mono)" } }}
            value={draft.ctn_regex}
            onChange={(e) => setDraft({ ...draft, ctn_regex: e.currentTarget.value })}
          />
        </Group>

        <Group justify="space-between">
          <Checkbox
            size="xs"
            label="启用此规则"
            checked={draft.enabled}
            onChange={(e) => setDraft({ ...draft, enabled: e.currentTarget.checked })}
          />
          <Group gap="xs">
            {draft.id && (
              <Button size="xs" variant="subtle" onClick={() => setDraft({ ...EMPTY_RULE })}>
                取消编辑
              </Button>
            )}
            <Button size="xs" leftSection={<Plus size={13} />} loading={busy} onClick={() => void handleSaveRule()}>
              保存解析规则
            </Button>
          </Group>
        </Group>

        <Divider label="在线规则试跑调试" labelPosition="left" />

        <TextInput
          label="模拟文件名"
          size="xs"
          value={sampleFileName}
          onChange={(e) => setSampleFileName(e.currentTarget.value)}
        />
        <Textarea
          label="模拟箱唛提取文本"
          size="xs"
          rows={3}
          styles={{ input: { fontFamily: "var(--mono)" } }}
          value={sampleText}
          onChange={(e) => setSampleText(e.currentTarget.value)}
        />

        <Group justify="space-between" align="center">
          <Button size="xs" variant="light" leftSection={<Play size={13} />} loading={busy} onClick={() => void handleTest()}>
            测试提取
          </Button>
          {testResult && (
            <Group gap={6}>
              <Badge color={testResult.shipment_id ? "green" : "red"} variant="light">
                FBA 货件号：{testResult.shipment_id || "未匹配"}
              </Badge>
              <Badge color={testResult.warehouse_code ? "blue" : "gray"} variant="light">
                仓点：{testResult.warehouse_code || "未匹配"}
              </Badge>
              <Badge color="teal" variant="light">
                箱号：{testResult.box_index} / {testResult.total_boxes}
              </Badge>
            </Group>
          )}
        </Group>

        {testResult && !testResult.shipment_id && (
          <Alert color="orange" p={8}>
            <Text size="xs">当前样本文本未提取到 FBA 货件号，可调整上方「货件号正则」后重新测试。</Text>
          </Alert>
        )}
      </Stack>
    </Modal>
  );
}
