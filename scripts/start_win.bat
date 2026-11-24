@echo off
chcp 65001 >nul
setlocal

set SCRIPT_DIR=%~dp0
for %%I in ("%SCRIPT_DIR%..") do set PROJECT_ROOT=%%~fI
set BACKEND_DIR=%PROJECT_ROOT%\backend
set FRONTEND_DIR=%PROJECT_ROOT%\frontend

if not exist "%BACKEND_DIR%\.venv\Scripts\uvicorn.exe" (
    echo [错误] 未检测到后端虚拟环境，请先在 backend 目录安装依赖：uv venv --python 3.12 ^&^& uv pip install -e ".[dev,windows]"
    pause
    exit /b 1
)

if not exist "%FRONTEND_DIR%\dist" (
    if exist "%FRONTEND_DIR%\package.json" (
        echo ==^> 正在构建前端 dist...
        pushd "%FRONTEND_DIR%"
        call npm install && call npm run build
        popd
    )
)

echo ==^> 正在启动 FBA Label Studio: http://127.0.0.1:8000
start "" cmd /c "timeout /t 2 >nul & start http://127.0.0.1:8000"
cd /d "%BACKEND_DIR%"
"%BACKEND_DIR%\.venv\Scripts\uvicorn.exe" app.main:app --host 127.0.0.1 --port 8000
