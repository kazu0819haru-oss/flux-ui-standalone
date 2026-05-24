# FLUX UI Standalone（EXE版）

FLUX.1 / Wan2.2 を使った AI 画像生成 UI のポータブルパッケージです。  
ComfyUI をバックエンドとして動作します。

---

## 必要なもの

- **Windows 10/11 (64bit)**
- **ComfyUI** がインストール済み（`main.py` が存在するフォルダ）
- ComfyUI の仮想環境に `flask`, `requests`, `Pillow` などがインストールされていること  
  → 初回起動時に自動インストールします

---

## 初回セットアップ

1. このフォルダを PC の好きな場所に置く（例：`C:\FLUX_UI\`）
2. **`FLUX_UI_Launcher.exe` をダブルクリック**
3. セットアップ画面が開く → ComfyUI フォルダを指定して「セットアップ開始」
4. 自動でパッケージインストールが始まる（数分かかることがあります）
5. インストール完了後、ブラウザが自動で開いて UI が表示される

> **補足:** 2回目以降は手順2だけで起動します。

---

## フォルダ構成

```
FLUX_UI_Launcher.exe   ← ダブルクリックで起動
config.json            ← ComfyUI パス等の設定（自動生成）
app/
  app.py               ← Flask サーバー本体
  static/              ← UI ファイル
  requirements.txt     ← 必要パッケージリスト
FLUX_UI_説明書.docx    ← 操作マニュアル（各機能の使い方）
launcher.log           ← 起動ログ（起動しない時の調査用）
flask.log              ← Flask ログ（エラー詳細）
```

---

## config.json の手動設定

セットアップ後に ComfyUI のパスを変えたい場合は `config.json` を直接編集してください。

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

## EXE が反応しない場合

1. `launcher.log` をメモ帳で開いてエラー内容を確認する
2. `flask.log` も同様に確認する
3. `config.json` の `comfyui_dir` が正しいパスか確認する
4. ComfyUI の Python に Flask がインストールされているか確認する

```
ComfyUI\.venv\Scripts\python.exe -m pip install flask requests Pillow
```

---

## 機能の詳細

`FLUX_UI_説明書.docx` を参照してください。  
各機能のスクリーンショット付きで操作手順を説明しています。
