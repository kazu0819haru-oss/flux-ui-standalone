"""
FLUX UI Launcher
- 初回起動時: ComfyUI パス設定ウィザードを表示
- 依存パッケージを自動インストール
- Flask (app.py) を起動してブラウザを開く
"""
import os
import sys
import json
import subprocess
import threading
import time
import webbrowser
import socket
import traceback

# このEXEと同じフォルダを基点にする
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
APP_DIR     = os.path.join(BASE_DIR, "app")
APP_PY      = os.path.join(APP_DIR, "app.py")
REQ_FILE    = os.path.join(APP_DIR, "requirements.txt")
LOG_PATH    = os.path.join(BASE_DIR, "launcher.log")


def log(msg):
    """ログをファイルに書き出す（問題調査用）"""
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def show_error(title, msg):
    """tkinter でエラーダイアログを表示する"""
    log(f"ERROR: {msg}")
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, msg)
        root.destroy()
    except Exception:
        pass


def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def find_python(comfy_dir):
    """ComfyUI の Python を探す。.venv → python_embeded → システム Python の順。"""
    candidates = [
        os.path.join(comfy_dir, ".venv", "Scripts", "python.exe"),
        os.path.join(comfy_dir, "python_embeded", "python.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    # システム Python を where コマンドで探す
    try:
        result = subprocess.run(
            ["where", "python"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                p = line.strip()
                # Windows Store のスタブ (WindowsApps) は除外
                if p and os.path.isfile(p) and "WindowsApps" not in p:
                    return p
    except Exception:
        pass
    if not getattr(sys, 'frozen', False):
        return sys.executable
    return ""


def port_open(port):
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=0.5)
        s.close()
        return True
    except OSError:
        return False


def show_setup_wizard():
    """tkinter でセットアップウィザードを表示し、設定 dict を返す。"""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        show_error("エラー", "tkinter が利用できません。config.json を直接編集してください。")
        return None

    result = {}

    root = tk.Tk()
    root.title("FLUX UI - 初回セットアップ")
    root.resizable(False, False)
    root.configure(bg="#1a1a1a")

    BG   = "#1a1a1a"
    FG   = "#f0f0f0"
    ACC  = "#bef264"
    BG2  = "#252525"
    FONT = ("Segoe UI", 10)
    FONT_S = ("Segoe UI", 8)

    root.update_idletasks()
    w, h = 520, 380
    x = (root.winfo_screenwidth()  - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")

    tk.Label(root, text="FLUX UI セットアップ", bg=BG, fg=ACC,
             font=("Segoe UI", 14, "bold")).pack(pady=(18, 2))
    tk.Label(root, text="ComfyUI フォルダと Python を指定してください。",
             bg=BG, fg=FG, font=FONT).pack(pady=(0, 12))

    frame = tk.Frame(root, bg=BG)
    frame.pack(fill="x", padx=30)

    # --- ComfyUI フォルダ ---
    tk.Label(frame, text="ComfyUI フォルダ:", bg=BG, fg=FG, font=FONT,
             anchor="w").pack(fill="x")
    row1 = tk.Frame(frame, bg=BG)
    row1.pack(fill="x", pady=(4, 0))

    path_var = tk.StringVar(value=r"C:\AI\ComfyUI")
    entry1 = tk.Entry(row1, textvariable=path_var, bg=BG2, fg=FG,
                      insertbackground=FG, relief="flat", font=FONT, bd=4)
    entry1.pack(side="left", fill="x", expand=True)

    def browse_comfy():
        d = filedialog.askdirectory(title="ComfyUI フォルダを選択")
        if d:
            d = d.replace("/", "\\")
            path_var.set(d)
            py = find_python(d)
            if py:
                py_var.set(py)

    tk.Button(row1, text="参照...", bg=BG2, fg=FG, relief="flat",
              font=FONT, cursor="hand2", command=browse_comfy,
              activebackground="#333", activeforeground=FG,
              bd=0, padx=8).pack(side="left", padx=(6, 0))

    # --- Python パス ---
    tk.Label(frame, text="Python (python.exe):", bg=BG, fg=FG, font=FONT,
             anchor="w").pack(fill="x", pady=(14, 0))

    py_var = tk.StringVar(value=find_python(path_var.get()) or "")
    row2 = tk.Frame(frame, bg=BG)
    row2.pack(fill="x", pady=(4, 0))

    entry2 = tk.Entry(row2, textvariable=py_var, bg=BG2, fg=FG,
                      insertbackground=FG, relief="flat", font=FONT, bd=4)
    entry2.pack(side="left", fill="x", expand=True)

    def browse_python():
        p = filedialog.askopenfilename(
            title="python.exe を選択",
            filetypes=[("Python", "python.exe"), ("すべて", "*.*")],
        )
        if p:
            py_var.set(p.replace("/", "\\"))

    tk.Button(row2, text="参照...", bg=BG2, fg=FG, relief="flat",
              font=FONT, cursor="hand2", command=browse_python,
              activebackground="#333", activeforeground=FG,
              bd=0, padx=8).pack(side="left", padx=(6, 0))

    tk.Label(frame,
             text="ComfyUI ポータブル版: python_embeded\\python.exe  /  venv 版: .venv\\Scripts\\python.exe",
             bg=BG, fg="#888", font=FONT_S, anchor="w").pack(fill="x", pady=(4, 0))

    status_var = tk.StringVar()
    tk.Label(root, textvariable=status_var, bg=BG, fg="#f87171",
             font=("Segoe UI", 9)).pack(pady=(10, 0))

    def on_ok():
        d = path_var.get().strip()
        if not d:
            status_var.set("ComfyUI フォルダを入力してください。")
            return
        main_py = os.path.join(d, "main.py")
        if not os.path.isfile(main_py):
            status_var.set(f"main.py が見つかりません: {d}")
            return
        py = py_var.get().strip()
        if not py or not os.path.isfile(py):
            status_var.set("python.exe が見つかりません。パスを確認してください。")
            return
        result["comfyui_dir"] = d
        result["comfyui_python"] = py
        result["flask_port"] = 5000
        root.destroy()

    btn_frame = tk.Frame(root, bg=BG)
    btn_frame.pack(pady=14)
    tk.Button(btn_frame, text="  セットアップ開始  ", bg=ACC, fg="#000",
              font=("Segoe UI", 10, "bold"), relief="flat",
              cursor="hand2", command=on_ok, bd=0, padx=6, pady=6).pack()

    root.mainloop()
    return result if result else None


CUSTOM_NODES = [
    {
        "name": "ComfyUI-GGUF",
        "url": "https://github.com/city96/ComfyUI-GGUF",
    },
    {
        "name": "comfyui_controlnet_aux",
        "url": "https://github.com/Fannovel16/comfyui_controlnet_aux",
    },
    {
        "name": "ComfyUI-Impact-Pack",
        "url": "https://github.com/ltdrdata/ComfyUI-Impact-Pack",
    },
    {
        "name": "ComfyUI-Custom-Scripts",
        "url": "https://github.com/pythongosssss/ComfyUI-Custom-Scripts",
    },
    {
        "name": "ComfyUI-VideoHelperSuite",
        "url": "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite",
    },
    {
        "name": "ComfyUI-SeedVR2_VideoUpscaler",
        "url": "https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler",
        "branch": "nightly",
    },
]


def install_custom_nodes(comfy_dir, python_exe, label_var=None):
    """必要なカスタムノードを git clone でインストールする（初回のみ）。"""
    custom_nodes_dir = os.path.join(comfy_dir, "custom_nodes")
    os.makedirs(custom_nodes_dir, exist_ok=True)

    try:
        subprocess.check_call(
            ["git", "--version"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except Exception:
        log("git が見つかりません。カスタムノードの自動インストールをスキップします。")
        return

    for node in CUSTOM_NODES:
        target = os.path.join(custom_nodes_dir, node["name"])
        branch = node.get("branch")
        if os.path.isdir(target):
            log(f"既存ノードを確認: {node['name']}")
            if branch:
                try:
                    subprocess.check_call(
                        ["git", "-C", target, "fetch", "origin", branch, "--depth=1"],
                        timeout=180,
                    )
                    subprocess.check_call(
                        ["git", "-C", target, "switch", branch],
                        timeout=60,
                    )
                    subprocess.check_call(
                        ["git", "-C", target, "pull", "--ff-only", "origin", branch],
                        timeout=180,
                    )
                except Exception as e:
                    log(f"ブランチ更新失敗: {node['name']}: {e}")
                    continue

        if label_var is not None:
            try:
                label_var.set(f"カスタムノード: {node['name']}")
            except Exception:
                pass

        if not os.path.isdir(target):
            log(f"git clone: {node['url']}")
            cmd = ["git", "clone", "--depth=1"]
            if branch:
                cmd += ["--branch", branch, "--single-branch"]
            cmd += [node["url"], target]
            try:
                subprocess.check_call(cmd, timeout=180)
            except Exception as e:
                log(f"クローン失敗: {node['name']}: {e}")
                continue

        req = os.path.join(target, "requirements.txt")
        if os.path.isfile(req):
            log(f"pip install: {node['name']}")
            try:
                subprocess.check_call(
                    [python_exe, "-m", "pip", "install", "-r", req,
                     "--quiet", "--disable-pip-version-check"],
                    timeout=300,
                )
            except Exception as e:
                log(f"pip install 失敗: {node['name']}: {e}")

    log("カスタムノードのインストール完了。")


def install_requirements(python_exe):
    """requirements.txt のパッケージをインストール。"""
    if not os.path.isfile(REQ_FILE):
        return True
    log("依存パッケージをインストール中...")
    try:
        subprocess.check_call(
            [python_exe, "-m", "pip", "install", "-r", REQ_FILE,
             "--quiet", "--disable-pip-version-check"],
            timeout=300,
        )
        log("インストール完了。")
        return True
    except Exception as e:
        log(f"インストール失敗: {e}")
        show_error("インストールエラー",
                   f"パッケージのインストールに失敗しました。\n\n"
                   f"Python: {python_exe}\n\n{e}\n\n"
                   f"詳細は launcher.log を確認してください。")
        return False


def show_progress_window(msg="起動中..."):
    try:
        import tkinter as tk
    except ImportError:
        return lambda: None

    win = [None]
    ready = threading.Event()

    def _run():
        root = tk.Tk()
        root.title("FLUX UI")
        root.resizable(False, False)
        root.configure(bg="#1a1a1a")
        w, h = 360, 120
        x = (root.winfo_screenwidth()  - w) // 2
        y = (root.winfo_screenheight() - h) // 2
        root.geometry(f"{w}x{h}+{x}+{y}")
        tk.Label(root, text="FLUX UI", bg="#1a1a1a", fg="#bef264",
                 font=("Segoe UI", 13, "bold")).pack(pady=(22, 4))
        tk.Label(root, text=msg, bg="#1a1a1a", fg="#a0a0a0",
                 font=("Segoe UI", 9)).pack()
        win[0] = root
        ready.set()
        root.mainloop()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    ready.wait(timeout=3)
    return lambda: win[0].destroy() if win[0] else None


def main():
    log(f"FLUX UI Launcher 起動 BASE_DIR={BASE_DIR}")
    log(f"APP_PY={APP_PY}")

    cfg = load_config()
    log(f"config={cfg}")

    # --- 初回セットアップ ---
    if not cfg.get("comfyui_dir") or not os.path.isdir(cfg["comfyui_dir"]):
        log("初回セットアップが必要")
        close_prog = show_progress_window("初回セットアップが必要です...")
        close_prog()
        new_cfg = show_setup_wizard()
        if not new_cfg:
            log("セットアップキャンセル")
            sys.exit(0)
        cfg = new_cfg
        save_config(cfg)
        log(f"設定保存: {cfg}")
        close_prog2 = show_progress_window("パッケージをインストール中...")
        python_exe = cfg.get("comfyui_python", sys.executable)
        ok = install_requirements(python_exe)
        close_prog2()
        if not ok:
            sys.exit(1)

        close_prog3 = show_progress_window(
            "カスタムノードをインストール中...\n(初回のみ / 数分かかる場合があります)"
        )
        install_custom_nodes(cfg["comfyui_dir"], python_exe)
        close_prog3()

    comfy_dir  = cfg.get("comfyui_dir", r"C:\AI\ComfyUI")
    python_exe = cfg.get("comfyui_python") or find_python(comfy_dir)
    if not python_exe or not os.path.isfile(python_exe):
        log(f"ComfyUI Python が見つからない → システム Python を使用")
        python_exe = sys.executable

    # フリーズ EXE 自身が python_exe になると無限起動するため検出して止める
    if getattr(sys, 'frozen', False):
        try:
            if os.path.normcase(os.path.abspath(python_exe)) == \
               os.path.normcase(os.path.abspath(sys.executable)):
                show_error(
                    "Python が見つかりません",
                    f"ComfyUI の Python インタープリターが見つかりません。\n\n"
                    f"ComfyUI フォルダ: {comfy_dir}\n\n"
                    f"以下のいずれかが存在することを確認してください:\n"
                    f"  .venv\\Scripts\\python.exe\n"
                    f"  python_embeded\\python.exe\n\n"
                    f"ComfyUI ポータブル版をお使いの場合は\n"
                    f"python_embeded フォルダが存在するか確認してください。"
                )
                sys.exit(1)
        except Exception as e:
            log(f"python_exe 検証エラー: {e}")

    flask_port = int(cfg.get("flask_port", 5000))

    log(f"python_exe={python_exe}")
    log(f"comfy_dir={comfy_dir}")
    log(f"flask_port={flask_port}")

    # --- app.py の存在確認 ---
    if not os.path.isfile(APP_PY):
        show_error("起動エラー",
                   f"app.py が見つかりません:\n{APP_PY}\n\n"
                   f"フォルダ構成を確認してください。")
        sys.exit(1)

    close_prog = show_progress_window("FLUX UI を起動中...")

    # --- ComfyUI が起動していなければ起動 ---
    if not port_open(8188):
        comfy_main = os.path.join(comfy_dir, "main.py")
        if os.path.isfile(comfy_main):
            log(f"ComfyUI を起動: {comfy_dir}")
            subprocess.Popen(
                [python_exe, "main.py", "--fast"],
                cwd=comfy_dir,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        else:
            log("ComfyUI main.py なし。手動起動が必要。")
    else:
        log("ComfyUI は既に起動中")

    # --- Flask を起動 ---
    env = os.environ.copy()
    env["COMFYUI_DIR"]    = comfy_dir
    env["COMFYUI_PYTHON"] = python_exe

    log("Flask 起動中...")
    flask_proc = subprocess.Popen(
        [python_exe, APP_PY],
        cwd=APP_DIR,
        env=env,
        stdout=open(os.path.join(BASE_DIR, "flask.log"), "w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
    )

    # --- ポート待機（最大 45 秒）---
    deadline = time.time() + 45
    while time.time() < deadline:
        if port_open(flask_port):
            log(f"Flask 起動完了 port={flask_port}")
            break
        if flask_proc.poll() is not None:
            # Flask が予期せず終了
            close_prog()
            show_error("起動エラー",
                       f"Flask の起動に失敗しました。\n\n"
                       f"flask.log を確認してください:\n{BASE_DIR}\\flask.log")
            sys.exit(1)
        time.sleep(0.5)
    else:
        close_prog()
        show_error("タイムアウト",
                   f"Flask が {flask_port} 番ポートで起動しませんでした。\n\n"
                   f"flask.log を確認してください:\n{BASE_DIR}\\flask.log")
        sys.exit(1)

    close_prog()

    # --- ブラウザを開く ---
    webbrowser.open(f"http://localhost:{flask_port}/loading")
    log(f"ブラウザ起動: http://localhost:{flask_port}")

    # --- Flask が終了するまで待機 ---
    flask_proc.wait()
    log("Flask 終了")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        err = traceback.format_exc()
        log(f"未処理例外:\n{err}")
        show_error("予期しないエラー", f"エラーが発生しました:\n\n{err}")
        sys.exit(1)
