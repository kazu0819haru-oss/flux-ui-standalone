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

REM --- 起動時に必要カスタムノードを自動同期 ---
set NODES_DIR=%COMFY_DIR%\custom_nodes
set SEEDVR2_DIR=%NODES_DIR%\ComfyUI-SeedVR2_VideoUpscaler
git --version > nul 2>&1
if not errorlevel 1 (
    if not exist "%NODES_DIR%" mkdir "%NODES_DIR%"
    call :sync_node "ComfyUI-GGUF" "https://github.com/city96/ComfyUI-GGUF"
    call :sync_node "comfyui_controlnet_aux" "https://github.com/Fannovel16/comfyui_controlnet_aux"
    call :sync_node "ComfyUI-Impact-Pack" "https://github.com/ltdrdata/ComfyUI-Impact-Pack"
    call :sync_node "ComfyUI-Custom-Scripts" "https://github.com/pythongosssss/ComfyUI-Custom-Scripts"
    call :sync_node "ComfyUI-VideoHelperSuite" "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite"
    call :sync_node "ComfyUI-SeedVR2_VideoUpscaler" "https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler" "nightly"
)

REM --- 既にComfyUIが起動中でも、必要ノードが未ロードなら再起動して読み込ませる ---
powershell -NoProfile -Command "$required=@('LoadVideo','GetVideoComponents','CreateVideo','SaveVideo','SeedVR2VideoUpscaler','SeedVR2LoadDiTModel','SeedVR2LoadVAEModel','SeedVR2TorchCompileSettings'); try { $o=Invoke-RestMethod -Uri 'http://127.0.0.1:8188/object_info' -TimeoutSec 5; $names=$o.PSObject.Properties.Name; foreach($n in $required){ if($names -notcontains $n){ exit 2 } }; exit 0 } catch { exit 1 }" > nul 2>&1
if errorlevel 2 (
    echo ComfyUIを再起動してカスタムノードを読み込み直します...
    powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*main.py*' -and $_.CommandLine -like '*ComfyUI*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    timeout /t 3 /nobreak > nul
)

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

REM --- splash.html がポーリングしてリダイレクトするためブラウザ起動は不要 ---

echo.
echo FLUX UI started. (Flask runs in background)
echo To stop: close the minimized CMD window running Flask.
pause
exit /b

:sync_node
set _NAME=%~1
set _URL=%~2
set _BRANCH=%~3
set _TARGET=%NODES_DIR%\%_NAME%
if exist "%_TARGET%" (
    echo Custom node update: %_NAME%
    if not "%_BRANCH%"=="" (
        git -C "%_TARGET%" fetch origin "%_BRANCH%" --depth=1
        git -C "%_TARGET%" switch "%_BRANCH%"
        git -C "%_TARGET%" pull --ff-only origin "%_BRANCH%"
    )
) else (
    echo Custom node install: %_NAME%
    if "%_BRANCH%"=="" (
        git clone --depth=1 "%_URL%" "%_TARGET%"
    ) else (
        git clone --depth=1 --branch "%_BRANCH%" --single-branch "%_URL%" "%_TARGET%"
    )
)
if exist "%_TARGET%\requirements.txt" (
    "%COMFY_PYTHON%" -m pip install -r "%_TARGET%\requirements.txt" --quiet --disable-pip-version-check
)
goto :eof
