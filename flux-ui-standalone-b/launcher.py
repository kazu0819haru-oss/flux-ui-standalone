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
    """ComfyUI .venv の Python を探す。なければシステム Python。"""
    candidates = [
        os.path.join(comfy_dir, ".venv", "Scripts", "python.exe"),
        os.path.join(comfy_dir, "python_embeded", "python.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return sys.executable


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
        from tkinter import filedialog, messagebox
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

    root.update_idletasks()
    w, h = 500, 300
    x = (root.winfo_screenwidth()  - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")

    tk.Label(root, text="FLUX UI セットアップ", bg=BG, fg=ACC,
             font=("Segoe UI", 14, "bold")).pack(pady=(20, 4))
    tk.Label(root, text="ComfyUI がインストールされているフォルダを指定してください。",
             bg=BG, fg=FG, font=FONT).pack(pady=(0, 16))

    frame = tk.Frame(root, bg=BG)
    frame.pack(fill="x", padx=30)

    tk.Label(frame, text="ComfyUI フォルダ:", bg=BG, fg=FG, font=FONT,
             anchor="w").pack(fill="x")

    row = tk.Frame(frame, bg=BG)
    row.pack(fill="x", pady=(4, 0))

    path_var = tk.StringVar(value=r"C:\AI\ComfyUI")
    entry = tk.Entry(row, textvariable=path_var, bg=BG2, fg=FG,
                     insertbackground=FG, relief="flat", font=FONT, bd=4)
    entry.pack(side="left", fill="x", expand=True)

    def browse():
        d = filedialog.askdirectory(title="ComfyUI フォルダを選択")
        if d:
            path_var.set(d.replace("/", "\\"))

    tk.Button(row, text="参照...", bg=BG2, fg=FG, relief="flat",
              font=FONT, cursor="hand2", command=browse,
              activebackground="#333", activeforeground=FG,
              bd=0, padx=8).pack(side="left", padx=(6, 0))

    status_var = tk.StringVar()
    tk.Label(root, textvariable=status_var, bg=BG, fg="#f87171",
             font=("Segoe UI", 9)).pack(pady=(10, 0))

    def on_ok():
        d = path_var.get().strip()
        if not d:
            status_var.set("フォルダを入力してください。")
            return
        main_py = os.path.join(d, "main.py")
        if not os.path.isfile(main_py):
            status_var.set(f"main.py が見つかりません: {d}")
            return
        result["comfyui_dir"] = d
        result["comfyui_python"] = find_python(d)
        result["flask_port"] = 5000
        root.destroy()

    btn_frame = tk.Frame(root, bg=BG)
    btn_frame.pack(pady=16)
    tk.Button(btn_frame, text="  セットアップ開始  ", bg=ACC, fg="#000",
              font=("Segoe UI", 10, "bold"), relief="flat",
              cursor="hand2", command=on_ok, bd=0, padx=6, pady=6).pack()

    root.mainloop()
    return result if result else None


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

    comfy_dir  = cfg.get("comfyui_dir", r"C:\AI\ComfyUI")
    python_exe = cfg.get("comfyui_python") or find_python(comfy_dir)
    if not os.path.isfile(python_exe):
        log(f"ComfyUI Python が見つからない → システム Python を使用")
        python_exe = sys.executable
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
