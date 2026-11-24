"""局域网 TCP 9100 RAW 热敏打印机连通性探测与裸字节流直传客户端。"""

from __future__ import annotations

import socket
import time


def validate_tcp_target(host: str, port: int = 9100) -> tuple[str, int]:
    """清洗并校验 TCP 目标地址与端口范围。"""
    clean_host = (host or "").strip()
    if clean_host.lower().startswith("tcp://"):
        clean_host = clean_host[6:]
    clean_host = clean_host.rstrip("/")
    if not clean_host or any(ch.isspace() for ch in clean_host):
        raise ValueError("请输入有效的打印机 IP 或局域网主机名")
    clean_port = int(port)
    if clean_port < 1 or clean_port > 65535:
        raise ValueError("TCP 端口号必须在 1~65535 之间（常见热敏网口为 9100）")
    return clean_host, clean_port


def test_tcp_printer(host: str, port: int = 9100, timeout: float = 2.5) -> dict[str, object]:
    """仅检测 TCP 端口握手连通性后立即断开，严禁向打印机发送任何字节。"""
    try:
        clean_host, clean_port = validate_tcp_target(host, port)
    except ValueError as exc:
        return {"ok": False, "host": host, "port": port, "message": str(exc)}

    t0 = time.perf_counter()
    try:
        with socket.create_connection((clean_host, clean_port), timeout=timeout):
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        return {
            "ok": True,
            "host": clean_host,
            "port": clean_port,
            "latency_ms": latency_ms,
            "message": f"TCP 连通正常 ({clean_host}:{clean_port}, {latency_ms} ms)",
        }
    except OSError as exc:
        return {
            "ok": False,
            "host": clean_host,
            "port": clean_port,
            "message": f"无法连接网口打印机 {clean_host}:{clean_port}（{exc}）",
        }


def send_raw_tcp(host: str, port: int, payload: bytes, timeout: float = 6.0) -> dict[str, object]:
    """通过 RAW TCP Socket 直接推送 TSPL/ZPL 二进制指令流。"""
    try:
        clean_host, clean_port = validate_tcp_target(host, port)
    except ValueError as exc:
        return {"ok": False, "mode": "network_tcp", "error": str(exc)}

    try:
        with socket.create_connection((clean_host, clean_port), timeout=timeout) as sock:
            sock.sendall(payload)
        return {
            "ok": True,
            "mode": "network_tcp",
            "target": f"{clean_host}:{clean_port}",
            "bytes": len(payload),
        }
    except OSError as exc:
        return {
            "ok": False,
            "mode": "network_tcp",
            "target": f"{clean_host}:{clean_port}",
            "error": f"TCP 发送失败：{exc}",
        }
