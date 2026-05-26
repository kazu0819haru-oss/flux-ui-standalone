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
REM env_snapshot があれば frozen requirements を優先する
set REQ_FILE=requirements.txt
if exist "env_snapshot\requirements.frozen.txt" (
    echo env_snapshot を検出しました。固定バージョンのパッケージをインストールします。
    set REQ_FILE=env_snapshot\requirements.frozen.txt
)
echo 必要なパッケージをインストール中...
if "%COMFY_PYTHON%"=="python" (
    python -m pip install -r "%REQ_FILE%"
) else (
    "%COMFY_PYTHON%" -m pip install -r "%REQ_FILE%"
)
if errorlevel 1 (
    echo.
    echo [警告] パッケージのインストールに失敗しました。
    echo 手動で以下を実行してください:
    echo   pip install -r %REQ_FILE%
) else (
    echo パッケージのインストール完了。
)

REM --- カスタムノードをインストール ---
echo.
echo カスタムノードをインストール中...
echo (初回のみ / 数分かかる場合があります)

set NODES_DIR=%COMFY_DIR%\custom_nodes
if not exist "%NODES_DIR%" mkdir "%NODES_DIR%"

REM SeedVR2: env_snapshot があればコピーを優先（git clone しない）
if exist "env_snapshot\custom_nodes\ComfyUI-SeedVR2_VideoUpscaler" (
    echo   env_snapshot から SeedVR2 をコピーします...
    if exist "%NODES_DIR%\ComfyUI-SeedVR2_VideoUpscaler" (
        rmdir /s /q "%NODES_DIR%\ComfyUI-SeedVR2_VideoUpscaler"
    )
    xcopy /e /i /q "env_snapshot\custom_nodes\ComfyUI-SeedVR2_VideoUpscaler" "%NODES_DIR%\ComfyUI-SeedVR2_VideoUpscaler\"
    if errorlevel 1 (
        echo   [警告] SeedVR2 のコピーに失敗しました。
    ) else (
        echo   SeedVR2 コピー完了。
        REM SeedVR2 の依存パッケージをインストール
        if exist "%NODES_DIR%\ComfyUI-SeedVR2_VideoUpscaler\requirements.txt" (
            if "%COMFY_PYTHON%"=="python" (
                python -m pip install -r "%NODES_DIR%\ComfyUI-SeedVR2_VideoUpscaler\requirements.txt" --quiet --disable-pip-version-check
            ) else (
                "%COMFY_PYTHON%" -m pip install -r "%NODES_DIR%\ComfyUI-SeedVR2_VideoUpscaler\requirements.txt" --quiet --disable-pip-version-check
            )
        )
    )
    goto :other_nodes
)

REM env_snapshot がない場合は git clone
git --version > nul 2>&1
if errorlevel 1 (
    echo [警告] git が見つかりません。カスタムノードの自動インストールをスキップします。
    echo   後で手動でインストールするか、ComfyUI Manager をご利用ください。
    goto :other_nodes
)
call :clone_node "ComfyUI-SeedVR2_VideoUpscaler" "https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler" "nightly"

:other_nodes
REM SeedVR2 以外のノードは git clone（git がある場合のみ）
git --version > nul 2>&1
if errorlevel 1 goto :skip_other_nodes

call :clone_node "ComfyUI-GGUF"              "https://github.com/city96/ComfyUI-GGUF"
call :clone_node "comfyui_controlnet_aux"    "https://github.com/Fannovel16/comfyui_controlnet_aux"
call :clone_node "ComfyUI-Impact-Pack"       "https://github.com/ltdrdata/ComfyUI-Impact-Pack"
call :clone_node "ComfyUI-Custom-Scripts"    "https://github.com/pythongosssss/ComfyUI-Custom-Scripts"
call :clone_node "ComfyUI-VideoHelperSuite"  "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite"

:skip_other_nodes
echo カスタムノードのインストール完了。

REM --- モデルファイルの確認 ---
echo.
echo モデルファイルを確認しています...
set MODELS_DIR=%COMFY_DIR%\models\SEEDVR2
set MISSING=0
if not exist "%MODELS_DIR%\seedvr2_ema_7b_sharp_fp8_e4m3fn_mixed_block35_fp16.safetensors" (
    set MISSING=1
    echo   [不足] seedvr2_ema_7b_sharp_fp8_e4m3fn_mixed_block35_fp16.safetensors
) else (
    echo   [OK]   seedvr2_ema_7b_sharp_fp8_e4m3fn_mixed_block35_fp16.safetensors
)
if not exist "%MODELS_DIR%\ema_vae_fp16.safetensors" (
    set MISSING=1
    echo   [不足] ema_vae_fp16.safetensors
) else (
    echo   [OK]   ema_vae_fp16.safetensors
)
if "%MISSING%"=="1" (
    echo.
    echo *** 上記のモデルファイルを以下のフォルダに配置してください ***
    echo     %MODELS_DIR%
)

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
