"""跨平台免安装独立发行包构建脚本（PyInstaller onedir + 内嵌前端 dist）。"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"
RELEASE_OUT_DIR = PROJECT_ROOT / "release_out"


def detect_platform_tag() -> str:
    sys_name = platform.system()
    machine = platform.machine().lower()
    if sys_name == "Darwin":
        arch = "arm64" if ("arm" in machine or "aarch64" in machine) else "x64"
        return f"macos-{arch}"
    if sys_name == "Windows":
        return "windows-x64"
    return f"linux-{'arm64' if 'aarch64' in machine or 'arm' in machine else 'x64'}"


def _build_frontend_if_needed(skip_frontend: bool) -> None:
    if skip_frontend and FRONTEND_DIST.is_dir():
        print(f"==> 使用已有前端静态产物: {FRONTEND_DIST}")
        return
    npm_cmd = "npm.cmd" if platform.system() == "Windows" else "npm"
    if not FRONTEND_DIST.is_dir() or not skip_frontend:
        print("==> 正在构建前端生产产物 (vite build)...")
        subprocess.run([npm_cmd, "run", "build"], cwd=str(FRONTEND_DIR), check=True)
    if not (FRONTEND_DIST / "index.html").is_file():
        raise FileNotFoundError(f"未找到前端构建入口: {FRONTEND_DIST / 'index.html'}")


def _write_readme_txt(dest_dir: Path, platform_tag: str, version: str) -> None:
    is_mac = platform_tag.startswith("macos")
    content = (
        f"FBA Label Studio · 亚马逊 FBA 一体化标签工作台 ({version} / {platform_tag})\n"
        "=" * 64 + "\n\n"
        "【使用方式】\n"
        + (
            "  1. 推荐双击根目录的「启动-FBA标签工作台.command」（或运行 ./app/FBA-Label-Studio）。\n"
            "  2. 启动后将自动分配空闲本地端口并打开系统默认浏览器。\n"
            "  3. 关闭终端窗口或在窗口内按 Ctrl+C 即可安全退出。\n\n"
            "【macOS 首次打开提示「无法验证开发者」放行方法】\n"
            "  - 方法一：按住 Control 键点击「启动-FBA标签工作台.command」→ 选择「打开」。\n"
            "  - 方法二：在终端进入解压目录后执行：xattr -cr .\n\n"
            "【本机数据存储目录】\n"
            "  ~/Library/Application Support/FBA Label Studio/label_print.db\n"
            if is_mac
            else
            "  1. 双击根目录的「启动-FBA标签工作台.bat」（或直接打开 app\\FBA-Label-Studio.exe）。\n"
            "  2. 启动后将自动分配空闲本地端口并打开系统默认浏览器。\n"
            "  3. 关闭黑色控制台窗口或在窗口内按 Ctrl+C 即可安全退出。\n\n"
            "【Windows 首次打开遇到 Defender SmartScreen 蓝屏拦截提示】\n"
            "  - 点击提示弹窗中的「更多信息」→ 点击「仍要运行」即可。\n\n"
            "【本机数据存储目录】\n"
            "  %LOCALAPPDATA%\\FBA Label Studio\\label_print.db\n"
        )
        + "\n【核心功能与 v0.4.0 新特性】\n"
        "  - 外箱灵活标签配比（默认记住）：支持「FBA 2 张 + 箱唛 1 张」等任意独立张数预设与按箱微调，默认配置自动保存。\n"
        "  - 芯烨 XP-420B / 佳博深度兼容：增强品牌及 300dpi 自动识别、TSPL 负偏移像素级安全平移、指令头自动复位与反色补偿。\n"
        "  - 产品标签与 CSV 批量套打：支持多编码 CSV 导入、一键换行防错贴、自定义纸卷规格（40×30/60×40/100×150）与货代正则规则。\n"
        "  - 通用多协议打印路由：兼容 TSPL2 / ZPL II / 系统原生驱动 / 局域网 TCP 9100，支持多机免换纸。\n"
        "\n【隐私与开源说明】\n"
        "  - 所有 PDF 解析、隐私擦除、批量排版与打印记录均在您本机完成，绝不上传第三方服务器。\n"
        "  - 遵循 GNU AGPL-3.0 开源协议。\n"
    )
    (dest_dir / "使用说明.txt").write_text(content, encoding="utf-8")


def _write_launchers(dest_dir: Path, platform_tag: str) -> None:
    if platform_tag.startswith("windows"):
        bat = (
            "@echo off\r\n"
            "chcp 65001 >nul\r\n"
            'cd /d "%~dp0"\r\n'
            '"%~dp0app\\FBA-Label-Studio.exe"\r\n'
            "if errorlevel 1 pause\r\n"
        )
        (dest_dir / "启动-FBA标签工作台.bat").write_text(bat, encoding="utf-8")
    else:
        sh = (
            "#!/bin/bash\n"
            'DIR="$(cd "$(dirname "$0")" && pwd)"\n'
            'cd "$DIR"\n'
            'exec "$DIR/app/FBA-Label-Studio"\n'
        )
        cmd_path = dest_dir / "启动-FBA标签工作台.command"
        cmd_path.write_text(sh, encoding="utf-8")
        cmd_path.chmod(cmd_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _zip_directory_preserving_permissions(source_dir: Path, zip_path: Path) -> None:
    """打包文件夹为 zip，并在 POSIX 平台保留符号链接与可执行权限位。"""
    base_parent = source_dir.parent
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(source_dir.rglob("*")):
            arcname = path.relative_to(base_parent).as_posix()
            if path.is_symlink():
                info = zipfile.ZipInfo(arcname)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                zf.writestr(info, os.readlink(path))
            elif path.is_dir():
                info = zipfile.ZipInfo(arcname + "/")
                info.create_system = 3
                info.external_attr = (0o755 << 16) | 0x10
                zf.writestr(info, b"")
            else:
                st = path.stat()
                info = zipfile.ZipInfo.from_file(path, arcname)
                info.compress_type = zipfile.ZIP_DEFLATED
                if platform.system() != "Windows":
                    info.create_system = 3
                    info.external_attr = (st.st_mode & 0xFFFF) << 16
                with open(path, "rb") as f:
                    zf.writestr(info, f.read())


def _write_sha256(file_path: Path) -> Path:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    digest = h.hexdigest()
    sha_path = file_path.with_suffix(file_path.suffix + ".sha256")
    sha_path.write_text(f"{digest}  {file_path.name}\n", encoding="utf-8")
    return sha_path


def main() -> None:
    parser = argparse.ArgumentParser(description="构建跨平台免安装 FBA Label Studio 发行包")
    parser.add_argument("--version", default="v0.4.0", help="发布版本号 (例如 v0.4.0)")
    parser.add_argument("--platform-tag", default="", help="覆盖输出平台后缀")
    parser.add_argument("--skip-frontend-build", action="store_true", help="跳过 npm run build（复用已有 frontend/dist）")
    args = parser.parse_args()

    platform_tag = args.platform_tag or detect_platform_tag()
    _build_frontend_if_needed(args.skip_frontend_build)

    work_build = BACKEND_DIR / "build" / "pyinstaller_work"
    dist_stage = BACKEND_DIR / "dist" / "pyinstaller_stage"
    spec_dir = BACKEND_DIR / "build" / "specs"
    for d in (work_build, dist_stage, spec_dir):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)

    add_data_sep = os.pathsep
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onedir",
        "--noconfirm",
        "--clean",
        "--name",
        "FBA-Label-Studio",
        "--workpath",
        str(work_build),
        "--distpath",
        str(dist_stage),
        "--specpath",
        str(spec_dir),
        "--paths",
        str(BACKEND_DIR),
        "--add-data",
        f"{FRONTEND_DIST}{add_data_sep}frontend_dist",
        "--collect-binaries",
        "zxingcpp",
        "--collect-binaries",
        "pymupdf",
        "--collect-submodules",
        "pymupdf",
        "--collect-data",
        "reportlab",
        "--hidden-import",
        "uvicorn.logging",
        "--hidden-import",
        "uvicorn.loops.auto",
        "--hidden-import",
        "uvicorn.loops.asyncio",
        "--hidden-import",
        "uvicorn.protocols.http.auto",
        "--hidden-import",
        "uvicorn.protocols.http.h11_impl",
        "--hidden-import",
        "uvicorn.protocols.websockets.auto",
        "--hidden-import",
        "uvicorn.lifespan.on",
        "--hidden-import",
        "python_multipart",
        "--hidden-import",
        "multipart",
        "--exclude-module",
        "onnxruntime",
        "--exclude-module",
        "pymupdf4llm",
        "--exclude-module",
        "pymupdf_layout",
        "--exclude-module",
        "networkx",
        "--exclude-module",
        "pytest",
        "--exclude-module",
        "httpx",
        "--exclude-module",
        "tkinter",
    ]
    if platform_tag.startswith("windows"):
        cmd.extend([
            "--hidden-import",
            "win32print",
            "--hidden-import",
            "win32ui",
            "--hidden-import",
            "win32con",
            "--hidden-import",
            "PIL.ImageWin",
        ])
    cmd.append(str(BACKEND_DIR / "launcher.py"))

    print("==> 正在运行 PyInstaller 冻结打包...")
    subprocess.run(cmd, cwd=str(BACKEND_DIR), check=True)

    bundled_app_dir = dist_stage / "FBA-Label-Studio"
    if not bundled_app_dir.is_dir():
        raise RuntimeError(f"PyInstaller 未产出期望目录: {bundled_app_dir}")

    RELEASE_OUT_DIR.mkdir(parents=True, exist_ok=True)
    pkg_name = f"FBA-Label-Studio-{args.version}-{platform_tag}"
    pkg_dir = RELEASE_OUT_DIR / pkg_name
    if pkg_dir.exists():
        shutil.rmtree(pkg_dir)
    pkg_dir.mkdir(parents=True)

    shutil.move(str(bundled_app_dir), str(pkg_dir / "app"))
    _write_launchers(pkg_dir, platform_tag)
    _write_readme_txt(pkg_dir, platform_tag, args.version)

    zip_path = RELEASE_OUT_DIR / f"{pkg_name}.zip"
    if zip_path.exists():
        zip_path.unlink()
    _zip_directory_preserving_permissions(pkg_dir, zip_path)
    sha_path = _write_sha256(zip_path)

    print("=" * 56)
    print(f"  打包完成: {zip_path} ({zip_path.stat().st_size / (1024 * 1024):.1f} MB)")
    print(f"  校验文件: {sha_path}")
    print("=" * 56)


if __name__ == "__main__":
    main()
