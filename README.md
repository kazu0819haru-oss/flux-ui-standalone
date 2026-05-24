# FLUX UI Standalone

FLUX.1 / Wan2.2 による AI 画像生成フロントエンドのポータブルパッケージです。  
ComfyUI をバックエンドとして動作します。

![FLUX UI スクリーンショット](flux-ui-standalone-b/docs/screenshots/01_main_overview.png)

---

## ダウンロード

| パッケージ | 対象 | ダウンロード |
|-----------|------|-------------|
| **EXE 版** (flux-ui-standalone-b) | Python 不要・ダブルクリック起動 | [最新リリース → Releases](../../releases/latest) |
| **Batch 版** (flux-ui-standalone-c) | Python が必要・バッチ起動 | [最新リリース → Releases](../../releases/latest) |

> ⚠ **どちらも ComfyUI のインストールが別途必要です。**

---

## 必要なもの

- **Windows 10/11 (64bit)**
- **ComfyUI** がインストール済みで起動できること
  - [ComfyUI 公式](https://github.com/comfyanonymous/ComfyUI)
- EXE 版：追加不要
- Batch 版：Python 3.10 以上

---

## 主な機能

| 機能 | 説明 |
|------|------|
| txt2img | テキストから画像生成 |
| img2img | 画像を参考に再生成 |
| インペイント | 画像の一部を塗り直し |
| アウトペイント | 画像の周囲を拡張 |
| アップスケール | 2x/4x 高解像度化 |
| Kontext | 画像の内容を自然言語で編集 |
| Redux | 画像スタイル参照生成 |
| Canny / Depth | ControlNet による構図制御 |
| Wan2.2 | テキスト・画像からの動画生成 |
| LoRA | モデルのカスタマイズ |
| ギャラリー | 生成画像の管理・検索・お気に入り |

---

## セットアップ

詳しくは各パッケージの `README.md` と `FLUX_UI_説明書.docx` を参照してください。

### EXE 版（簡単）
1. ZIP を解凍
2. `FLUX_UI_Launcher.exe` をダブルクリック
3. ComfyUI フォルダを指定してセットアップ完了

### Batch 版
1. ZIP を解凍
2. `セットアップ.bat` を実行（初回のみ）
3. 次回から `起動.vbs` をダブルクリック

---

## 既存の flux-ui との関係

このリポジトリはオリジナルの `flux-ui` を**他の PC でも動くよう改造したポータブル版**です。  
オリジナルは変更していません。

---

## ライセンス

個人・学習目的での使用に限ります。
