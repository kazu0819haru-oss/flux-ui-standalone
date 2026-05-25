@echo off
chcp 65001 > nul
echo ========================================
echo   FLUX UI 起動中...
echo ========================================

REM --- config.json を読む（PowerShell で JSON パース）---
for /f "delims=" %%i in ('powershell -NoProfile -Command "(Get-Content config.json | ConvertFrom-Json).comfyui_dir"') do set COMFY_DIR=%%i
for /f "delims=" %%i in ('powershell -NoProfile -Command "(Get-Content config.json | ConvertFrom-Json).comfyui_python"') do set COMFY_PYTHON=%%i
for /f "delims=" %%i in ('powershell -NoProfile -Command "(Get-Content config.json | ConvertFrom-Json).flask_port"') do set FLASK_PORT=%%i

if "%COMFY_PYTHON%"=="" set COMFY_PYTHON=python
if "%FLASK_PORT%"=="" set FLASK_PORT=5000

echo ComfyUI: %COMFY_DIR%
echo Python:  %COMFY_PYTHON%
echo Port:    %FLASK_PORT%
echo.

REM --- ComfyUI が起動していなければ起動 ---
powershell -NoProfile -Command "try { (New-Object System.Net.Sockets.TcpClient).Connect('127.0.0.1',8188); exit 0 } catch { exit 1 }" > nul 2>&1
if errorlevel 1 (
    if exist "%COMFY_DIR%\main.py" (
        echo ComfyUI を起動中...
        start "" /min cmd /c "cd /d "%COMFY_DIR%" && "%COMFY_PYTHON%" main.py --fast"
        echo ComfyUI の起動を待機中（約60秒）...
        timeout /t 10 /nobreak > nul
    )
) else (
    echo ComfyUI は既に起動しています。
)

REM --- Flask を起動 ---
echo Flask UI を起動中...
set COMFYUI_DIR=%COMFY_DIR%
set COMFYUI_PYTHON=%COMFY_PYTHON%
start "" /min cmd /c "cd /d "%~dp0" && "%COMFY_PYTHON%" app.py"

REM --- ポート待機 ---
echo ブラウザを開くまで待機中...
timeout /t 4 /nobreak > nul

:WAIT_LOOP
powershell -NoProfile -Command "try { (New-Object System.Net.Sockets.TcpClient).Connect('127.0.0.1',%FLASK_PORT%); exit 0 } catch { exit 1 }" > nul 2>&1
if errorlevel 1 (
    timeout /t 2 /nobreak > nul
    goto WAIT_LOOP
)

REM --- ブラウザを開く ---
echo ブラウザを開いています: http://localhost:%FLASK_PORT%/loading
start "" "http://localhost:%FLASK_PORT%/loading"

echo.
echo FLUX UI started. (Flask runs in background)
echo To stop: close the minimized CMD window running Flask.
pause
