import { Badge } from "@mantine/core";
import { History, LayoutGrid, Moon, PackageCheck, Printer, Sun, Upload } from "lucide-react";
import { useMantineColorScheme } from "@mantine/core";
import classes from "../styles/Studio.module.css";
import { useWorkbenchStore } from "../store/useWorkbenchStore";
import type { TabKey } from "../types";

interface Props {
  onOpenImport: () => void;
}

const NAV_ITEMS: Array<{ key: TabKey; label: string; Icon: typeof PackageCheck }> = [
  { key: "box", label: "外箱标签", Icon: PackageCheck },
  { key: "editor", label: "标签设计", Icon: LayoutGrid },
  { key: "batches", label: "打印记录", Icon: History },
  { key: "hardware", label: "打印机", Icon: Printer },
];

export function IconRail({ onOpenImport }: Props) {
  const { activeTab, setActiveTab, batches } = useWorkbenchStore();
  const { colorScheme, toggleColorScheme } = useMantineColorScheme();

  return (
    <aside className={classes.iconRail} aria-label="功能区导航">
      <div className={classes.railGroup} role="tablist" aria-label="主工作区切换">
        <div className={classes.railLogo} aria-hidden="true">
          FBA
        </div>
        {NAV_ITEMS.map(({ key, label, Icon }) => {
          const isActive = activeTab === key;
          return (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={isActive}
              className={`${classes.railBtn} ${isActive ? classes.railBtnActive : ""}`}
              onClick={() => setActiveTab(key)}
            >
              <Icon size={20} strokeWidth={1.8} aria-hidden="true" />
              <span>{label}</span>
              {key === "batches" && batches.length > 0 && (
                <Badge
                  size="xs"
                  circle
                  color="blue"
                  style={{ position: "absolute", top: 4, right: 4, pointerEvents: "none" }}
                >
                  {batches.length}
                </Badge>
              )}
            </button>
          );
        })}
      </div>

      <div className={classes.railGroup}>
        <button
          type="button"
          className={classes.railBottomBtn}
          onClick={onOpenImport}
          aria-label="导入本地 PDF 文件"
          title="导入本地 PDF"
        >
          <Upload size={17} aria-hidden="true" />
        </button>
        <button
          type="button"
          className={classes.railBottomBtn}
          onClick={() => toggleColorScheme()}
          aria-label="切换浅色或深色界面外观"
          title="切换外观"
        >
          {colorScheme === "dark" ? <Sun size={17} aria-hidden="true" /> : <Moon size={17} aria-hidden="true" />}
        </button>
      </div>
    </aside>
  );
}
