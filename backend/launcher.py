"""独立分发版统一启动入口（PyInstaller 冻结运行入口：自动分配空闲端口并打开浏览器）。"""

from __future__ import annotations

import argparse
import os
import socket
import threading
import time
import urllib.request
import webbrowser
from typing import Iterable

import uvicorn

from app.config import get_data_dir, get_frontend_dist_dir
from app.main import app


def is_port_free(host: str, port: int) -> bool:
    """探测本地 TCP 端口是否空闲可绑定。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def find_available_port(
    host: str = "127.0.0.1",
    preferred_ports: Iterable[int] = (8000, *range(18180, 18220)),
) -> int:
    """优先从常用端口池选取可用端口，全部占用时向系统申请随机空闲端口。"""
    for port in preferred_ports:
        if is_port_free(host, port):
            return int(port)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _open_browser_when_ready(url: str) -> None:
    health_url = f"{url}/api/health"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(60):
        try:
            with opener.open(health_url, timeout=0.8) as resp:
                if resp.status == 200:
                    webbrowser.open(url)
                    return
        except Exception:
            time.sleep(0.25)


def main() -> None:
    parser = argparse.ArgumentParser(description="FBA Label Studio 本地服务启动器")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=0, help="指定监听端口（0 表示自动选择空闲端口）")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    args = parser.parse_args()

    # Windows 下兼容部分控制台输出 UTF-8 中文提示
    if os.name == "nt":
        try:
            import sys

            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    port = args.port if args.port > 0 else find_available_port(host=args.host)
    url = f"http://{args.host}:{port}"

    print("=" * 56)
    print("  FBA Label Studio · 亚马逊 FBA 一体化标签工作台")
    print(f"  本地访问地址: {url}")
    print(f"  数据存储目录: {get_data_dir()}")
    print(f"  前端资源目录: {get_frontend_dist_dir()}")
    print("  提示: 保持此窗口运行；关闭窗口或按 Ctrl+C 停止服务。")
    print("=" * 56, flush=True)

    if not args.no_browser:
        t = threading.Thread(target=_open_browser_when_ready, args=(url,), daemon=True)
        t.start()

    uvicorn.run(app, host=args.host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
