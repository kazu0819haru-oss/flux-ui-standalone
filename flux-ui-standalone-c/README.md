# FLUX UI Standalone（Batch版）

FLUX.1 / Wan2.2 を使った AI 画像生成 UI のポータブルパッケージです。  
ComfyUI をバックエンドとして動作します。

---

## 必要なもの

- **Windows 10/11 (64bit)**
- **Python 3.10 以上**（`python` コマンドが使えること）
- **ComfyUI** がインストール済み（`main.py` が存在するフォルダ）

---

## 初回セットアップ（1回だけ）

1. このフォルダを PC の好きな場所に置く（例：`C:\FLUX_UI\`）
2. **`セットアップ.bat` をダブルクリック**
3. 黒いウィンドウが開く → ComfyUI のフォルダパスを入力して Enter
4. 自動でパッケージインストールが始まる（数分かかることがあります）
5. 「セットアップ完了」と表示されたらウィンドウを閉じる

> **補足:** セットアップは最初の1回だけです。次回からは起動のみ。

---

## 毎回の起動

- **`起動.vbs` をダブルクリック** → コンソールなしで静かに起動します  
- または `起動.bat` をダブルクリック → 黒いコンソールウィンドウが出ます（ログ確認用）

ブラウザが自動で開き、UI が表示されます。

---

## フォルダ構成

```
セットアップ.bat        ← 初回のみ実行
起動.vbs               ← 毎回これをダブルクリック（コンソールなし）
起動.bat               ← 毎回これをダブルクリック（コンソールあり）
config.json            ← ComfyUI パス等の設定（セットアップで自動生成）
app.py                 ← Flask サーバー本体
static/                ← UI ファイル
requirements.txt       ← 必要パッケージリスト
FLUX_UI_説明書.docx    ← 操作マニュアル（各機能の使い方）
```

---

## config.json の手動設定

セットアップ後にパスを変えたい場合は `config.json` を直接編集してください。

```json
{
  "comfyui_dir": "C:\\AI\\ComfyUI",
  "comfyui_python": "C:\\AI\\ComfyUI\\.venv\\Scripts\\python.exe",
  "flask_port": 5000
}
```

| キー | 説明 |
|------|------|
| `comfyui_dir` | ComfyUI をインストールしたフォルダ |
| `comfyui_python` | ComfyUI の Python 実行ファイルのパス |
| `flask_port` | UI の待受ポート（通常 5000 のまま） |

---

## 起動しない場合

1. `config.json` の `comfyui_dir` が正しいパスか確認する
2. `セットアップ.bat` を再実行してパッケージを再インストールする
3. `起動.bat` で起動して黒いウィンドウのエラーメッセージを確認する

```
ComfyUI\.venv\Scripts\python.exe -m pip install flask requests Pillow
```

---

## 機能の詳細

`FLUX_UI_説明書.docx` を参照してください。 
各機能のスクリーンショット付きで操作手順を説明しています。

---

## SeedVR2 モデル配置

SeedVR2 のカスタムノードは `nightly` ブランチで入ります。モデルは ComfyUI 側の下記フォルダに配置してください。

```text
C:\AI\ComfyUI\models\SEEDVR2\
```

この standalone の動画アップスケール workflow が標準で参照するファイル名は次の2つです。

```text
seedvr2_ema_7b_sharp_fp8_e4m3fn_mixed_block35_fp16.safetensors
ema_vae_fp16.safetensors
```

`config.json` の `comfyui_dir` を別の場所にしている場合は、その ComfyUI 配下の `models\SEEDVR2\` に入れてください。
