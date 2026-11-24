#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

echo "==> [FBA Label Studio] 正在启动本地服务..."

if [ ! -x "$BACKEND_DIR/.venv/bin/uvicorn" ]; then
  echo "未检测到后端虚拟环境，请先运行: cd backend && uv venv --python 3.12 && uv pip install -e '.[dev]'"
  exit 1
fi

if [ ! -d "$FRONTEND_DIR/dist" ] && [ -d "$FRONTEND_DIR" ] && command -v npm >/dev/null 2>&1; then
  echo "==> 首次运行检测到缺少 frontend/dist，正在构建前端..."
  (cd "$FRONTEND_DIR" && npm install && npm run build)
fi

cd "$BACKEND_DIR"
"$BACKEND_DIR/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port 8000 &
SERVER_PID=$!

trap "kill $SERVER_PID 2>/dev/null || true" EXIT INT TERM

for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    break
  fi
  sleep 0.3
done

echo "==> 服务已就绪: http://127.0.0.1:8000"
open "http://127.0.0.1:8000" 2>/dev/null || true

wait $SERVER_PID
