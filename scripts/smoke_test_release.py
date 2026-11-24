"""独立分发包解压、冷启动与核心全链路冒烟测试脚本（本地与 CI 通用）。"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import httpx

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
from tests.conftest import build_synthetic_fba_en_pdf  # noqa: E402


def verify_standalone_zip(zip_path: Path, port: int = 18199) -> None:
    if not zip_path.is_file():
        raise FileNotFoundError(f"未找到分发压缩包: {zip_path}")

    extract_dir = Path(tempfile.mkdtemp(prefix="fba_smoke_extract_"))
    data_dir = Path(tempfile.mkdtemp(prefix="fba_smoke_data_"))

    try:
        is_windows = platform.system() == "Windows"
        if is_windows:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)
        else:
            subprocess.run(["unzip", "-q", str(zip_path), "-d", str(extract_dir)], check=True)

        roots = [p for p in extract_dir.iterdir() if p.is_dir()]
        if not roots:
            raise RuntimeError("解压后的压缩包未包含顶层程序目录")
        pkg_dir = roots[0]
        exe_name = "FBA-Label-Studio.exe" if is_windows else "FBA-Label-Studio"
        exe_path = pkg_dir / "app" / exe_name
        if not exe_path.is_file():
            raise FileNotFoundError(f"未找到独立可执行文件: {exe_path}")

        if not is_windows:
            os.chmod(exe_path, 0o755)
            cmd_launcher = pkg_dir / "启动-FBA标签工作台.command"
            assert cmd_launcher.is_file() and os.access(cmd_launcher, os.X_OK), "缺少或不可执行 .command 启动文件"

        env = os.environ.copy()
        env["LABEL_PRINT_DATA_DIR"] = str(data_dir)
        proc = subprocess.Popen(
            [str(exe_path), "--no-browser", "--port", str(port)],
            cwd=str(pkg_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        with httpx.Client(trust_env=False, timeout=15.0) as client:
            try:
                base_url = f"http://127.0.0.1:{port}"
                for _ in range(60):
                    if proc.poll() is not None:
                        out = proc.stdout.read().decode("utf-8", errors="replace") if proc.stdout else ""
                        raise RuntimeError(f"独立可执行文件提前退出 ({proc.returncode}):\n{out}")
                    try:
                        r = client.get(f"{base_url}/api/health", timeout=1.0)
                        if r.status_code == 200:
                            break
                    except Exception:
                        time.sleep(0.3)
                else:
                    raise RuntimeError("独立后端服务启动超时")

                r_idx = client.get(f"{base_url}/")
                assert r_idx.status_code == 200 and "FBA 标签工作台" in r_idx.text

                r_prof = client.get(f"{base_url}/api/hardware/profiles")
                assert r_prof.status_code == 200 and len(r_prof.json()) >= 2

                fba_pdf = build_synthetic_fba_en_pdf("FBA00STANDALONE", "DMO1", 2)
                r_fba = client.post(
                    f"{base_url}/api/box/process-fba",
                    files={"file": ("FBA00STANDALONE.pdf", fba_pdf, "application/pdf")},
                )
                assert r_fba.status_code == 200, r_fba.text
                assert r_fba.json()["shipment_id"] == "FBA00STANDALONE"
                assert r_fba.json()["boxes"][0]["clean_preview_b64"].startswith("data:image/png;base64,")

                r_fnsku = client.post(
                    f"{base_url}/api/fnsku/render-preview",
                    json={
                        "widthMm": 50,
                        "heightMm": 30,
                        "layoutType": "double",
                        "qty": 2,
                        "elements": [
                            {"id": "bc1", "type": "barcode1d", "x": 3, "y": 2, "w": 44, "h": 14, "code": "X009PKG01", "showText": True},
                            {"id": "t1", "type": "text", "x": 3, "y": 17, "w": 44, "h": 8, "text": "中文测试标签 Demo", "fontSize": 7.5},
                        ],
                    },
                )
                assert r_fnsku.status_code == 200, r_fnsku.text
                assert r_fnsku.json()["preview_203dpi_b64"].startswith("data:image/png;base64,")

                r_tspl = client.post(
                    f"{base_url}/api/hardware/dryrun-tspl",
                    json={"pdf_b64": r_fba.json()["pdf_b64"], "width_mm": 100.0, "height_mm": 100.0},
                )
                assert r_tspl.status_code == 200 and r_tspl.json()["commands_count"] == 2

                assert (data_dir / "label_print.db").is_file(), "未在独立用户目录自动创建 SQLite 库"
                print(f"SMOKE TEST PASSED: {zip_path.name} ({platform.system()})")
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)
        shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python scripts/smoke_test_release.py <zip_path>")
    verify_standalone_zip(Path(sys.argv[1]).resolve())
