"""全局常量、物理毫米/点/点阵换算与存储路径配置。"""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

IS_FROZEN: bool = bool(getattr(sys, "frozen", False))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))


def get_frontend_dist_dir() -> Path:
    """获取编译后的前端静态资源目录（兼容环境变量、PyInstaller 冻结态与源码开发态）。"""
    env_dir = os.environ.get("LABEL_PRINT_FRONTEND_DIR")
    if env_dir:
        return Path(env_dir)
    if IS_FROZEN:
        bundled = BUNDLE_DIR / "frontend_dist"
        if bundled.is_dir():
            return bundled
    return PROJECT_ROOT / "frontend" / "dist"


FRONTEND_DIST_DIR = get_frontend_dist_dir()


def get_data_dir() -> Path:
    """获取持久化数据目录（支持环境变量覆盖；冻结态自动写入系统用户可写目录）。"""
    env_dir = os.environ.get("LABEL_PRINT_DATA_DIR")
    if env_dir:
        path = Path(env_dir)
    elif IS_FROZEN:
        sys_name = platform.system()
        if sys_name == "Darwin":
            path = Path.home() / "Library" / "Application Support" / "FBA Label Studio"
        elif sys_name == "Windows":
            base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
            path = base / "FBA Label Studio"
        else:
            path = Path.home() / ".local" / "share" / "fba-label-studio"
    else:
        path = BACKEND_ROOT / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_db_path() -> Path:
    """获取 SQLite 数据库文件路径。"""
    return get_data_dir() / "label_print.db"


def get_snapshots_dir() -> Path:
    """获取历史打印快照目录。"""
    d = get_data_dir() / "snapshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


# 打印机与 PDF 几何物理常量
DPI: int = 203
DOTS_PER_MM: float = 8.0  # TSC TTP-244 Pro 为 203 dpi (~8 dots/mm)
MM_TO_PT: float = 72.0 / 25.4
PT_TO_MM: float = 25.4 / 72.0

PAGE_BOX_MM: float = 100.0
SAFE_BOX_MM: float = 98.0
DEFAULT_50X30_WIDTH_MM: float = 50.0
DEFAULT_50X30_HEIGHT_MM: float = 30.0
DEFAULT_COL_GAP_MM: float = 2.0


def mm_to_pt(mm: float) -> float:
    """毫米转 PDF 点 (pt)。"""
    return float(mm) * MM_TO_PT


def pt_to_mm(pt: float) -> float:
    """PDF 点 (pt) 转毫米。"""
    return float(pt) * PT_TO_MM


def dots_per_mm_for_dpi(dpi: int = 203) -> float:
    """按打印头精度返回每毫米像素点数（203dpi 保留 8.0 以维持既有点阵输出完全兼容）。"""
    if int(dpi) == 203:
        return DOTS_PER_MM
    return float(dpi) / 25.4


def mm_to_dots(mm: float, dots_per_mm: float = DOTS_PER_MM) -> int:
    """毫米转热敏整数像素点 (dot)。"""
    return int(round(float(mm) * dots_per_mm))


def dots_to_mm(dots: int, dots_per_mm: float = DOTS_PER_MM) -> float:
    """像素点转毫米。"""
    return float(dots) / dots_per_mm
