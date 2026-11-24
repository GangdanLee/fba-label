import { useRef, useState } from "react";
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Checkbox,
  Divider,
  Group,
  Modal,
  NumberInput,
  Paper,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Tabs,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { ArrowDown, ArrowUp, Image as ImageIcon, Plus, Redo2, Trash2, Undo2, Upload } from "lucide-react";
import * as api from "../api/client";
import classes from "../styles/Studio.module.css";
import { useWorkbenchStore } from "../store/useWorkbenchStore";
import type { CanvasElement } from "../types";
import { encodeCode128B, evaluateBarcodeDots } from "../utils/code128";
import { BatchSkuModal } from "./BatchSkuModal";

function renderSvgElement(
  el: CanvasElement,
  pxPerMm: number,
  isSelected: boolean,
  onMouseDown?: (e: React.MouseEvent) => void,
) {
  const x = el.x * pxPerMm;
  const y = el.y * pxPerMm;
  const w = el.w * pxPerMm;
  const h = el.h * pxPerMm;
  const cx = x + w / 2;
  const cy = y + h / 2;
  const transform = el.rotate ? `rotate(${el.rotate} ${cx} ${cy})` : undefined;

  let body: React.ReactNode = null;
  if (el.type === "barcode1d") {
    const enc = encodeCode128B(el.code || "X000DEMO01");
    const showText = el.showText !== false;
    const textH = showText ? ((el.fontSize || 8.5) * pxPerMm * 25.4) / 72 * 1.35 : 0;
    const barH = Math.max(4, h - textH);
    const modPx = w / (enc.totalWidth + 16);
    const barOffX = 8 * modPx;
    body = (
      <g>
        {enc.bars.map((b, i) => (
          <rect key={i} x={x + barOffX + b.x * modPx} y={y} width={Math.max(0.8, b.w * modPx)} height={barH} fill="#000" />
        ))}
        {showText && (
          <text
            x={cx}
            y={y + h - 1}
            textAnchor="middle"
            fontFamily="ui-monospace, monospace"
            fontWeight="700"
            fontSize={((el.fontSize || 8.5) * pxPerMm * 25.4) / 72}
            fill="#000"
          >
            {enc.code}
          </text>
        )}
      </g>
    );
  } else if (el.type === "text") {
    const fpx = ((el.fontSize || 7.5) * pxPerMm * 25.4) / 72;
    const rawParas = (el.text || "").split("\n");
    const wrappedLines: string[] = [];
    for (const para of rawParas) {
      if (!para) {
        wrappedLines.push("");
        continue;
      }
      const tokens = para.match(/[A-Za-z0-9\-_/.:()]+|\s+|./g) || [para];
      const measureWidth = (s: string) => {
        let total = 0;
        for (const ch of s) total += (ch.charCodeAt(0) > 127 ? 1.0 : 0.54) * fpx;
        return total;
      };
      let cur = "";
      let curWidth = 0;
      for (const tok of tokens) {
        const tokW = measureWidth(tok);
        if (curWidth + tokW <= w || (!cur && tokW <= w)) {
          cur += tok;
          curWidth += tokW;
        } else if (tokW <= w) {
          if (cur) wrappedLines.push(cur.replace(/\s+$/, ""));
          const trimmed = tok.replace(/^\s+/, "");
          cur = trimmed;
          curWidth = measureWidth(trimmed);
        } else {
          if (cur && /^[A-Za-z0-9]/.test(tok)) {
            wrappedLines.push(cur.replace(/\s+$/, ""));
            cur = "";
            curWidth = 0;
          }
          for (const ch of tok) {
            const chW = (ch.charCodeAt(0) > 127 ? 1.0 : 0.54) * fpx;
            if (curWidth + chW > w && cur) {
              wrappedLines.push(cur);
              cur = ch;
              curWidth = chW;
            } else {
              cur += ch;
              curWidth += chW;
            }
          }
        }
      }
      if (cur) wrappedLines.push(cur);
    }
    const anchor = el.align === "center" ? "middle" : el.align === "right" ? "end" : "start";
    const tx = el.align === "center" ? cx : el.align === "right" ? x + w : x;
    body = (
      <g>
        {wrappedLines.map((ln, idx) => (
          <text
            key={idx}
            x={tx}
            y={y + fpx * 0.9 + idx * fpx * (el.lineHeight || 1.2)}
            textAnchor={anchor}
            fontWeight={el.bold ? "700" : "400"}
            fontStyle={el.italic ? "italic" : "normal"}
            fontSize={fpx}
            fill="#000"
          >
            {ln}
          </text>
        ))}
      </g>
    );
  } else if (el.type === "rect") {
    body = (
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        fill={el.fill || "none"}
        stroke="#000"
        strokeWidth={(el.strokeWidth || 0.4) * pxPerMm}
        strokeDasharray={el.dashed ? "4 3" : undefined}
      />
    );
  } else if (el.type === "mask") {
    body = <rect x={x} y={y} width={w} height={h} fill="#ffffff" stroke="#cbd5e1" strokeDasharray="3 2" strokeWidth={1} />;
  } else if (el.type === "line") {
    body = (
      <line
        x1={x}
        y1={cy}
        x2={x + w}
        y2={cy}
        stroke="#000"
        strokeWidth={(el.strokeWidth || 0.4) * pxPerMm}
        strokeDasharray={el.dashed ? "4 3" : undefined}
      />
    );
  } else if (el.type === "qrcode") {
    const qrUrl = `/api/fnsku/qrcode-preview?code=${encodeURIComponent(el.code || "DEMO")}`;
    body = (
      <g>
        <rect x={x} y={y} width={w} height={h} fill="#ffffff" stroke="#cbd5e1" strokeWidth={0.8} />
        <image
          href={qrUrl}
          x={x}
          y={y}
          width={w}
          height={h}
          preserveAspectRatio="xMidYMid meet"
          style={{ pointerEvents: "none" }}
        />
      </g>
    );
  } else if (el.type === "image") {
    body = el.imageDataUrl ? (
      <image
        href={el.imageDataUrl}
        x={x}
        y={y}
        width={w}
        height={h}
        preserveAspectRatio="xMidYMid meet"
        style={{ pointerEvents: "none" }}
      />
    ) : (
      <rect x={x} y={y} width={w} height={h} fill="#f8fafc" stroke="#94a3b8" strokeDasharray="3 2" strokeWidth={1} />
    );
  }

  return (
    <g
      key={el.id}
      data-el-id={el.id}
      transform={transform}
      style={{ cursor: el.locked ? "not-allowed" : "move" }}
      onMouseDown={onMouseDown}
    >
      <rect x={x} y={y} width={w} height={h} fill="transparent" />
      {body}
      {isSelected && (
        <rect
          x={x - 1}
          y={y - 1}
          width={w + 2}
          height={h + 2}
          fill="none"
          stroke="#2563eb"
          strokeWidth={1.5}
          strokeDasharray="3 2"
        />
      )}
    </g>
  );
}

export function EditorStudio() {
  const {
    editorMode,
    draftSku,
    editorDraftDirty,
    editorDraftRestored,
    boxOverlayElements,
    selectedElementId,
    historyPast,
    historyFuture,
    zoom,
    snapGrid,
    showGrid,
    editorSim203,
    editorSim203B64,
    fnskuQty,
    colGapMm,
    templates,
    pairing,
    activeGroupId,
    activeBoxIndex,
    setEditorMode,
    setActiveTab,
    selectElement,
    undo,
    redo,
    setZoom,
    setSnapGrid,
    setShowGrid,
    setEditorSim203,
    setFnskuQty,
    updateActiveElements,
    moveElementLayer,
    clearBoxOverlays,
    getCalibrationForSpec,
    updateDraftMeta,
    selectTemplate,
    createNewTemplate,
    saveDraftTemplate,
    discardEditorDraft,
    removeTemplate,
    importProductPdf,
    openPrintJob,
  } = useWorkbenchStore();

  const pdfImportRef = useRef<HTMLInputElement>(null);
  const imgImportRef = useRef<HTMLInputElement>(null);
  const propDirtyRef = useRef(false);
  const [newModalOpen, setNewModalOpen] = useState(false);
  const [batchOpen, setBatchOpen] = useState(false);
  const [newSku, setNewSku] = useState("NEW-SKU-01");
  const [newFnsku, setNewFnsku] = useState("X000NEW001");
  const [newPreset, setNewPreset] = useState("50x30_double");
  const [newW, setNewW] = useState(50);
  const [newH, setNewH] = useState(30);
  const [newLayout, setNewLayout] = useState<"double" | "single">("double");

  const isSku = editorMode === "sku_50x30";
  const wMm = isSku ? draftSku.widthMm : 100;
  const hMm = isSku ? draftSku.heightMm : 100;
  const activeSpecKey = isSku ? `${draftSku.widthMm}x${draftSku.heightMm}_${draftSku.layoutType}` : "100x100_single";
  const activeDpi = (getCalibrationForSpec(activeSpecKey)?.dpi ?? 203) as 203 | 300;
  const elements = isSku ? draftSku.elements : boxOverlayElements;
  const selectedEl = elements.find((e) => e.id === selectedElementId) || null;

  const activeGroup = pairing.groups.find((g) => g.shipment_id === activeGroupId) || pairing.groups[0] || null;
  const activePair = activeGroup?.pairs.find((p) => p.box_index === activeBoxIndex) || activeGroup?.pairs[0] || null;
  const activeBoxBg = activePair?.fba_box?.clean_preview_b64 || "";

  const recordContinuous = () => {
    if (!propDirtyRef.current) {
      propDirtyRef.current = true;
      return true;
    }
    return false;
  };

  const handleImportImage = (file: File) => {
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = typeof reader.result === "string" ? reader.result : "";
      if (!dataUrl) return;
      const id = `el_${Date.now()}`;
      const size = Math.min(24, wMm - 6, hMm - 6);
      const el: CanvasElement = {
        id,
        type: "image",
        name: file.name.replace(/\.[^.]+$/, "").slice(0, 18) || "本地图片",
        x: 4,
        y: 4,
        w: Math.max(8, size),
        h: Math.max(8, size),
        imageDataUrl: dataUrl,
      };
      updateActiveElements((els) => [...els, el], true);
      selectElement(id);
    };
    reader.readAsDataURL(file);
  };

  const basePxPerMm = wMm >= 80 ? 3.8 : 6.4;
  const pxPerMm = basePxPerMm * zoom;
  const cw = Math.round(wMm * pxPerMm);
  const ch = Math.round(hMm * pxPerMm);

  const zooms = [0.75, 1, 1.25, 1.65, 2];
  const zIdx = zooms.findIndex((z) => Math.abs(z - zoom) < 0.02);

  const addElement = (kind: CanvasElement["type"], presetText?: string) => {
    const id = `el_${Date.now()}`;
    let el: CanvasElement;
    if (kind === "barcode1d") {
      el = { id, type: "barcode1d", name: "条形码", x: 3, y: 2, w: Math.min(44, wMm - 6), h: 14, code: draftSku.fnsku || "X000DEMO01", showText: true, fontSize: 8.5 };
    } else if (kind === "qrcode") {
      el = { id, type: "qrcode", name: "二维码", x: 6, y: 6, w: 14, h: 14, code: draftSku.fnsku || "DEMO" };
    } else if (kind === "rect") {
      el = { id, type: "rect", name: "矩形边框", x: 2, y: 2, w: wMm - 4, h: hMm - 4, strokeWidth: 0.4 };
    } else if (kind === "mask") {
      el = { id, type: "mask", name: "白色遮挡", x: 6, y: 6, w: 20, h: 10, fill: "#ffffff" };
    } else if (kind === "line") {
      el = { id, type: "line", name: "分割线", x: 3, y: hMm / 2, w: wMm - 6, h: 1, strokeWidth: 0.4 };
    } else {
      el = {
        id,
        type: "text",
        name: presetText || "文字",
        x: 4,
        y: Math.max(4, hMm - 8),
        w: Math.min(34, wMm - 8),
        h: 5,
        text: presetText || "示例文字",
        fontSize: 8,
        bold: presetText === "Made in China",
        lineHeight: 1.2,
        align: "left",
      };
    }
    updateActiveElements((els) => [...els, el], true);
    selectElement(id);
  };

  const handleDragStart = (el: CanvasElement, ev: React.MouseEvent) => {
    ev.stopPropagation();
    selectElement(el.id);
    if (el.locked) return;
    const startX = ev.clientX;
    const startY = ev.clientY;
    const origX = el.x;
    const origY = el.y;
    let recorded = false;

    const onMove = (m: MouseEvent) => {
      if (!recorded && (Math.abs(m.clientX - startX) > 2 || Math.abs(m.clientY - startY) > 2)) {
        recorded = true;
        useWorkbenchStore.getState().pushHistory();
      }
      const dxMm = (m.clientX - startX) / pxPerMm;
      const dyMm = (m.clientY - startY) / pxPerMm;
      let nx = origX + dxMm;
      let ny = origY + dyMm;
      if (snapGrid) {
        nx = Math.round(nx * 2) / 2;
        ny = Math.round(ny * 2) / 2;
      }
      nx = Math.max(0, Math.min(wMm - el.w, Math.round(nx * 10) / 10));
      ny = Math.max(0, Math.min(hMm - el.h, Math.round(ny * 10) / 10));
      updateActiveElements((arr) => arr.map((item) => (item.id === el.id ? { ...item, x: nx, y: ny } : item)), false);
    };

    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  const alignSelected = (pos: "left" | "centerX" | "right" | "top" | "centerY" | "bottom") => {
    if (!selectedEl) return;
    updateActiveElements(
      (arr) =>
        arr.map((item) => {
          if (item.id !== selectedEl.id) return item;
          if (pos === "left") return { ...item, x: 1.5 };
          if (pos === "centerX") return { ...item, x: Math.round(((wMm - item.w) / 2) * 10) / 10 };
          if (pos === "right") return { ...item, x: Math.round((wMm - item.w - 1.5) * 10) / 10 };
          if (pos === "top") return { ...item, y: 1.5 };
          if (pos === "centerY") return { ...item, y: Math.round(((hMm - item.h) / 2) * 10) / 10 };
          return { ...item, y: Math.round((hMm - item.h - 1.5) * 10) / 10 };
        }),
      true,
    );
  };

  const handleExportPdf = async () => {
    const specKey = `${draftSku.widthMm}x${draftSku.heightMm}_${draftSku.layoutType}`;
    const prof = getCalibrationForSpec(specKey);
    const res = await api.renderFnskuPreview({
      elements: draftSku.elements,
      widthMm: draftSku.widthMm,
      heightMm: draftSku.heightMm,
      layoutType: draftSku.layoutType,
      colGapMm: prof?.col_gap_mm ?? colGapMm,
      offsetXMm: prof?.offset_x_mm ?? 0,
      offsetYMm: prof?.offset_y_mm ?? 0,
      qty: fnskuQty,
      dpi: prof?.dpi ?? 203,
    });
    api.downloadBase64Pdf(res.pdf_b64, `${draftSku.sku}_${fnskuQty}pcs.pdf`);
    notifications.show({ title: "已导出矢量 PDF", message: `共 ${res.page_count} 页`, color: "green" });
  };

  const handlePrintProduct = () => {
    const specKey = `${draftSku.widthMm}x${draftSku.heightMm}_${draftSku.layoutType}`;
    const prof = getCalibrationForSpec(specKey);
    openPrintJob({
      title: `打印产品标签 · ${draftSku.sku}`,
      summaryDesc: `${draftSku.sku} · ${fnskuQty} 张`,
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
        const res = await api.renderFnskuPreview({
          elements: draftSku.elements,
          widthMm: draftSku.widthMm,
          heightMm: draftSku.heightMm,
          layoutType: draftSku.layoutType,
          colGapMm: prof?.col_gap_mm ?? colGapMm,
          offsetXMm: prof?.offset_x_mm ?? 0,
          offsetYMm: prof?.offset_y_mm ?? 0,
          qty: fnskuQty,
          dpi: prof?.dpi ?? 203,
        });
        return res.pdf_b64;
      },
    });
  };

  return (
    <div className={classes.threePaneStudio}>
      {/* 左栏：新建标签 + 添加元素 / 图层 / 我的模板 */}
      <div className={classes.leftPanelNarrow}>
        <Group justify="space-between" p="10px 12px" style={{ borderBottom: "1px solid var(--border)" }}>
          <Text size="xs" fw={700}>
            标签模板
          </Text>
          <Button size="xs" leftSection={<Plus size={13} />} onClick={() => setNewModalOpen(true)}>
            新建标签
          </Button>
        </Group>

        <Tabs defaultValue="elements" style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
          <Tabs.List grow>
            <Tabs.Tab value="elements" fz="xs">
              添加元素
            </Tabs.Tab>
            <Tabs.Tab value="layers" fz="xs">
              图层列表
            </Tabs.Tab>
            <Tabs.Tab value="templates" fz="xs">
              我的模板
            </Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="elements" p="sm" style={{ overflowY: "auto", flex: 1 }}>
            {isSku && (
              <>
                <Button
                  fullWidth
                  size="xs"
                  variant="light"
                  mb="sm"
                  leftSection={<Upload size={13} />}
                  onClick={() => pdfImportRef.current?.click()}
                >
                  导入本地亚马逊产品标 PDF
                </Button>
                <input
                  ref={pdfImportRef}
                  type="file"
                  accept=".pdf,application/pdf"
                  style={{ display: "none" }}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) void importProductPdf(file);
                    e.target.value = "";
                  }}
                />
              </>
            )}

            <Text size="xs" fw={700} c="dimmed" mb={6}>
              基础元素
            </Text>
            <SimpleGrid cols={2} spacing={6} mb="md">
              <Button size="xs" variant="default" onClick={() => addElement("text", "产品描述")}>
                文本
              </Button>
              <Button size="xs" variant="default" onClick={() => addElement("barcode1d")}>
                条形码
              </Button>
              <Button size="xs" variant="default" onClick={() => addElement("qrcode")}>
                二维码
              </Button>
              <Button size="xs" variant="default" onClick={() => addElement("rect")}>
                矩形边框
              </Button>
              <Button size="xs" variant="default" onClick={() => addElement("mask")}>
                白色遮挡
              </Button>
              <Button size="xs" variant="default" onClick={() => addElement("line")}>
                分割线
              </Button>
              <Button size="xs" variant="default" leftSection={<ImageIcon size={12} />} onClick={() => imgImportRef.current?.click()}>
                本地图片
              </Button>
            </SimpleGrid>
            <input
              ref={imgImportRef}
              type="file"
              accept="image/png,image/jpeg,image/webp,image/svg+xml"
              style={{ display: "none" }}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleImportImage(file);
                e.target.value = "";
              }}
            />

            <Text size="xs" fw={700} c="dimmed" mb={6}>
              合规常用标识
            </Text>
            <SimpleGrid cols={2} spacing={6}>
              <Button size="xs" variant="default" onClick={() => addElement("text", "Made in China")}>
                Made in China
              </Button>
              <Button size="xs" variant="default" onClick={() => addElement("text", "New")}>
                New 成色
              </Button>
              <Button size="xs" variant="default" onClick={() => addElement("text", "CE")}>
                CE 标志
              </Button>
              <Button size="xs" variant="default" onClick={() => addElement("text", "UKCA")}>
                UKCA 标
              </Button>
            </SimpleGrid>
          </Tabs.Panel>

          <Tabs.Panel value="layers" p="sm" style={{ overflowY: "auto", flex: 1 }}>
            <Stack gap={6}>
              {!elements.length && (
                <Text size="xs" c="dimmed" ta="center" py="md">
                  当前画布暂无图层，请从“添加元素”插入
                </Text>
              )}
              {[...elements]
                .map((el, idx) => ({ el, idx }))
                .reverse()
                .map(({ el, idx }) => (
                  <Paper
                    key={el.id}
                    withBorder
                    p={7}
                    radius="sm"
                    style={{
                      cursor: "pointer",
                      borderColor: el.id === selectedElementId ? "var(--accent)" : undefined,
                      background: el.id === selectedElementId ? "var(--accent-soft)" : undefined,
                    }}
                    onClick={() => selectElement(el.id)}
                  >
                    <Group justify="space-between" wrap="nowrap" gap={4}>
                      <Text size="xs" fw={600} truncate style={{ flex: 1, minWidth: 0 }}>
                        {el.name || el.type}
                      </Text>
                      <Group gap={2} wrap="nowrap">
                        <ActionIcon
                          size="xs"
                          variant="subtle"
                          aria-label="上移一层"
                          disabled={idx === elements.length - 1}
                          onClick={(e) => {
                            e.stopPropagation();
                            moveElementLayer(el.id, "up");
                          }}
                        >
                          <ArrowUp size={12} />
                        </ActionIcon>
                        <ActionIcon
                          size="xs"
                          variant="subtle"
                          aria-label="下移一层"
                          disabled={idx === 0}
                          onClick={(e) => {
                            e.stopPropagation();
                            moveElementLayer(el.id, "down");
                          }}
                        >
                          <ArrowDown size={12} />
                        </ActionIcon>
                        <Badge size="xs" variant="light">
                          {el.type}
                        </Badge>
                      </Group>
                    </Group>
                  </Paper>
                ))}
            </Stack>
          </Tabs.Panel>

          <Tabs.Panel value="templates" p="sm" style={{ overflowY: "auto", flex: 1 }}>
            {templates.length === 0 ? (
              <Text size="xs" c="dimmed" ta="center" mt="md">
                暂无已保存模板。点击右下角「保存模板」即可保存到本地 SQLite 库。
              </Text>
            ) : (
              <Stack gap={6}>
                {templates.map((tpl) => (
                  <Paper
                    key={tpl.id}
                    withBorder
                    p={8}
                    radius="sm"
                    style={{
                      cursor: "pointer",
                      borderColor: tpl.id === draftSku.id ? "var(--accent)" : undefined,
                    }}
                    onClick={() => selectTemplate(tpl)}
                  >
                    <Group justify="space-between" wrap="nowrap">
                      <div style={{ minWidth: 0 }}>
                        <Text size="xs" fw={700} truncate>
                          {tpl.sku}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {tpl.widthMm}×{tpl.heightMm}mm · {tpl.layoutType === "double" ? "双排" : "单排"}
                        </Text>
                      </div>
                      <ActionIcon
                        size="xs"
                        color="red"
                        variant="subtle"
                        aria-label={`删除模板 ${tpl.sku}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          void removeTemplate(tpl.id);
                        }}
                      >
                        <Trash2 size={13} />
                      </ActionIcon>
                    </Group>
                  </Paper>
                ))}
              </Stack>
            )}
          </Tabs.Panel>
        </Tabs>
      </div>

      {/* 中栏自由画布 */}
      <div className={classes.centerStage}>
        {/* 双胶囊画布工具栏 */}
        <div className={classes.stageTopbar}>
          <div className={classes.stageFloatBar}>
            <SegmentedControl
              size="xs"
              value={editorMode}
              onChange={(v) => setEditorMode(v as typeof editorMode)}
              data={[
                { value: "sku_50x30", label: `${draftSku.widthMm}×${draftSku.heightMm} 模板` },
                { value: "box_100x100", label: "100×100 外箱" },
              ]}
            />
            <Divider orientation="vertical" my={6} />
            <ActionIcon size="sm" variant="subtle" aria-label="撤销上一步" disabled={!historyPast.length} onClick={undo}>
              <Undo2 size={14} />
            </ActionIcon>
            <ActionIcon size="sm" variant="subtle" aria-label="重做操作" disabled={!historyFuture.length} onClick={redo}>
              <Redo2 size={14} />
            </ActionIcon>
            <Divider orientation="vertical" my={6} />
            <Checkbox label="吸附" size="xs" checked={snapGrid} onChange={(e) => setSnapGrid(e.currentTarget.checked)} />
            <Checkbox label="网格" size="xs" checked={showGrid} onChange={(e) => setShowGrid(e.currentTarget.checked)} />
          </div>

          <div className={classes.stageFloatBar}>
            <ActionIcon
              size="sm"
              variant="subtle"
              aria-label="缩小画布"
              disabled={zIdx <= 0}
              onClick={() => zIdx > 0 && setZoom(zooms[zIdx - 1])}
            >
              −
            </ActionIcon>
            <Button
              size="xs"
              variant="subtle"
              px={6}
              styles={{ root: { fontFamily: "var(--mono)" } }}
              onClick={() => setZoom(1.25)}
              aria-label="重置缩放为 125%"
            >
              {Math.round(zoom * 100)}%
            </Button>
            <ActionIcon
              size="sm"
              variant="subtle"
              aria-label="放大画布"
              disabled={zIdx >= zooms.length - 1}
              onClick={() => zIdx < zooms.length - 1 && setZoom(zooms[zIdx + 1])}
            >
              +
            </ActionIcon>
          </div>
        </div>

        {isSku && (editorDraftRestored || editorDraftDirty) && (
          <Alert
            color={editorDraftRestored ? "teal" : "blue"}
            variant="light"
            mx="md"
            mt={6}
            p="6px 10px"
            styles={{ message: { width: "100%" } }}
          >
            <Group justify="space-between" wrap="nowrap" gap="xs">
              <Text size="xs" fw={600}>
                {editorDraftRestored
                  ? `已自动恢复上次未保存的草稿：${draftSku.sku}`
                  : `画布已实时暂存本地草稿（${draftSku.sku}），刷新页面不丢失`}
              </Text>
              <Group gap={6} wrap="nowrap">
                <Button size="compact-xs" variant="light" color="green" onClick={() => void saveDraftTemplate()}>
                  立即保存至模板库
                </Button>
                <Button size="compact-xs" variant="subtle" color="gray" onClick={discardEditorDraft}>
                  放弃草稿
                </Button>
              </Group>
            </Group>
          </Alert>
        )}

        <div className={classes.edCanvasStage}>
          {selectedEl && (
            <div className={classes.floatingCtxBar}>
              <Button size="compact-xs" variant="subtle" onClick={() => alignSelected("left")}>
                左
              </Button>
              <Button size="compact-xs" variant="subtle" onClick={() => alignSelected("centerX")}>
                居中
              </Button>
              <Button size="compact-xs" variant="subtle" onClick={() => alignSelected("right")}>
                右
              </Button>
              <Divider orientation="vertical" my={4} />
              <Button size="compact-xs" variant="subtle" onClick={() => alignSelected("top")}>
                顶
              </Button>
              <Button size="compact-xs" variant="subtle" onClick={() => alignSelected("centerY")}>
                垂直中
              </Button>
              <Button size="compact-xs" variant="subtle" onClick={() => alignSelected("bottom")}>
                底
              </Button>
              <Divider orientation="vertical" my={4} />
              <Button
                size="compact-xs"
                variant="subtle"
                onClick={() =>
                  updateActiveElements(
                    (arr) =>
                      arr.map((it) =>
                        it.id === selectedEl.id ? { ...it, rotate: (((it.rotate || 0) + 90) % 360) as 0 | 90 | 180 | 270 } : it,
                      ),
                    true,
                  )
                }
              >
                90°
              </Button>
              <Button
                size="compact-xs"
                color="red"
                variant="light"
                onClick={() => {
                  updateActiveElements((arr) => arr.filter((it) => it.id !== selectedEl.id), true);
                  selectElement(null);
                }}
              >
                删除
              </Button>
            </div>
          )}

          <div className={classes.edCanvasViewport} onClick={() => selectElement(null)}>
            {editorSim203 && editorSim203B64 ? (
              <Stack align="center" gap="xs">
                <img
                  src={editorSim203B64}
                  alt={`${activeDpi}dpi 热转印仿真出纸图`}
                  style={{ maxWidth: 420, border: "1px solid var(--border-strong)", background: "#fff", borderRadius: 4 }}
                />
                <Text size="xs" c="dimmed">
                  真实后端 {activeDpi}dpi 1-bit 出纸仿真 ({wMm}×{hMm}mm) · 取消底部勾选以继续自由调整
                </Text>
              </Stack>
            ) : (
              <div
                className={classes.rulerFrame}
                style={{ gridTemplateColumns: `22px ${cw}px`, gridTemplateRows: `18px ${ch}px` }}
              >
                <div style={{ fontSize: 12, color: "#64748b", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  mm
                </div>
                <svg width={cw} height={18}>
                  {Array.from({ length: Math.floor(wMm) + 1 }).map((_, mm) =>
                    mm % 5 === 0 ? (
                      <g key={mm}>
                        <line x1={mm * pxPerMm} y1={8} x2={mm * pxPerMm} y2={18} stroke="#94a3b8" />
                        {mm < wMm - 2 && (
                          <text x={mm * pxPerMm + 2} y={9} fontSize={9} fill="#64748b">
                            {mm}
                          </text>
                        )}
                      </g>
                    ) : null,
                  )}
                </svg>
                <svg width={22} height={ch}>
                  {Array.from({ length: Math.floor(hMm) + 1 }).map((_, mm) =>
                    mm % 5 === 0 ? (
                      <g key={mm}>
                        <line x1={12} y1={mm * pxPerMm} x2={22} y2={mm * pxPerMm} stroke="#94a3b8" />
                        {mm < hMm - 2 && (
                          <text x={2} y={mm * pxPerMm + 9} fontSize={9} fill="#64748b">
                            {mm}
                          </text>
                        )}
                      </g>
                    ) : null,
                  )}
                </svg>
                <svg
                  id="activeLabelCanvas"
                  width={cw}
                  height={ch}
                  style={{
                    backgroundColor: "#ffffff",
                    border: "1px solid #cbd5e1",
                    backgroundImage: showGrid ? "radial-gradient(circle, rgba(100,116,139,0.28) 1px, transparent 1px)" : undefined,
                    backgroundSize: showGrid ? `${pxPerMm}px ${pxPerMm}px` : undefined,
                  }}
                  onClick={(e) => e.stopPropagation()}
                >
                  {!isSku && activeBoxBg ? (
                    <image
                      href={activeBoxBg}
                      x={0}
                      y={0}
                      width={cw}
                      height={ch}
                      preserveAspectRatio="xMidYMid meet"
                      opacity={0.9}
                      style={{ pointerEvents: "none" }}
                    />
                  ) : !isSku ? (
                    <text x={cw / 2} y={24} textAnchor="middle" fontSize={12} fill="#94a3b8" style={{ pointerEvents: "none" }}>
                      100×100mm 外箱叠加层（暂无选中外箱底图）
                    </text>
                  ) : null}
                  {elements.map((el) =>
                    renderSvgElement(el, pxPerMm, el.id === selectedElementId, (ev) => handleDragStart(el, ev)),
                  )}
                </svg>
              </div>
            )}
          </div>
        </div>

        {/* 底部同步出纸 / 外箱叠加应用 Dock */}
        {isSku ? (
          <div className={classes.edBottomDock}>
            <Group gap="sm">
              <NumberInput
                aria-label="本次发货张数"
                label="本次发货张数"
                size="xs"
                w={115}
                min={1}
                max={9999}
                value={fnskuQty}
                onChange={(v) => setFnskuQty(Number(v) || 1)}
              />
              <Badge size="sm" color="blue" variant="light" mt={18}>
                {draftSku.layoutType === "double" ? `共 ${Math.ceil(fnskuQty / 2)} 排` : `共 ${fnskuQty} 张单排`}
              </Badge>
            </Group>

            <Group gap="xs">
              <Checkbox
                label="打印效果模拟"
                size="xs"
                checked={editorSim203}
                onChange={(e) => void setEditorSim203(e.currentTarget.checked)}
              />
              <Button size="xs" variant="light" onClick={() => setBatchOpen(true)}>
                CSV 批量套打
              </Button>
              <Button size="xs" variant="default" onClick={() => void saveDraftTemplate()}>
                保存模板
              </Button>
              <Button size="xs" variant="default" onClick={() => void handleExportPdf()}>
                导出 PDF
              </Button>
              <Button size="xs" onClick={handlePrintProduct}>
                打印标签
              </Button>
            </Group>
          </div>
        ) : (
          <div className={classes.edBottomDock}>
            <Group gap="xs">
              <Badge size="sm" color="blue" variant="light">
                {activePair?.fba_box
                  ? `正在微调：${activePair.fba_box.shipment_id || "FBA"} 第 ${activePair.box_index} 箱`
                  : "100×100mm 外箱通用叠加层"}
              </Badge>
              <Text size="xs" c="dimmed">
                已叠加 {elements.length} 项元素
              </Text>
            </Group>
            <Group gap="xs">
              <Checkbox
                label="打印效果模拟"
                size="xs"
                checked={editorSim203}
                onChange={(e) => void setEditorSim203(e.currentTarget.checked)}
              />
              <Button
                size="xs"
                variant="default"
                color="red"
                disabled={elements.length === 0}
                onClick={() => {
                  clearBoxOverlays();
                  notifications.show({
                    title: "已清空外箱叠加层",
                    message: "可继续从左侧插入文本、条码或白色遮挡框",
                    color: "blue",
                  });
                }}
              >
                清空叠加层
              </Button>
              <Button size="xs" onClick={() => setActiveTab("box")}>
                应用并返回外箱配对
              </Button>
            </Group>
          </div>
        )}
      </div>

      {/* 右栏：属性检查器（条形码与可读文字一体化单控） */}
      <div className={classes.rightPanel}>
        <Group justify="space-between" mb="xs">
          <Text size="xs" fw={700}>
            {selectedEl ? selectedEl.name || selectedEl.type : "标签设置"}
          </Text>
          <Badge size="xs" variant="light">
            {selectedEl ? selectedEl.type : `${wMm}×${hMm}mm`}
          </Badge>
        </Group>

        {!selectedEl ? (
          isSku ? (
            <Stack gap="xs">
              <TextInput
                label="当前 SKU / 模板名"
                size="xs"
                value={draftSku.sku}
                onChange={(e) => updateDraftMeta({ sku: e.currentTarget.value })}
              />
              <Text size="xs" c="dimmed">
                当前规格：{wMm} × {hMm} mm（{draftSku.layoutType === "double" ? "双排" : "单排"}）· 共 {elements.length} 项元素。
              </Text>
              <Text size="xs" c="dimmed">
                点击画布中的条码或文字即可修改内容与坐标；修改条码编码时，条形与正下方可读编号将保持同步更新。
              </Text>
            </Stack>
          ) : (
            <Stack gap="xs">
              <Text size="xs" fw={600}>
                {activePair?.fba_box
                  ? `底图：${activePair.fba_box.shipment_id || "未命名货件"} · 第 ${activePair.box_index} 箱`
                  : "通用 100×100mm 外箱叠加层"}
              </Text>
              <Text size="xs" c="dimmed">
                当前规格：100 × 100 mm（单排外箱叠加层）· 共 {elements.length} 项叠加元素。
              </Text>
              <Text size="xs" c="dimmed">
                在此画布添加的文字、二维码、图片或白色遮挡框，会在导出与打印 FBA 外箱标签时以矢量层准确叠印。
              </Text>
            </Stack>
          )
        ) : (
          <Stack gap="xs">
            {selectedEl.type === "barcode1d" && (() => {
              const rep = evaluateBarcodeDots(selectedEl.code || "X000DEMO01", selectedEl.w, activeDpi);
              return (
                <>
                  <TextInput
                    label="条码编码（条纹与下方文字同步更新）"
                    size="xs"
                    styles={{ input: { fontFamily: "var(--mono)" } }}
                    value={selectedEl.code || ""}
                    onFocus={() => {
                      propDirtyRef.current = false;
                    }}
                    onBlur={() => {
                      propDirtyRef.current = false;
                    }}
                    onChange={(e) => {
                      const val = e.currentTarget.value;
                      updateActiveElements(
                        (arr) => arr.map((it) => (it.id === selectedEl.id ? { ...it, code: val } : it)),
                        recordContinuous(),
                      );
                    }}
                  />
                  <Alert color={rep.level === "safe" ? "green" : rep.level === "warn" ? "yellow" : "red"} p={8}>
                    <Text size="xs">{rep.message}</Text>
                  </Alert>
                  <Checkbox
                    size="xs"
                    label="同时显示下方编号文字"
                    checked={selectedEl.showText !== false}
                    onChange={(e) => {
                      const chk = e.currentTarget.checked;
                      updateActiveElements((arr) => arr.map((it) => (it.id === selectedEl.id ? { ...it, showText: chk } : it)), true);
                    }}
                  />
                  <NumberInput
                    label="下方文字大小 (pt)"
                    size="xs"
                    min={5}
                    max={18}
                    step={0.5}
                    value={selectedEl.fontSize || 8.5}
                    onFocus={() => {
                      propDirtyRef.current = false;
                    }}
                    onBlur={() => {
                      propDirtyRef.current = false;
                    }}
                    onChange={(v) =>
                      updateActiveElements(
                        (arr) => arr.map((it) => (it.id === selectedEl.id ? { ...it, fontSize: Number(v) || 8.5 } : it)),
                        recordContinuous(),
                      )
                    }
                  />
                </>
              );
            })()}

            {selectedEl.type === "qrcode" && (
              <>
                <TextInput
                  label="二维码内容（实时预览编码）"
                  size="xs"
                  styles={{ input: { fontFamily: "var(--mono)" } }}
                  value={selectedEl.code || ""}
                  onFocus={() => {
                    propDirtyRef.current = false;
                  }}
                  onBlur={() => {
                    propDirtyRef.current = false;
                  }}
                  onChange={(e) => {
                    const val = e.currentTarget.value;
                    updateActiveElements(
                      (arr) => arr.map((it) => (it.id === selectedEl.id ? { ...it, code: val } : it)),
                      recordContinuous(),
                    );
                  }}
                />
                <Text size="xs" c="dimmed">
                  支持 FNSKU、网址或自定义文本，调整宽高时建议保持正方形以确保扫码识别率。
                </Text>
              </>
            )}

            {selectedEl.type === "text" && (
              <>
                <Textarea
                  label="文本内容"
                  size="xs"
                  rows={3}
                  value={selectedEl.text || ""}
                  onFocus={() => {
                    propDirtyRef.current = false;
                  }}
                  onBlur={() => {
                    propDirtyRef.current = false;
                  }}
                  onChange={(e) => {
                    const v = e.currentTarget.value;
                    updateActiveElements(
                      (arr) => arr.map((it) => (it.id === selectedEl.id ? { ...it, text: v } : it)),
                      recordContinuous(),
                    );
                  }}
                />
                <SimpleGrid cols={2}>
                  <NumberInput
                    label="字号 (pt)"
                    size="xs"
                    min={4}
                    max={36}
                    step={0.5}
                    value={selectedEl.fontSize || 7.5}
                    onFocus={() => {
                      propDirtyRef.current = false;
                    }}
                    onBlur={() => {
                      propDirtyRef.current = false;
                    }}
                    onChange={(v) =>
                      updateActiveElements(
                        (arr) => arr.map((it) => (it.id === selectedEl.id ? { ...it, fontSize: Number(v) || 7.5 } : it)),
                        recordContinuous(),
                      )
                    }
                  />
                  <Select
                    label="对齐方式"
                    size="xs"
                    value={selectedEl.align || "left"}
                    onChange={(v) =>
                      updateActiveElements(
                        (arr) =>
                          arr.map((it) => (it.id === selectedEl.id ? { ...it, align: (v as "left" | "center" | "right") || "left" } : it)),
                        true,
                      )
                    }
                    data={[
                      { value: "left", label: "左对齐" },
                      { value: "center", label: "居中" },
                      { value: "right", label: "右对齐" },
                    ]}
                  />
                </SimpleGrid>
                <Checkbox
                  size="xs"
                  label="文字加粗"
                  checked={Boolean(selectedEl.bold)}
                  onChange={(e) => {
                    const chk = e.currentTarget.checked;
                    updateActiveElements((arr) => arr.map((it) => (it.id === selectedEl.id ? { ...it, bold: chk } : it)), true);
                  }}
                />
              </>
            )}

            {(selectedEl.type === "rect" || selectedEl.type === "line") && (
              <>
                <NumberInput
                  label="线条粗细 (mm)"
                  size="xs"
                  min={0.1}
                  max={5}
                  step={0.1}
                  decimalScale={1}
                  value={selectedEl.strokeWidth ?? 0.4}
                  onFocus={() => {
                    propDirtyRef.current = false;
                  }}
                  onBlur={() => {
                    propDirtyRef.current = false;
                  }}
                  onChange={(v) =>
                    updateActiveElements(
                      (arr) => arr.map((it) => (it.id === selectedEl.id ? { ...it, strokeWidth: Math.max(0.1, Number(v) || 0.4) } : it)),
                      recordContinuous(),
                    )
                  }
                />
                <Checkbox
                  size="xs"
                  label="虚线样式"
                  checked={Boolean(selectedEl.dashed)}
                  onChange={(e) => {
                    const chk = e.currentTarget.checked;
                    updateActiveElements((arr) => arr.map((it) => (it.id === selectedEl.id ? { ...it, dashed: chk } : it)), true);
                  }}
                />
              </>
            )}

            {selectedEl.type === "image" && selectedEl.imageDataUrl && (
              <Paper withBorder p={6} radius="sm" bg="#fff">
                <img
                  src={selectedEl.imageDataUrl}
                  alt={selectedEl.name || "插入图片"}
                  style={{ display: "block", width: "100%", maxHeight: 110, objectFit: "contain" }}
                />
              </Paper>
            )}

            <Divider my={4} />
            <SimpleGrid cols={2}>
              <NumberInput
                label="左距 X (mm)"
                size="xs"
                step={0.5}
                decimalScale={1}
                value={selectedEl.x}
                onFocus={() => {
                  propDirtyRef.current = false;
                }}
                onBlur={() => {
                  propDirtyRef.current = false;
                }}
                onChange={(v) =>
                  updateActiveElements(
                    (arr) => arr.map((it) => (it.id === selectedEl.id ? { ...it, x: Number(v) || 0 } : it)),
                    recordContinuous(),
                  )
                }
              />
              <NumberInput
                label="顶距 Y (mm)"
                size="xs"
                step={0.5}
                decimalScale={1}
                value={selectedEl.y}
                onFocus={() => {
                  propDirtyRef.current = false;
                }}
                onBlur={() => {
                  propDirtyRef.current = false;
                }}
                onChange={(v) =>
                  updateActiveElements(
                    (arr) => arr.map((it) => (it.id === selectedEl.id ? { ...it, y: Number(v) || 0 } : it)),
                    recordContinuous(),
                  )
                }
              />
              <NumberInput
                label="宽度 W (mm)"
                size="xs"
                step={0.5}
                min={2}
                decimalScale={1}
                value={selectedEl.w}
                onFocus={() => {
                  propDirtyRef.current = false;
                }}
                onBlur={() => {
                  propDirtyRef.current = false;
                }}
                onChange={(v) =>
                  updateActiveElements(
                    (arr) => arr.map((it) => (it.id === selectedEl.id ? { ...it, w: Math.max(2, Number(v) || 2) } : it)),
                    recordContinuous(),
                  )
                }
              />
              <NumberInput
                label="高度 H (mm)"
                size="xs"
                step={0.5}
                min={1}
                decimalScale={1}
                value={selectedEl.h}
                onFocus={() => {
                  propDirtyRef.current = false;
                }}
                onBlur={() => {
                  propDirtyRef.current = false;
                }}
                onChange={(v) =>
                  updateActiveElements(
                    (arr) => arr.map((it) => (it.id === selectedEl.id ? { ...it, h: Math.max(1, Number(v) || 1) } : it)),
                    recordContinuous(),
                  )
                }
              />
            </SimpleGrid>
          </Stack>
        )}
      </div>

      {/* 新建多尺寸标签弹窗 */}
      <Modal opened={newModalOpen} onClose={() => setNewModalOpen(false)} title="新建自定义标签" centered>
        <Stack gap="sm">
          <TextInput label="模板 / SKU 名称" value={newSku} onChange={(e) => setNewSku(e.currentTarget.value)} />
          <TextInput label="FNSKU 条码编号" value={newFnsku} onChange={(e) => setNewFnsku(e.currentTarget.value)} />
          <Select
            label="常用尺寸预设"
            value={newPreset}
            onChange={(val) => {
              const v = val || "50x30_double";
              setNewPreset(v);
              if (v === "50x30_double") {
                setNewW(50);
                setNewH(30);
                setNewLayout("double");
              } else if (v === "40x30_double") {
                setNewW(40);
                setNewH(30);
                setNewLayout("double");
              } else if (v === "100x100_single") {
                setNewW(100);
                setNewH(100);
                setNewLayout("single");
              }
            }}
            data={[
              { value: "50x30_double", label: "50 × 30 mm · 双排" },
              { value: "40x30_double", label: "40 × 30 mm · 双排" },
              { value: "100x100_single", label: "100 × 100 mm · 单排" },
            ]}
          />
          <SimpleGrid cols={3}>
            <NumberInput label="宽 (mm)" min={20} max={150} value={newW} onChange={(v) => setNewW(Number(v) || 50)} />
            <NumberInput label="高 (mm)" min={15} max={150} value={newH} onChange={(v) => setNewH(Number(v) || 30)} />
            <Select
              label="排数"
              value={newLayout}
              onChange={(v) => setNewLayout((v as "double" | "single") || "double")}
              data={[
                { value: "double", label: "双排" },
                { value: "single", label: "单排" },
              ]}
            />
          </SimpleGrid>
          <Group justify="flex-end" mt="sm">
            <Button variant="default" onClick={() => setNewModalOpen(false)}>
              取消
            </Button>
            <Button
              onClick={() => {
                createNewTemplate({ sku: newSku, fnsku: newFnsku, widthMm: newW, heightMm: newH, layoutType: newLayout });
                setNewModalOpen(false);
              }}
            >
              创建并进入设计
            </Button>
          </Group>
        </Stack>
      </Modal>
      <BatchSkuModal opened={batchOpen} onClose={() => setBatchOpen(false)} />
    </div>
  );
}
