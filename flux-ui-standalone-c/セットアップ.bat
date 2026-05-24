@echo off
chcp 65001 > nul
echo ========================================
echo   FLUX UI セットアップ
echo ========================================
echo.

REM --- ComfyUI フォルダのパスを入力 ---
set /p COMFY_DIR="ComfyUI のフォルダパスを入力してください (例: C:\AI\ComfyUI): "
if "%COMFY_DIR%"=="" (
    echo パスが入力されませんでした。デフォルトを使用します: C:\AI\ComfyUI
    set COMFY_DIR=C:\AI\ComfyUI
)

REM --- Python の場所を特定 ---
set COMFY_PYTHON=%COMFY_DIR%\.venv\Scripts\python.exe
if not exist "%COMFY_PYTHON%" (
    echo ComfyUI 内蔵 Python が見つかりません。システム Python を使用します。
    set COMFY_PYTHON=python
)

REM --- config.json を生成 ---
echo { > config.json
echo   "comfyui_dir": "%COMFY_DIR:\=\\%", >> config.json
echo   "comfyui_python": "%COMFY_PYTHON:\=\\%", >> config.json
echo   "flask_port": 5000 >> config.json
echo } >> config.json
echo.
echo config.json を生成しました。

REM --- pip パッケージをインストール ---
echo.
echo 必要なパッケージをインストール中...
if "%COMFY_PYTHON%"=="python" (
    python -m pip install -r requirements.txt
) else (
    "%COMFY_PYTHON%" -m pip install -r requirements.txt
)
if errorlevel 1 (
    echo.
    echo [警告] パッケージのインストールに失敗しました。
    echo 手動で以下を実行してください:
    echo   pip install -r requirements.txt
) else (
    echo パッケージのインストール完了。
)

echo.
echo ========================================
echo   セットアップ完了！
echo   「起動.bat」または「起動.vbs」をダブルクリックして起動してください。
echo ========================================
pause
