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

REM --- カスタムノードをインストール ---
echo.
echo カスタムノードをインストール中...
echo (初回のみ / 数分かかる場合があります)

git --version > nul 2>&1
if errorlevel 1 (
    echo [警告] git が見つかりません。カスタムノードの自動インストールをスキップします。
    echo   後で手動でインストールするか、ComfyUI Manager をご利用ください。
    goto :skip_custom_nodes
)

set NODES_DIR=%COMFY_DIR%\custom_nodes
if not exist "%NODES_DIR%" mkdir "%NODES_DIR%"

call :clone_node "ComfyUI-GGUF"              "https://github.com/city96/ComfyUI-GGUF"
call :clone_node "comfyui_controlnet_aux"    "https://github.com/Fannovel16/comfyui_controlnet_aux"
call :clone_node "ComfyUI-Impact-Pack"       "https://github.com/ltdrdata/ComfyUI-Impact-Pack"
call :clone_node "ComfyUI-Custom-Scripts"    "https://github.com/pythongosssss/ComfyUI-Custom-Scripts"
call :clone_node "ComfyUI-VideoHelperSuite"  "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite"
call :clone_node "ComfyUI-SeedVR2_VideoUpscaler" "https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler" "nightly"

echo カスタムノードのインストール完了。
:skip_custom_nodes

echo.
echo ========================================
echo   セットアップ完了！
echo   「起動.bat」または「起動.vbs」をダブルクリックして起動してください。
echo ========================================
pause
exit /b

:clone_node
set _NAME=%~1
set _URL=%~2
set _BRANCH=%~3
if exist "%NODES_DIR%\%_NAME%" (
    echo   既存ノードを確認中: %_NAME%
    if not "%_BRANCH%"=="" (
        git -C "%NODES_DIR%\%_NAME%" fetch origin "%_BRANCH%" --depth=1
        git -C "%NODES_DIR%\%_NAME%" switch "%_BRANCH%"
        git -C "%NODES_DIR%\%_NAME%" pull --ff-only origin "%_BRANCH%"
    )
    goto :install_node_requirements
)
echo   クローン中: %_NAME%
if "%_BRANCH%"=="" (
    git clone --depth=1 "%_URL%" "%NODES_DIR%\%_NAME%"
) else (
    git clone --depth=1 --branch "%_BRANCH%" --single-branch "%_URL%" "%NODES_DIR%\%_NAME%"
)
if errorlevel 1 (
    echo   [警告] クローン失敗: %_NAME%
    goto :eof
)
:install_node_requirements
if exist "%NODES_DIR%\%_NAME%\requirements.txt" (
    echo   依存パッケージをインストール中: %_NAME%
    if "%COMFY_PYTHON%"=="python" (
        python -m pip install -r "%NODES_DIR%\%_NAME%\requirements.txt" --quiet --disable-pip-version-check
    ) else (
        "%COMFY_PYTHON%" -m pip install -r "%NODES_DIR%\%_NAME%\requirements.txt" --quiet --disable-pip-version-check
    )
)
goto :eof
