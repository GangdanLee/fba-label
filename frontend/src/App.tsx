import { useEffect, useRef, useState } from "react";
import { Button, Group, Modal, Stack, Text } from "@mantine/core";
import { Spotlight, type SpotlightActionData } from "@mantine/spotlight";
import { History, LayoutGrid, PackageCheck, Printer, Sparkles } from "lucide-react";
import classes from "./styles/Studio.module.css";
import { useWorkbenchStore } from "./store/useWorkbenchStore";
import { IconRail } from "./components/IconRail";
import { StudioHeader } from "./components/StudioHeader";
import { BoxStudio } from "./components/BoxStudio";
import { EditorStudio } from "./components/EditorStudio";
import { BatchesView } from "./components/BatchesView";
import { HardwareView } from "./components/HardwareView";
import { PrintModal } from "./components/PrintModal";

export default function App() {
  const { activeTab, setActiveTab, initApp, loadFictionalDemo, uploadFbaFiles, uploadCarrierFiles, importProductPdf, undo, redo } =
    useWorkbenchStore();
  const [importModalOpen, setImportModalOpen] = useState(false);

  const fbaFileRef = useRef<HTMLInputElement>(null);
  const carFileRef = useRef<HTMLInputElement>(null);
  const prodFileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void initApp();
  }, [initApp]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [undo, redo]);

  const actions: SpotlightActionData[] = [
    {
      id: "go-box",
      label: "切换到外箱标签工作台",
      description: "导入亚马逊外箱标与货代箱唛，物理擦除隐私并按编号配对",
      leftSection: <PackageCheck size={16} />,
      onClick: () => setActiveTab("box"),
    },
    {
      id: "go-editor",
      label: "切换到标签设计器",
      description: "新建多尺寸标签模板、自由拖拽条码或导入亚马逊产品标",
      leftSection: <LayoutGrid size={16} />,
      onClick: () => setActiveTab("editor"),
    },
    {
      id: "go-batches",
      label: "查看历史打印记录",
      description: "查看本地 SQLite 打印批次记录",
      leftSection: <History size={16} />,
      onClick: () => setActiveTab("batches"),
    },
    {
      id: "go-hardware",
      label: "打开打印机设置与校准",
      description: "探测热敏机、调整偏移与浓度、下载校准测试卡",
      leftSection: <Printer size={16} />,
      onClick: () => setActiveTab("hardware"),
    },
    {
      id: "demo-mix",
      label: "试用虚构双票配对示例",
      description: "客户端实时合成虚构 PDF 并经后端 PyMuPDF 真实脱敏",
      leftSection: <Sparkles size={16} />,
      onClick: () => {
        setActiveTab("box");
        void loadFictionalDemo("dual_mix");
      },
    },
  ];

  return (
    <div className={classes.studioShell}>
      <IconRail onOpenImport={() => setImportModalOpen(true)} />

      <div className={classes.workspaceMain}>
        <StudioHeader />
        {activeTab === "box" && <BoxStudio />}
        {activeTab === "editor" && <EditorStudio />}
        {activeTab === "batches" && <BatchesView />}
        {activeTab === "hardware" && <HardwareView />}
      </div>

      <PrintModal />

      <Spotlight
        actions={actions}
        shortcut={["mod + K"]}
        nothingFound="未找到匹配命令..."
        searchProps={{ placeholder: "输入命令关键词，例如：外箱、设计、打印记录..." }}
      />

      <Modal opened={importModalOpen} onClose={() => setImportModalOpen(false)} title="导入本地 PDF 文件" centered>
        <Stack gap="sm">
          <Text size="xs" c="dimmed">
            全部文件仅在本机后端处理，不会上传到任何第三方服务器。
          </Text>
          <Group grow>
            <Button
              variant="default"
              onClick={() => fbaFileRef.current?.click()}
            >
              ① 导入亚马逊外箱 PDF
            </Button>
            <Button
              variant="default"
              onClick={() => carFileRef.current?.click()}
            >
              ② 导入货代箱唛 PDF
            </Button>
          </Group>
          <Button
            variant="light"
            onClick={() => prodFileRef.current?.click()}
          >
            ③ 导入亚马逊产品标签 PDF (FNSKU)
          </Button>
          <input
            ref={fbaFileRef}
            type="file"
            accept=".pdf,application/pdf"
            multiple
            style={{ display: "none" }}
            onChange={(e) => {
              if (e.target.files) {
                setActiveTab("box");
                void uploadFbaFiles(Array.from(e.target.files));
              }
              setImportModalOpen(false);
              e.target.value = "";
            }}
          />
          <input
            ref={carFileRef}
            type="file"
            accept=".pdf,application/pdf"
            multiple
            style={{ display: "none" }}
            onChange={(e) => {
              if (e.target.files) {
                setActiveTab("box");
                void uploadCarrierFiles(Array.from(e.target.files));
              }
              setImportModalOpen(false);
              e.target.value = "";
            }}
          />
          <input
            ref={prodFileRef}
            type="file"
            accept=".pdf,application/pdf"
            style={{ display: "none" }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) {
                setActiveTab("editor");
                void importProductPdf(f);
              }
              setImportModalOpen(false);
              e.target.value = "";
            }}
          />
        </Stack>
      </Modal>
    </div>
  );
}
