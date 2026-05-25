import copy
import io
import json
import os
import random
import re
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
import zipfile
from functools import wraps
from flask import (Flask, request, jsonify, send_from_directory, Response,
                   send_file, session, redirect, url_for, render_template_string)
import requests

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass


# ── Portable config ───────────────────────────────────────────────
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_APP_DIR, "config.json")

def _load_comfyui_config():
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as _f:
            return json.load(_f)
    except Exception:
        return {}

_PORTABLE_CONFIG = _load_comfyui_config()
_COMFYUI_DIR = (os.environ.get("COMFYUI_DIR") or
                _PORTABLE_CONFIG.get("comfyui_dir", r"C:\AI\ComfyUI"))
_COMFYUI_PYTHON = (os.environ.get("COMFYUI_PYTHON") or
                   _PORTABLE_CONFIG.get("comfyui_python",
                       os.path.join(_COMFYUI_DIR, ".venv", "Scripts", "python.exe")))
_FLASK_PORT = int(_PORTABLE_CONFIG.get("flask_port", 5000))

COMFY_URL = "http://127.0.0.1:8188"

# ── ComfyUI 自動起動 (ポータブル版 - 設定ファイルベース) ──────────────────
_comfy_starting = False
_comfy_start_lock = threading.Lock()
_last_start_attempt = 0.0

def _maybe_start_comfy():
    """ComfyUIが落ちていれば config.json の Python で起動する（5分に1回まで）"""
    global _comfy_starting, _last_start_attempt
    with _comfy_start_lock:
        now = time.time()
        if _comfy_starting or now - _last_start_attempt < 300:
            return
        try:
            requests.get(f"{COMFY_URL}/system_stats", timeout=1)
            return
        except Exception:
            pass
        comfy_dir = _COMFYUI_DIR
        comfy_main = os.path.join(comfy_dir, "main.py")
        if not os.path.isfile(comfy_main):
            return
        _comfy_starting = True
        _last_start_attempt = now

    def _run():
        global _comfy_starting
        try:
            python_exe = _COMFYUI_PYTHON
            if not os.path.isfile(python_exe):
                python_exe = "python"
            subprocess.Popen(
                [python_exe, "main.py", "--fast"],
                cwd=comfy_dir,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            print(f"[auto-start] ComfyUI起動: {comfy_dir}")
        except Exception as e:
            print(f"[auto-start] 失敗: {e}")
        finally:
            time.sleep(180)
            _comfy_starting = False

    threading.Thread(target=_run, daemon=True).start()

# FLUX works best at ≤1536px per side. Images larger than this are downscaled
# before upload so the VAE / VRAM stays manageable.
FLUX_MAX_SIDE = 1536

MODEL_CONFIG = {
    "unet":   "flux1-dev.safetensors",
    "vae":    "ae.safetensors",
    "clip_l": "clip_l.safetensors",
    "t5":     "t5xxl_fp16.safetensors",
}

UNET_DIR         = os.path.join(_COMFYUI_DIR, "models", "unet")
DIFFM_DIR        = os.path.join(_COMFYUI_DIR, "models", "diffusion_models")
TEXT_ENCODER_DIR = os.path.join(_COMFYUI_DIR, "models", "text_encoders")
CLIP_DIR         = os.path.join(_COMFYUI_DIR, "models", "clip")
VAE_DIR          = os.path.join(_COMFYUI_DIR, "models", "vae")

FLUX2_CONFIG = {
    "unet": r"flux2\flux2_dev_fp8mixed.safetensors",
    "vae": r"flux2\flux2-vae.safetensors",
    "clip": r"flux2\mistral_3_small_flux2_fp8.safetensors",
}
FLUX2_ALT_CLIPS = [
    r"flux2\mistral_3_small_flux2_fp8.safetensors",
]
FLUX2_TURBO_LORA = "Flux_2-Turbo-LoRA_comfyui.safetensors"

WAN22_CONFIG = {
    "text_encoder": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    "vae": "wan_2.1_vae.safetensors",
    "high": {
        "unet": "Wan2.2-I2V-A14B-HighNoise-Q5_K_M.gguf",
        "lora": "Wan2.2-Lightning_I2V-A14B-4steps-lora_HIGH_fp16.safetensors",
        "lora_strength": 1.5,
    },
    "low": {
        "unet": "Wan2.2-I2V-A14B-LowNoise-Q5_K_M.gguf",
        "lora": "Wan2.2-Lightning_I2V-A14B-4steps-lora_LOW_fp16.safetensors",
        "lora_strength": 1.0,
    },
}

WAN22_HIGH_UNET_CANDIDATES = [
    WAN22_CONFIG["high"]["unet"],
    "wan2.2_i2v_high_noise_14B_Q5_K_M.gguf",
]
WAN22_LOW_UNET_CANDIDATES = [
    WAN22_CONFIG["low"]["unet"],
    "wan2.2_i2v_low_noise_14B_Q5_K_M.gguf",
]

KONTEXT_MODEL = "flux1-kontext-dev.safetensors"
KONTEXT_FP8_MODEL = "flux1-dev-kontext_fp8_scaled.safetensors"
KONTEXT_MODEL_DIR = os.path.join(_COMFYUI_DIR, "models", "diffusion_models")
T5_FP8_MODEL = "t5xxl_fp8_e4m3fn_scaled.safetensors"

CN_UPSCALER_MODEL = "Flux.1-dev-Controlnet-Upscaler.safetensors"
CN_UPSCALER_DIR   = os.path.join(_COMFYUI_DIR, "models", "controlnet")

FILL_MODEL     = "flux1-fill-dev.safetensors"
FILL_MODEL_DIR = os.path.join(_COMFYUI_DIR, "models", "diffusion_models")

REDUX_MODEL      = "flux1-redux-dev.safetensors"
REDUX_MODEL_DIR  = os.path.join(_COMFYUI_DIR, "models", "style_models")
REDUX_CLIP_MODEL = "sigclip_vision_patch14_384.safetensors"
REDUX_CLIP_DIR   = os.path.join(_COMFYUI_DIR, "models", "clip_vision")

LORA_MODEL_DIR = os.path.join(_COMFYUI_DIR, "models", "loras")

# BFL official Canny/Depth are not loaded by ControlNetLoader.
# LoRA variants use LoraLoaderModelOnly; full variants use UNETLoader directly.
BFL_CONTROL_LORAS = {
    "canny": "flux1-canny-dev-lora.safetensors",
    "depth": "flux1-depth-dev-lora.safetensors",
}
BFL_CONTROL_FULL_MODELS = {
    "canny": "flux1-canny-dev.safetensors",
    "depth": "flux1-depth-dev.safetensors",
}
BFL_CN_MODELS = {
    "canny": "flux1-canny-instantx.safetensors",
    "depth": "xlabs-flux-depth-v3.safetensors",
}
CN_PREPROCESSOR_MAP = {
    "flux1-canny-instantx.safetensors": "CannyEdgePreprocessor",
    "xlabs-flux-depth-v3.safetensors": "DepthAnythingV2Preprocessor",
}

STYLE_SUFFIXES = {
    "photo":    ", photorealistic, ultra sharp, professional photography, 8k UHD, DSLR quality",
    "anime":    ", anime style, vibrant colors, detailed illustration, manga, Studio Ghibli inspired",
    "oil":      ", oil painting, thick brushstrokes, rich colors, impressionist, museum quality",
    "water":    ", watercolor painting, soft washes, delicate details, artistic, painterly",
    "cinema":   ", cinematic, anamorphic, film grain, dramatic lighting, movie still, color graded",
    "concept":  ", concept art, digital painting, detailed, artstation trending, matte painting",
    "minimal":  ", minimalist design, clean composition, elegant, simple, refined",
    "render3d": ", 3D render, octane render, ray tracing, volumetric lighting, photorealistic",
}

DEFAULT_SAMPLERS = ["euler", "dpm_2", "dpm_2_ancestral", "heun", "dpmpp_2s_ancestral",
                    "dpmpp_sde", "dpmpp_2m", "dpmpp_2m_sde", "ddim", "uni_pc"]
DEFAULT_SCHEDULERS = ["simple", "normal", "karras", "exponential", "sgm_uniform", "beta"]

app = Flask(__name__, static_folder="static")

# ── Simple password auth ───────────────────────────────────────
FLASK_PASSWORD = os.environ.get("FLUX_PASSWORD", "")
if not FLASK_PASSWORD:
    _pw_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".password")
    if os.path.exists(_pw_file):
        with open(_pw_file) as _f:
            FLASK_PASSWORD = _f.read().strip()

_SK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".secret_key")
if os.path.exists(_SK_FILE):
    with open(_SK_FILE) as _f:
        app.secret_key = _f.read().strip()
else:
    _sk = secrets.token_hex(32)
    with open(_SK_FILE, "w") as _f:
        _f.write(_sk)
    app.secret_key = _sk

_AUTH_EXEMPT = {"login_page", "logout", "loading_page", "ping", "health", "keepalive"}
_ACCESS_LOG  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "access.log")

def _log_access(status: str, note: str = ""):
    ts   = time.strftime("%Y-%m-%d %H:%M:%S")
    ip   = request.remote_addr or "-"
    line = f"{ts}  {ip:<20} {status:<8} {request.method} {request.path}"
    if note:
        line += f"  [{note}]"
    try:
        with open(_ACCESS_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

@app.before_request
def _require_login():
    if request.remote_addr not in ("127.0.0.1", "::1"):
        _maybe_start_comfy()  # 外部接続時にComfyUIを自動起動
    if not FLASK_PASSWORD:
        return
    if request.remote_addr in ("127.0.0.1", "::1"):
        return  # ローカルからは認証不要
    if request.endpoint in _AUTH_EXEMPT:
        return
    if session.get("logged_in"):
        _log_access("OK")
        return
    _log_access("BLOCK", "未ログイン")
    return redirect(url_for("login_page"))

_LOGIN_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>FLUX UI — ログイン</title>
  <style>
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
    body{background:#070707;color:#fff;font-family:system-ui,sans-serif;
         display:flex;align-items:center;justify-content:center;min-height:100vh}
    .card{background:#111;border:1px solid #1e1e1e;border-radius:14px;
          padding:2.5rem;width:320px;display:flex;flex-direction:column;gap:1.4rem}
    .logo{font-size:1.8rem;font-weight:900;letter-spacing:-.04em;text-align:center}
    .logo span{color:#bef264}
    label{display:block;font-size:.72rem;color:rgba(255,255,255,.45);
          letter-spacing:.1em;text-transform:uppercase;margin-bottom:.4rem}
    input[type=password]{width:100%;background:#0d0d0d;border:1px solid #252525;
          border-radius:8px;color:#fff;padding:.72rem 1rem;font-size:.95rem;
          outline:none;transition:border-color .18s}
    input[type=password]:focus{border-color:#bef264}
    button{background:#bef264;color:#000;border:none;border-radius:8px;
           padding:.78rem;font-size:.9rem;font-weight:700;cursor:pointer;
           transition:opacity .15s;width:100%}
    button:hover{opacity:.85}
    .err{font-size:.78rem;color:#f87171;text-align:center;
         background:rgba(248,113,113,.1);border-radius:6px;padding:.5rem}
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">FLUX<span>.</span></div>
    <form method="POST" style="display:flex;flex-direction:column;gap:1.1rem">
      <div>
        <label>パスワード</label>
        <input type="password" name="password" autofocus autocomplete="current-password">
      </div>
      {% if error %}<div class="err">{{ error }}</div>{% endif %}
      <button type="submit">ログイン</button>
    </form>
  </div>
</body>
</html>"""

@app.route("/login", methods=["GET", "POST"])
def login_page():
    if not FLASK_PASSWORD:
        return redirect("/")
    if request.method == "POST":
        if request.form.get("password") == FLASK_PASSWORD:
            session["logged_in"] = True
            _log_access("LOGIN", "成功")
            return redirect(request.args.get("next") or "/")
        _log_access("LOGIN", "失敗（パスワード不一致）")
        return render_template_string(_LOGIN_HTML, error="パスワードが違います"), 401
    return render_template_string(_LOGIN_HTML, error=None)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


def _is_japanese(text):
    return bool(re.search(r'[぀-ヿ㐀-䶿一-鿿ｦ-ﾟ]', text))


def _translate(text):
    text = text.replace("、", ", ")
    text = re.sub(r"\s*,\s*", ", ", text)
    try:
        from deep_translator import GoogleTranslator
        return GoogleTranslator(source="auto", target="en").translate(text)
    except Exception:
        return text


def _shrink_for_flux(img_bytes: bytes):
    """Resize image if either dimension exceeds FLUX_MAX_SIDE. Returns (bytes, w, h, was_resized).
    Also converts HEIC/HEIF (iPhone) to PNG automatically.
    Dimensions are snapped to multiples of 8 by center-cropping."""
    from PIL import Image as PILImage, ImageOps
    img = ImageOps.exif_transpose(PILImage.open(io.BytesIO(img_bytes))).convert("RGB")
    w, h = img.size
    if max(w, h) <= FLUX_MAX_SIDE:
        cw = (w // 8) * 8
        ch = (h // 8) * 8
        if cw != w or ch != h:
            img = img.crop(((w - cw) // 2, (h - ch) // 2,
                            (w - cw) // 2 + cw, (h - ch) // 2 + ch))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), cw, ch, False
    scale = FLUX_MAX_SIDE / max(w, h)
    new_w = (round(w * scale) // 8) * 8
    new_h = (round(h * scale) // 8) * 8
    img = img.resize((new_w, new_h), PILImage.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), new_w, new_h, True


def _resolve_base_model(model_name=None):
    if model_name and _is_visible_base_model(model_name):
        if _model_file_exists(KONTEXT_MODEL_DIR, model_name) or _model_file_exists(r"C:\AI\ComfyUI\models\unet", model_name):
            return model_name
    return MODEL_CONFIG["unet"]


def _is_flux2_model(model_name):
    return bool(model_name and re.search(r"flux[._-]?2", model_name, re.I))


def _is_wan22_model(model_name):
    return bool(model_name and re.search(r"wan2[._-]?2", model_name, re.I))


def _flux2_clip_name():
    for name in FLUX2_ALT_CLIPS:
        if _model_file_exists(TEXT_ENCODER_DIR, name) or _model_file_exists(CLIP_DIR, name):
            return name
    return FLUX2_CONFIG["clip"]


def _flux2_vae_name():
    return FLUX2_CONFIG["vae"]


def _flux2_model_info(model_name=None):
    return {
        "workflow": "flux2-dedicated",
        "model": model_name or FLUX2_CONFIG["unet"],
        "text_encoder": _flux2_clip_name(),
        "vae": _flux2_vae_name(),
        "lora": FLUX2_TURBO_LORA if _model_file_exists(LORA_MODEL_DIR, FLUX2_TURBO_LORA) else None,
    }


def _flux2_missing_requirements():
    missing = []
    info = _flux2_model_info()
    if not _model_file_exists(DIFFM_DIR, info["model"]):
        missing.append(f"diffusion model: {info['model']}")
    if not (
        _model_file_exists(r"C:\AI\ComfyUI\models\text_encoders", info["text_encoder"]) or
        _model_file_exists(r"C:\AI\ComfyUI\models\clip", info["text_encoder"])
    ):
        missing.append(f"text encoder: {info['text_encoder']}")
    if not _model_file_exists(r"C:\AI\ComfyUI\models\vae", info["vae"]):
        missing.append(f"vae: {info['vae']}")
    return missing


def _format_comfy_error(err):
    if not isinstance(err, dict):
        return str(err)
    msg = err.get("error", err)
    parts = []
    if isinstance(msg, dict):
        for key in ("message", "details", "type"):
            if msg.get(key):
                parts.append(str(msg[key]))
    elif msg:
        parts.append(str(msg))
    node_errors = err.get("node_errors") or {}
    if node_errors:
        brief = []
        for node_id, detail in list(node_errors.items())[:3]:
            if isinstance(detail, dict):
                class_type = detail.get("class_type") or detail.get("node_type") or "node"
                errors = detail.get("errors") or []
                emsg = ""
                if errors and isinstance(errors[0], dict):
                    emsg = errors[0].get("message") or errors[0].get("details") or ""
                brief.append(f"{node_id}:{class_type} {emsg}".strip())
            else:
                brief.append(f"{node_id}:{detail}")
        parts.append("node_errors: " + " / ".join(brief))
    return " | ".join(p for p in parts if p) or json.dumps(err, ensure_ascii=False)[:500]


def _build_model_nodes(model_name=None):
    return {
        "10": {"class_type": "VAELoader",
               "inputs": {"vae_name": MODEL_CONFIG["vae"]}},
        "11": {"class_type": "DualCLIPLoader",
               "inputs": {"clip_name1": MODEL_CONFIG["clip_l"],
                          "clip_name2": _t5_model_name(),
                          "type": "flux",
                          "device": "default"}},
        "12": {"class_type": "UNETLoader",
               "inputs": {"unet_name": _resolve_base_model(model_name), "weight_dtype": "default"}},
    }


def _chain_loras(wf, loras):
    """loras: [{name, strength}]. Returns (model_ref, clip_ref). Mutates wf."""
    model_ref = ["12", 0]
    clip_ref  = ["11", 0]
    for i, lora in enumerate(loras or []):
        if not lora.get("name"):
            continue
        node_id = f"100{i}"
        wf[node_id] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": model_ref,
                "clip":  clip_ref,
                "lora_name": lora["name"],
                "strength_model": float(lora.get("strength", 1.0)),
                "strength_clip":  float(lora.get("strength", 1.0)),
            },
        }
        model_ref = [node_id, 0]
        clip_ref  = [node_id, 1]
    return model_ref, clip_ref


def build_txt2img_workflow(prompt, negative, width, height, steps, seed, batch_size=1,
                            sampler="euler", scheduler="simple", cfg=1.0,
                            loras=None, model_name=None):
    wf = {}
    wf.update(_build_model_nodes(model_name))
    model_ref, clip_ref = _chain_loras(wf, loras or [])

    wf["6"] = {"class_type": "CLIPTextEncode",
               "inputs": {"text": prompt, "clip": clip_ref}}
    wf["33"] = {"class_type": "CLIPTextEncode",
                "inputs": {"text": negative or "", "clip": clip_ref}}
    wf["27"] = {"class_type": "EmptyLatentImage",
                "inputs": {"batch_size": batch_size, "height": height, "width": width}}
    wf["13"] = {
        "class_type": "KSampler",
        "inputs": {
            "cfg": cfg, "denoise": 1.0,
            "latent_image": ["27", 0], "model": model_ref,
            "negative": ["33", 0], "positive": ["6", 0],
            "sampler_name": sampler, "scheduler": scheduler,
            "seed": seed, "steps": steps,
        },
    }
    wf["8"] = {"class_type": "VAEDecode",
               "inputs": {"samples": ["13", 0], "vae": ["10", 0]}}
    wf["9"] = {"class_type": "SaveImage",
               "inputs": {"images": ["8", 0], "filename_prefix": "flux_ui"}}
    return wf


def build_flux2_workflow(prompt, width, height, steps, seed, batch_size=1,
                         model_name=None, refs=None, guidance=4.0, sampler="euler"):
    """FLUX.2 Dev workflow. Optional refs are uploaded ComfyUI image descriptors."""
    refs = (refs or [])[:10]
    wf = {
        "10": {"class_type": "VAELoader",
               "inputs": {"vae_name": _flux2_vae_name()}},
        "11": {"class_type": "CLIPLoader",
               "inputs": {"clip_name": _flux2_clip_name(), "type": "flux2", "device": "default"}},
        "12": {"class_type": "UNETLoader",
               "inputs": {"unet_name": model_name or FLUX2_CONFIG["unet"], "weight_dtype": "default"}},
        "6": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": ["11", 0]}},
        "26": {"class_type": "FluxGuidance",
               "inputs": {"conditioning": ["6", 0], "guidance": float(guidance)}},
        "47": {"class_type": "EmptyFlux2LatentImage",
               "inputs": {"width": int(width), "height": int(height), "batch_size": int(batch_size)}},
        "48": {"class_type": "Flux2Scheduler",
               "inputs": {"steps": int(steps), "width": int(width), "height": int(height)}},
        "16": {"class_type": "KSamplerSelect",
               "inputs": {"sampler_name": sampler or "euler"}},
        "25": {"class_type": "RandomNoise",
               "inputs": {"noise_seed": int(seed)}},
    }

    conditioning_ref = ["26", 0]
    next_id = 60
    for ref in refs:
        load_id, scale_id, enc_id, ref_id = map(str, range(next_id, next_id + 4))
        wf[load_id] = {"class_type": "LoadImage",
                       "inputs": {"image": ref["filename"], "upload": "image"}}
        wf[scale_id] = {"class_type": "ImageScaleToTotalPixels",
                        "inputs": {"image": [load_id, 0], "upscale_method": "area",
                                   "megapixels": 0.25, "resolution_steps": 1}}
        wf[enc_id] = {"class_type": "VAEEncode",
                      "inputs": {"pixels": [scale_id, 0], "vae": ["10", 0]}}
        wf[ref_id] = {"class_type": "ReferenceLatent",
                      "inputs": {"conditioning": conditioning_ref, "latent": [enc_id, 0]}}
        conditioning_ref = [ref_id, 0]
        next_id += 4

    if len(refs) > 1:
        method_id = str(next_id)
        wf[method_id] = {"class_type": "FluxKontextMultiReferenceLatentMethod",
                         "inputs": {"conditioning": conditioning_ref,
                                    "reference_latents_method": "index"}}
        conditioning_ref = [method_id, 0]

    wf["50"] = {"class_type": "LoraLoaderModelOnly",
                "inputs": {"model": ["12", 0],
                           "lora_name": FLUX2_TURBO_LORA,
                           "strength_model": 1.0}}
    wf["22"] = {"class_type": "BasicGuider",
                "inputs": {"model": ["50", 0], "conditioning": conditioning_ref}}
    wf["13"] = {"class_type": "SamplerCustomAdvanced",
                "inputs": {"noise": ["25", 0], "guider": ["22", 0],
                           "sampler": ["16", 0], "sigmas": ["48", 0],
                           "latent_image": ["47", 0]}}
    wf["8"] = {"class_type": "VAEDecode",
               "inputs": {"samples": ["13", 0], "vae": ["10", 0]}}
    wf["9"] = {"class_type": "SaveImage",
               "inputs": {"images": ["8", 0], "filename_prefix": "flux2_ui"}}
    return wf


def _wan22_unet_node(unet_name):
    """UnetLoaderGGUF (ComfyUI-GGUF) for .gguf files."""
    return {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": unet_name}}


def build_wan22_workflow(prompt, start_image_name, end_image_name=None,
                          steps=8, seed=None,
                          width=832, height=480, length=81, fps=16):
    """Wan2.2 I2V two-model split-step workflow (GGUF or safetensors + Lightning LoRA)."""
    if seed is None:
        seed = random.randint(0, 2**31 - 1)
    wf = {
        "1":  {"class_type": "CLIPLoader",
               "inputs": {"clip_name": WAN22_CONFIG["text_encoder"], "type": "wan"}},
        "2":  {"class_type": "CLIPTextEncode",
               "inputs": {"text": prompt, "clip": ["1", 0]}},
        "3":  {"class_type": "CLIPTextEncode",
               "inputs": {"text": "", "clip": ["1", 0]}},
        "4":  {"class_type": "VAELoader",
               "inputs": {"vae_name": WAN22_CONFIG["vae"]}},
        # High / Low noise model (GGUF or safetensors auto-detected)
        "5":  _wan22_unet_node(_resolve_wan22_unet(WAN22_HIGH_UNET_CANDIDATES)),
        "6":  _wan22_unet_node(_resolve_wan22_unet(WAN22_LOW_UNET_CANDIDATES)),
        # High noise LoRA (strength=1.5)
        "7":  {"class_type": "LoraLoaderModelOnly",
               "inputs": {"model": ["5", 0],
                          "lora_name": WAN22_CONFIG["high"]["lora"],
                          "strength_model": WAN22_CONFIG["high"]["lora_strength"]}},
        # Low noise LoRA (strength=1.0)
        "8":  {"class_type": "LoraLoaderModelOnly",
               "inputs": {"model": ["6", 0],
                          "lora_name": WAN22_CONFIG["low"]["lora"],
                          "strength_model": WAN22_CONFIG["low"]["lora_strength"]}},
        # ModelSamplingSD3 shift=4 for both models
        "9":  {"class_type": "ModelSamplingSD3",
               "inputs": {"model": ["7", 0], "shift": 4.0}},
        "10": {"class_type": "ModelSamplingSD3",
               "inputs": {"model": ["8", 0], "shift": 4.0}},
        # Start image
        "20": {"class_type": "LoadImage",
               "inputs": {"image": start_image_name, "upload": "image"}},
    }
    i2v_inputs = {
        "positive": ["2", 0],
        "negative": ["3", 0],
        "vae": ["4", 0],
        "start_image": ["20", 0],
        "width": int(width),
        "height": int(height),
        "length": int(length),
        "batch_size": 1,
    }
    if end_image_name:
        wf["21"] = {"class_type": "LoadImage",
                    "inputs": {"image": end_image_name, "upload": "image"}}
        i2v_inputs["end_image"] = ["21", 0]
        wf["30"] = {"class_type": "WanFirstLastFrameToVideo",
                    "inputs": i2v_inputs}
    else:
        wf["30"] = {"class_type": "WanImageToVideo",
                    "inputs": i2v_inputs}
    # Stage 1: high noise model, steps 0→4
    wf["40"] = {
        "class_type": "KSamplerAdvanced",
        "inputs": {
            "model": ["9", 0],
            "add_noise": "enable",
            "noise_seed": int(seed),
            "steps": int(steps),
            "cfg": 1.0,
            "sampler_name": "euler",
            "scheduler": "simple",
            "positive": ["30", 0],
            "negative": ["30", 1],
            "latent_image": ["30", 2],
            "start_at_step": 0,
            "end_at_step": 4,
            "return_with_leftover_noise": "enable",
        },
    }
    # Stage 2: low noise model, steps 4→end
    wf["41"] = {
        "class_type": "KSamplerAdvanced",
        "inputs": {
            "model": ["10", 0],
            "add_noise": "disable",
            "noise_seed": 0,
            "steps": int(steps),
            "cfg": 1.0,
            "sampler_name": "euler",
            "scheduler": "simple",
            "positive": ["30", 0],
            "negative": ["30", 1],
            "latent_image": ["40", 0],
            "start_at_step": 4,
            "end_at_step": 10000,
            "return_with_leftover_noise": "disable",
        },
    }
    wf["50"] = {"class_type": "VAEDecode",
                "inputs": {"samples": ["41", 0], "vae": ["4", 0]}}
    wf["51"] = {"class_type": "CreateVideo",
                "inputs": {"images": ["50", 0], "fps": int(fps)}}
    wf["52"] = {"class_type": "SaveVideo",
                "inputs": {"video": ["51", 0], "filename_prefix": "wan22_ui",
                           "format": "mp4", "codec": "h264"}}
    return wf


def _fill_model_name():
    """Use Fill model if installed, fall back to base model."""
    if _model_file_exists(FILL_MODEL_DIR, FILL_MODEL):
        return FILL_MODEL
    return MODEL_CONFIG["unet"]


def _kontext_models():
    models = []
    for name, label in (
        (KONTEXT_FP8_MODEL, "Kontext fp8 scaled"),
        (KONTEXT_MODEL, "Kontext full"),
    ):
        if _model_file_exists(KONTEXT_MODEL_DIR, name):
            models.append({"name": name, "label": label, "default": name == KONTEXT_FP8_MODEL})
    return models


def _kontext_model_name(requested=None):
    if requested:
        allowed = {m["name"] for m in _kontext_models()}
        if requested in allowed:
            return requested
    return KONTEXT_FP8_MODEL if _model_file_exists(KONTEXT_MODEL_DIR, KONTEXT_FP8_MODEL) else KONTEXT_MODEL


def _t5_model_name():
    text_encoder_dir = r"C:\AI\ComfyUI\models\text_encoders"
    clip_dir = r"C:\AI\ComfyUI\models\clip"
    if _model_file_exists(text_encoder_dir, T5_FP8_MODEL) or _model_file_exists(clip_dir, T5_FP8_MODEL):
        return T5_FP8_MODEL
    return MODEL_CONFIG["t5"]


def build_inpaint_workflow(image_name, mask_name, prompt, steps, seed,
                            denoise=1.0, sampler="euler", scheduler="normal", cfg=2.0,
                            guidance=30.0):
    wf = {}
    wf.update(_build_model_nodes())
    wf["12"] = {"class_type": "UNETLoader",
                "inputs": {"unet_name": _fill_model_name(), "weight_dtype": "fp8_e4m3fn"}}
    wf["14"] = {"class_type": "DifferentialDiffusion",
                "inputs": {"model": ["12", 0]}}
    wf["1"]  = {"class_type": "LoadImage",
                "inputs": {"image": image_name, "upload": "image"}}
    wf["50"] = {"class_type": "LoadImage",
                "inputs": {"image": mask_name, "upload": "image"}}
    wf["51"] = {"class_type": "ImageToMask",
                "inputs": {"image": ["50", 0], "channel": "red"}}
    wf["6"]  = {"class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["11", 0]}}
    wf["15"] = {"class_type": "FluxGuidance",
                "inputs": {"guidance": guidance, "conditioning": ["6", 0]}}
    wf["33"] = {"class_type": "CLIPTextEncode",
                "inputs": {"text": "", "clip": ["11", 0]}}
    # Official FLUX Fill workflow: FluxGuidance + InpaintModelConditioning + DifferentialDiffusion.
    wf["52"] = {"class_type": "InpaintModelConditioning",
                "inputs": {"noise_mask": False,
                           "positive": ["15", 0], "negative": ["33", 0],
                           "vae": ["10", 0], "pixels": ["1", 0], "mask": ["51", 0]}}
    wf["13"] = {
        "class_type": "KSampler",
        "inputs": {
            "cfg": cfg, "denoise": denoise,
            "latent_image": ["52", 2], "model": ["14", 0],
            "negative": ["52", 1], "positive": ["52", 0],
            "sampler_name": sampler, "scheduler": scheduler,
            "seed": seed, "steps": steps,
        },
    }
    wf["8"] = {"class_type": "VAEDecode",
               "inputs": {"samples": ["13", 0], "vae": ["10", 0]}}
    wf["9"] = {"class_type": "SaveImage",
               "inputs": {"images": ["8", 0], "filename_prefix": "flux_inpaint"}}
    return wf


def build_img2img_workflow(image_name, prompt, steps, seed, denoise=0.75,
                            sampler="euler", scheduler="simple", cfg=1.0):
    wf = {}
    wf.update(_build_model_nodes())

    wf["1"] = {"class_type": "LoadImage",
               "inputs": {"image": image_name, "upload": "image"}}
    wf["2"] = {"class_type": "VAEEncode",
               "inputs": {"pixels": ["1", 0], "vae": ["10", 0]}}
    wf["6"] = {"class_type": "CLIPTextEncode",
               "inputs": {"text": prompt, "clip": ["11", 0]}}
    wf["33"] = {"class_type": "CLIPTextEncode",
                "inputs": {"text": "", "clip": ["11", 0]}}
    wf["13"] = {
        "class_type": "KSampler",
        "inputs": {
            "cfg": cfg, "denoise": denoise,
            "latent_image": ["2", 0], "model": ["12", 0],
            "negative": ["33", 0], "positive": ["6", 0],
            "sampler_name": sampler, "scheduler": scheduler,
            "seed": seed, "steps": steps,
        },
    }
    wf["8"] = {"class_type": "VAEDecode",
               "inputs": {"samples": ["13", 0], "vae": ["10", 0]}}
    wf["9"] = {"class_type": "SaveImage",
               "inputs": {"images": ["8", 0], "filename_prefix": "flux_vary"}}
    return wf


def build_cn_upscaler_workflow(image_name, scale_by=2.0, denoise=0.35, steps=28,
                               seed=0, guidance=3.5, cn_strength=0.6,
                               orig_w=1024, orig_h=1024):
    """Flux.1-dev-Controlnet-Upscaler (jasperai) — BasicGuider + SamplerCustomAdvanced."""
    target_w = round(orig_w * scale_by)
    target_h = round(orig_h * scale_by)
    wf = {}
    wf["10"] = {"class_type": "VAELoader",       "inputs": {"vae_name": MODEL_CONFIG["vae"]}}
    wf["11"] = {"class_type": "DualCLIPLoader",  "inputs": {"clip_name1": MODEL_CONFIG["clip_l"],
                                                              "clip_name2": MODEL_CONFIG["t5"], "type": "flux"}}
    wf["12"] = {"class_type": "UNETLoader",      "inputs": {"unet_name": MODEL_CONFIG["unet"],
                                                              "weight_dtype": "fp8_e4m3fn"}}
    wf["1"]  = {"class_type": "LoadImage",       "inputs": {"image": image_name, "upload": "image"}}
    # Pre-upscale with lanczos to target resolution
    wf["2"]  = {"class_type": "ImageScaleBy",    "inputs": {"image": ["1", 0],
                                                              "upscale_method": "lanczos",
                                                              "scale_by": float(scale_by)}}
    # Encode upscaled image to latent (low-denoise starting point)
    wf["3"]  = {"class_type": "VAEEncode",       "inputs": {"pixels": ["2", 0], "vae": ["10", 0]}}
    # Empty text conditioning (upscaler is guidance-free)
    wf["6"]  = {"class_type": "CLIPTextEncode",  "inputs": {"text": "", "clip": ["11", 0]}}
    wf["33"] = {"class_type": "CLIPTextEncode",  "inputs": {"text": "", "clip": ["11", 0]}}
    # ControlNet upscaler
    wf["40"] = {"class_type": "ControlNetLoader","inputs": {"control_net_name": CN_UPSCALER_MODEL}}
    wf["41"] = {"class_type": "ControlNetApplyAdvanced", "inputs": {
        "positive":      ["6", 0],
        "negative":      ["33", 0],
        "control_net":   ["40", 0],
        "vae":           ["10", 0],
        "image":         ["2", 0],
        "strength":      float(cn_strength),
        "start_percent": 0.0,
        "end_percent":   1.0,
    }}
    wf["42"] = {"class_type": "FluxGuidance",    "inputs": {"conditioning": ["41", 0],
                                                              "guidance": float(guidance)}}
    # Patch model with FLUX sampling sigmas for target resolution
    wf["43"] = {"class_type": "ModelSamplingFlux","inputs": {"model": ["12", 0],
                                                               "max_shift": 1.15, "base_shift": 0.5,
                                                               "width": target_w, "height": target_h}}
    wf["44"] = {"class_type": "BasicGuider",     "inputs": {"model": ["43", 0], "conditioning": ["42", 0]}}
    wf["45"] = {"class_type": "RandomNoise",     "inputs": {"noise_seed": seed}}
    wf["46"] = {"class_type": "KSamplerSelect",  "inputs": {"sampler_name": "euler"}}
    wf["47"] = {"class_type": "BasicScheduler",  "inputs": {"model": ["43", 0], "scheduler": "simple",
                                                              "steps": steps, "denoise": float(denoise)}}
    wf["48"] = {"class_type": "SamplerCustomAdvanced", "inputs": {
        "noise":        ["45", 0],
        "guider":       ["44", 0],
        "sampler":      ["46", 0],
        "sigmas":       ["47", 0],
        "latent_image": ["3", 0],
    }}
    wf["8"]  = {"class_type": "VAEDecode",       "inputs": {"samples": ["48", 0], "vae": ["10", 0]}}
    wf["9"]  = {"class_type": "SaveImage",       "inputs": {"images": ["8", 0],
                                                              "filename_prefix": "flux_upscale"}}
    return wf


def _copy_output_video_to_input(filename, subfolder=""):
    src = _safe_output_path(filename, subfolder)
    if not os.path.isfile(src):
        raise FileNotFoundError(f"video not found: {filename}")
    input_dir = os.path.join(os.path.dirname(COMFY_OUTPUT_DIR), "input")
    os.makedirs(input_dir, exist_ok=True)
    base, ext = os.path.splitext(os.path.basename(filename))
    dst_name = f"fluxui_video_upscale_{int(time.time())}_{uuid.uuid4().hex[:8]}{ext or '.mp4'}"
    shutil.copy2(src, os.path.join(input_dir, dst_name))
    return dst_name


def build_seedvr2_video_upscale_workflow(video_name, resolution=1080, batch_size=1, seed=0,
                                         model="seedvr2_ema_7b_sharp_fp8_e4m3fn_mixed_block35_fp16.safetensors",
                                         vae="ema_vae_fp16.safetensors"):
    resolution = max(256, min(2160, int(resolution)))
    batch_size = max(1, min(8, int(batch_size)))
    return {
        "1": {"class_type": "LoadVideo",
              "inputs": {"file": video_name, "upload": "image"}},
        "2": {"class_type": "GetVideoComponents",
              "inputs": {"video": ["1", 0]}},
        "3": {"class_type": "SeedVR2TorchCompileSettings",
              "inputs": {"backend": "inductor", "mode": "default", "fullgraph": False,
                         "dynamic": False, "dynamo_cache_size_limit": 64,
                         "dynamo_recompile_limit": 128}},
        "4": {"class_type": "SeedVR2LoadDiTModel",
              "inputs": {"torch_compile_args": ["3", 0], "model": model, "device": "cuda:0",
                         "blocks_to_swap": 36, "swap_io_components": True,
                         "offload_device": "cpu", "cache_model": False,
                         "attention_mode": "sdpa"}},
        "5": {"class_type": "SeedVR2LoadVAEModel",
              "inputs": {"torch_compile_args": ["3", 0], "model": vae, "device": "cuda:0",
                         "encode_tiled": False, "encode_tile_size": 1024,
                         "encode_tile_overlap": 128, "decode_tiled": False,
                         "decode_tile_size": 1024, "decode_tile_overlap": 128,
                         "tile_debug": "false", "offload_device": "none",
                         "cache_model": False}},
        "6": {"class_type": "SeedVR2VideoUpscaler",
              "inputs": {"image": ["2", 0], "dit": ["4", 0], "vae": ["5", 0],
                         "seed": int(seed), "resolution": resolution, "max_resolution": 0,
                         "batch_size": batch_size, "uniform_batch_size": False,
                         "color_correction": "lab", "temporal_overlap": 0,
                         "prepend_frames": 0, "input_noise_scale": 0,
                         "latent_noise_scale": 0, "offload_device": "cpu",
                         "enable_debug": False}},
        "7": {"class_type": "CreateVideo",
              "inputs": {"images": ["6", 0], "audio": ["2", 1], "fps": ["2", 2]}},
        "8": {"class_type": "SaveVideo",
              "inputs": {"video": ["7", 0], "filename_prefix": "video/seedvr2_upscale",
                         "format": "mp4", "codec": "h264"}},
    }


def build_redux_workflow(image_name, prompt="", steps=20, seed=0,
                          sampler="euler", scheduler="simple", cfg=1.0,
                          width=1024, height=1024, guidance=3.5,
                          redux_strength=1.0, batch_size=1):
    """FLUX.1 Redux — image-to-image style variation (BFL official)."""
    wf = {}
    wf.update(_build_model_nodes())
    wf["1"]  = {"class_type": "LoadImage",       "inputs": {"image": image_name, "upload": "image"}}
    wf["21"] = {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": REDUX_CLIP_MODEL}}
    wf["22"] = {"class_type": "CLIPVisionEncode",
                "inputs": {"clip_vision": ["21", 0], "image": ["1", 0], "crop": "center"}}
    wf["20"] = {"class_type": "StyleModelLoader", "inputs": {"style_model_name": REDUX_MODEL}}
    wf["6"]  = {"class_type": "CLIPTextEncode",   "inputs": {"text": prompt or "", "clip": ["11", 0]}}
    wf["33"] = {"class_type": "CLIPTextEncode",   "inputs": {"text": "", "clip": ["11", 0]}}
    wf["23"] = {"class_type": "StyleModelApply",
                "inputs": {"conditioning": ["6", 0], "style_model": ["20", 0],
                           "clip_vision_output": ["22", 0],
                           "strength": float(redux_strength), "strength_type": "multiply"}}
    wf["24"] = {"class_type": "FluxGuidance",
                "inputs": {"conditioning": ["23", 0], "guidance": float(guidance)}}
    wf["27"] = {"class_type": "EmptyLatentImage", "inputs": {"batch_size": int(batch_size), "height": height, "width": width}}
    wf["13"] = {"class_type": "KSampler",
                "inputs": {"cfg": 1.0, "denoise": 1.0, "latent_image": ["27", 0],
                           "model": ["12", 0], "negative": ["33", 0], "positive": ["24", 0],
                           "sampler_name": sampler, "scheduler": scheduler,
                           "seed": seed, "steps": steps}}
    wf["8"]  = {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["10", 0]}}
    wf["9"]  = {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "flux_redux"}}
    return wf


def build_kontext_workflow(image_name, instruction, steps=28, seed=0,
                           guidance=2.5, sampler="euler", scheduler="simple",
                           model_name=None, batch_size=1):
    """FLUX.1 Kontext [dev] local workflow based on the official ComfyUI template."""
    wf = {}
    wf["10"] = {"class_type": "VAELoader",   "inputs": {"vae_name": MODEL_CONFIG["vae"]}}
    wf["11"] = {"class_type": "DualCLIPLoader",
                "inputs": {"clip_name1": MODEL_CONFIG["clip_l"],
                           "clip_name2": _t5_model_name(), "type": "flux",
                           "device": "default"}}
    wf["12"] = {"class_type": "UNETLoader",
                "inputs": {"unet_name": _kontext_model_name(model_name), "weight_dtype": "default"}}
    wf["1"] = {"class_type": "LoadImage",
               "inputs": {"image": image_name, "upload": "image"}}
    wf["2"] = {"class_type": "FluxKontextImageScale",
               "inputs": {"image": ["1", 0]}}
    wf["3"] = {"class_type": "VAEEncode",
               "inputs": {"pixels": ["2", 0], "vae": ["10", 0]}}
    latent_ref = ["3", 0]
    if int(batch_size) > 1:
        wf["36"] = {"class_type": "RepeatLatentBatch",
                    "inputs": {"samples": ["3", 0], "amount": int(batch_size)}}
        latent_ref = ["36", 0]
    wf["6"] = {"class_type": "CLIPTextEncode",
               "inputs": {"text": instruction, "clip": ["11", 0]}}
    wf["7"] = {"class_type": "ReferenceLatent",
               "inputs": {"conditioning": ["6", 0], "latent": latent_ref}}
    wf["8"] = {"class_type": "FluxGuidance",
               "inputs": {"conditioning": ["7", 0], "guidance": guidance}}
    wf["33"] = {"class_type": "ConditioningZeroOut",
                "inputs": {"conditioning": ["6", 0]}}
    wf["13"] = {"class_type": "KSampler",
                "inputs": {"model": ["12", 0],
                           "positive": ["8", 0], "negative": ["33", 0],
                           "latent_image": latent_ref,
                           "seed": seed, "steps": steps, "cfg": 1.0,
                           "sampler_name": sampler, "scheduler": scheduler,
                           "denoise": 1.0}}
    wf["14"] = {"class_type": "VAEDecode",
                "inputs": {"samples": ["13", 0], "vae": ["10", 0]}}
    wf["9"] = {"class_type": "SaveImage",
               "inputs": {"images": ["14", 0], "filename_prefix": "flux_kontext"}}
    return wf




def build_img2img_full_workflow(image_name, prompt, negative, steps, seed,
                                 denoise=0.75, sampler="euler", scheduler="simple",
                                 cfg=1.0, loras=None):
    """Full img2img with LoRA support."""
    wf = {}
    wf.update(_build_model_nodes())
    model_ref, clip_ref = _chain_loras(wf, loras or [])
    wf["1"] = {"class_type": "LoadImage",
               "inputs": {"image": image_name, "upload": "image"}}
    wf["2"] = {"class_type": "VAEEncode",
               "inputs": {"pixels": ["1", 0], "vae": ["10", 0]}}
    wf["6"] = {"class_type": "CLIPTextEncode",
               "inputs": {"text": prompt, "clip": clip_ref}}
    wf["33"] = {"class_type": "CLIPTextEncode",
                "inputs": {"text": negative or "", "clip": clip_ref}}
    wf["13"] = {"class_type": "KSampler",
                "inputs": {"cfg": cfg, "denoise": denoise,
                           "latent_image": ["2", 0], "model": model_ref,
                           "negative": ["33", 0], "positive": ["6", 0],
                           "sampler_name": sampler, "scheduler": scheduler,
                           "seed": seed, "steps": steps}}
    wf["8"] = {"class_type": "VAEDecode",
               "inputs": {"samples": ["13", 0], "vae": ["10", 0]}}
    wf["9"] = {"class_type": "SaveImage",
               "inputs": {"images": ["8", 0], "filename_prefix": "flux_i2i"}}
    return wf


def _fetch_and_upload_image(filename, subfolder, img_type):
    params = {"filename": filename, "subfolder": subfolder, "type": img_type}
    r = requests.get(f"{COMFY_URL}/view", params=params, timeout=60)
    r.raise_for_status()

    ext = filename.rsplit(".", 1)[-1] if "." in filename else "png"
    mime = f"image/{ext}"
    files = {"image": (filename, r.content, mime),
             "overwrite": (None, "true")}
    up = requests.post(f"{COMFY_URL}/upload/image", files=files, timeout=30)
    up.raise_for_status()
    return up.json().get("name", filename)


_RUN_LOG_PATH = os.path.join(os.path.dirname(__file__), "workflow-run.jsonl")
_LEGACY_RUN_LOG_PATH = os.path.join(os.path.dirname(__file__), "run.log")
_RUN_LOG_MAX  = 50


def _infer_mode(wf):
    types = {n.get("class_type", "") for n in wf.values()}
    model_names = []
    for node in wf.values():
        inp = node.get("inputs", {})
        for key in ("unet_name", "lora_name", "control_net_name"):
            if inp.get(key):
                model_names.append(str(inp[key]).lower())
    if "Flux2Scheduler" in types or "EmptyFlux2LatentImage" in types or any("flux2" in name or "flux.2" in name for name in model_names):
        return "flux2"
    if any("canny" in name for name in model_names):
        return "canny"
    if any("depth" in name for name in model_names):
        return "depth"
    if "WanImageToVideo" in types or "WanFirstLastFrameToVideo" in types: return "wan22"
    if "FluxKontextImageScale" in types:         return "kontext"
    if "StyleModelLoader" in types:              return "redux"
    if "InpaintModelConditioning" in types:
        return "outpaint" if "ImagePadForOutpaint" in types else "inpaint"
    if "FaceDetailer" in types:                  return "face"
    if "ControlNetLoader" in types:
        return "upscale" if "ImageScaleBy" in types else "controlnet"
    if "VAEEncode" in types and "LoadImage" in types: return "img2img"
    return "txt2img"


def _extract_models(wf):
    models = []
    class_keys = {
        "UNETLoader":      "unet_name",
        "VAELoader":       "vae_name",
        "ControlNetLoader":"control_net_name",
        "StyleModelLoader":"style_model_name",
        "CLIPVisionLoader":"clip_name",
        "CLIPLoader":      "clip_name",
        "LoraLoader":      "lora_name",
        "LoraLoaderModelOnly": "lora_name",
    }
    for node in wf.values():
        ct = node.get("class_type", "")
        key = class_keys.get(ct)
        if key:
            val = node.get("inputs", {}).get(key)
            if val:
                models.append(val)
        if ct == "DualCLIPLoader":
            inp = node.get("inputs", {})
            for k in ("clip_name1", "clip_name2"):
                v = inp.get(k)
                if v:
                    models.append(v)
        if ct == "AIO_Preprocessor":
            p = node.get("inputs", {}).get("preprocessor")
            if p:
                models.append(f"preprocessor:{p}")
    return models


def _write_run_log(entry):
    try:
        lines = []
        if os.path.exists(_RUN_LOG_PATH):
            with open(_RUN_LOG_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()
        lines.append(json.dumps(entry, ensure_ascii=False) + "\n")
        lines = lines[-_RUN_LOG_MAX:]
        with open(_RUN_LOG_PATH, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception:
        pass


def _rewrite_run_log(rows):
    try:
        rows = rows[-_RUN_LOG_MAX:]
        with open(_RUN_LOG_PATH, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _read_run_log():
    rows = []
    try:
        paths = [_RUN_LOG_PATH]
        if not os.path.exists(_RUN_LOG_PATH) and os.path.exists(_LEGACY_RUN_LOG_PATH):
            paths.append(_LEGACY_RUN_LOG_PATH)
        for path in paths:
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f.readlines()[-_RUN_LOG_MAX * 3:]:
                    line = line.strip()
                    if not line or not line.startswith("{"):
                        continue
                    try:
                        row = json.loads(line)
                        if row.get("pid") or row.get("mode"):
                            rows.append(row)
                    except Exception:
                        continue
    except Exception as e:
        rows = [{"error": str(e)}]
    return rows[-_RUN_LOG_MAX:]


def _sync_run_log_with_jobs(jobs):
    rows = _read_run_log()
    if not rows:
        return rows
    by_pid = {j.get("prompt_id"): j for j in jobs if j.get("prompt_id")}
    changed = False
    for row in rows:
        if not isinstance(row, dict) or row.get("raw"):
            continue
        row_changed = False
        pid = row.get("pid")
        job = by_pid.get(pid)
        if not job:
            continue
        for key in ("status", "error", "node_type", "num_images", "num_videos"):
            if row.get(key) != job.get(key):
                row[key] = job.get(key)
                row_changed = True
        if row_changed:
            row["updated_ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            start_epoch = row.get("start_epoch")
            if start_epoch and job.get("status") in ("success", "error"):
                row["duration_sec"] = round(time.time() - float(start_epoch), 1)
            changed = True
    if changed:
        _rewrite_run_log(rows)
    return rows


def _is_video_output(item):
    name = (item or {}).get("filename", "")
    return bool(re.search(r"\.(mp4|webm|mov|mkv|avi|gif)$", name, re.I))


def _queue_workflow(workflow, metadata=None):
    client_id = str(uuid.uuid4())
    r = requests.post(
        f"{COMFY_URL}/prompt",
        json={"prompt": workflow, "client_id": client_id},
        timeout=10,
    )
    if not r.ok:
        try:
            err = r.json()
            raise Exception(f"ComfyUI error: {_format_comfy_error(err)}")
        except (ValueError, AttributeError):
            raise Exception(f"ComfyUI {r.status_code}: {r.text[:300]}")
    prompt_id = r.json().get("prompt_id")
    entry = {
        "ts":       time.strftime("%Y-%m-%dT%H:%M:%S"),
        "start_epoch": time.time(),
        "mode":     _infer_mode(workflow),
        "models":   _extract_models(workflow),
        "pid":      prompt_id,
        "status":   "queued",
    }
    if metadata:
        entry.update(metadata)
    _write_run_log(entry)
    return prompt_id, client_id


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/loading")
def loading_page():
    return send_from_directory("static", "loading.html")


@app.route("/api/ping")
def ping():
    return jsonify({"ok": True})


@app.route("/api/health")
def health():
    try:
        r = requests.get(f"{COMFY_URL}/system_stats", timeout=3)
        info = r.json()
        return jsonify({"comfy": "online",
                        "version": info.get("system", {}).get("comfyui_version", "")})
    except Exception:
        return jsonify({"comfy": "offline"}), 503


@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.json or {}
    prompt = data.get("prompt", "").strip()
    negative = data.get("negative", "").strip()
    if not prompt:
        return jsonify({"error": "プロンプトを入力してください"}), 400

    if _is_japanese(prompt):
        prompt = _translate(prompt)
    if negative and _is_japanese(negative):
        negative = _translate(negative)

    width      = max(64, min(2048, int(data.get("width", 1024))))
    height     = max(64, min(2048, int(data.get("height", 1024))))
    steps      = max(1,  min(100,  int(data.get("steps", 20))))
    batch_size = max(1,  min(4,    int(data.get("batch_size", 1))))
    cfg        = float(data.get("cfg", 1.0))
    sampler    = data.get("sampler", "euler")
    scheduler  = data.get("scheduler", "simple")
    loras      = data.get("loras") or []
    model_name = data.get("model") or data.get("unet")
    refs       = (data.get("refs") or [])[:10]

    seed = data.get("seed")
    if seed is None or seed == -1:
        seed = random.randint(0, 2**31 - 1)
    seed = int(seed)

    if _is_flux2_model(model_name):
        workflow = build_flux2_workflow(
            prompt, width, height, steps, seed, batch_size,
            model_name=model_name, refs=refs, sampler=sampler
        )
    else:
        workflow = build_txt2img_workflow(
            prompt, negative, width, height, steps, seed, batch_size,
            sampler, scheduler, cfg, loras, model_name
        )

    try:
        prompt_id, client_id = _queue_workflow(workflow)
        _gallery_pending[prompt_id] = {
            "prompt": prompt, "seed": seed,
            "width": width, "height": height,
            "steps": steps, "sampler": sampler, "scheduler": scheduler, "cfg": cfg,
            "tags": [], "is_video": False,
        }
        return jsonify({"prompt_id": prompt_id, "client_id": client_id, "seed": seed})
    except requests.ConnectionError:
        return jsonify({"error": "ComfyUIに接続できません"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/flux2/generate", methods=["POST"])
def flux2_generate():
    data = request.json or {}
    prompt = data.get("prompt", "").strip()

    missing = _flux2_missing_requirements()
    if missing:
        return jsonify({"error": "Flux2 required files missing: " + ", ".join(missing)}), 400

    if _is_japanese(prompt):
        prompt = _translate(prompt)

    width      = max(64, min(2048, int(data.get("width", 512))))
    height     = max(64, min(2048, int(data.get("height", 512))))
    steps      = max(1, min(100, int(data.get("steps", 20))))
    # Keep Flux2 isolated and predictable: UI repeats single-image jobs for batch.
    batch_size = 1
    sampler    = data.get("sampler", "euler")
    model_name = data.get("model") or FLUX2_CONFIG["unet"]
    refs       = (data.get("refs") or [])[:10]
    guidance   = float(data.get("guidance", 4.0))

    seed = data.get("seed")
    if seed is None or seed == -1:
        seed = random.randint(0, 2**31 - 1)
    seed = int(seed)

    info = _flux2_model_info(model_name)
    try:
        workflow = build_flux2_workflow(
            prompt, width, height, steps, seed, batch_size,
            model_name=info["model"], refs=refs, guidance=guidance, sampler=sampler
        )
        prompt_id, client_id = _queue_workflow(workflow, {
            "mode": "flux2",
            "workflow": info["workflow"],
            "flux2_model": info["model"],
            "flux2_text_encoder": info["text_encoder"],
            "flux2_vae": info["vae"],
            "ref_count": len(refs),
        })
        _gallery_pending[prompt_id] = {
            "prompt": prompt, "seed": seed,
            "width": width, "height": height,
            "steps": steps, "sampler": sampler, "cfg": 4.0,
            "tags": ["flux2"], "is_video": False,
        }
        return jsonify({
            "prompt_id": prompt_id,
            "client_id": client_id,
            "seed": seed,
            "workflow": info["workflow"],
            "model": info["model"],
            "text_encoder": info["text_encoder"],
            "vae": info["vae"],
            "ref_count": len(refs),
        })
    except requests.ConnectionError:
        return jsonify({"error": "ComfyUIに接続できません"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/wan22/generate", methods=["POST"])
def wan22_generate():
    data = request.json or {}
    prompt     = data.get("prompt", "").strip()
    steps      = max(1, min(50, int(data.get("steps", 8))))
    width      = max(64, min(1920, int(data.get("width", 832))))
    height     = max(64, min(1920, int(data.get("height", 480))))
    length     = max(5, min(200, int(data.get("length", 81))))
    fps        = max(1, min(60, int(data.get("frame_rate", data.get("fps", 16)))))
    start_filename  = data.get("start_filename", "")
    start_subfolder = data.get("start_subfolder", "")
    start_type      = data.get("start_type", "input")
    end_filename    = data.get("end_filename", "")
    end_subfolder   = data.get("end_subfolder", "")
    end_type        = data.get("end_type", "input")

    seed = data.get("seed")
    if seed is None or seed == -1:
        seed = random.randint(0, 2**31 - 1)
    seed = int(seed)

    if not start_filename:
        return jsonify({"error": "開始フレーム画像が必要です"}), 400

    if prompt and _is_japanese(prompt):
        prompt = _translate(prompt)

    try:
        start_name = _fetch_and_upload_image(start_filename, start_subfolder, start_type)
        end_name = None
        if end_filename:
            end_name = _fetch_and_upload_image(end_filename, end_subfolder, end_type)
        workflow = build_wan22_workflow(
            prompt, start_name, end_name,
            steps=steps, seed=seed,
            width=width, height=height, length=length, fps=fps
        )
        prompt_id, client_id = _queue_workflow(workflow, {"mode": "wan22"})
        _gallery_pending[prompt_id] = {
            "prompt": prompt, "seed": seed,
            "width": width, "height": height,
            "steps": steps, "sampler": "euler", "cfg": 1.0,
            "tags": ["wan2.2", "i2v"], "is_video": True,
        }
        return jsonify({
            "prompt_id": prompt_id,
            "client_id": client_id,
            "seed": seed,
        })
    except requests.ConnectionError:
        return jsonify({"error": "ComfyUIに接続できません"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/inpaint", methods=["POST"])
def inpaint():
    data = request.json or {}
    filename  = data.get("filename", "")
    subfolder = data.get("subfolder", "")
    img_type  = data.get("type", "output")
    mask_data = data.get("mask_data", "")
    prompt    = data.get("prompt", "").strip()
    denoise   = float(data.get("denoise", 1.0))
    steps     = max(1, min(100, int(data.get("steps", 20))))
    cfg       = float(data.get("cfg", 2.0))
    seed      = random.randint(0, 2**31 - 1)

    if not filename or not mask_data:
        return jsonify({"error": "image and mask required"}), 400

    if prompt and _is_japanese(prompt):
        prompt = _translate(prompt)

    try:
        img_name = _fetch_and_upload_image(filename, subfolder, img_type)
        # decode mask base64 and upload
        import base64, re as _re
        mask_b64 = _re.sub(r'^data:image/\w+;base64,', '', mask_data)
        mask_bytes = base64.b64decode(mask_b64)
        files = {"image": (f"mask_{seed}.png", mask_bytes, "image/png"),
                 "overwrite": (None, "true")}
        up = requests.post(f"{COMFY_URL}/upload/image", files=files, timeout=30)
        up.raise_for_status()
        mask_name = up.json().get("name", f"mask_{seed}.png")

        workflow = build_inpaint_workflow(img_name, mask_name, prompt, steps, seed, denoise, cfg=cfg)
        prompt_id, client_id = _queue_workflow(workflow)
        _gallery_pending[prompt_id] = {
            "prompt": prompt, "seed": seed, "steps": steps, "cfg": cfg,
            "tags": ["inpaint"], "is_video": False,
        }
        return jsonify({"prompt_id": prompt_id, "client_id": client_id, "seed": seed})
    except requests.ConnectionError:
        return jsonify({"error": "ComfyUIに接続できません"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/queue")
def queue_list():
    try:
        q = requests.get(f"{COMFY_URL}/queue", timeout=5).json()
        running = [{"prompt_id": item[1]} for item in q.get("queue_running", [])]
        pending = [{"prompt_id": item[1]} for item in q.get("queue_pending", [])]
        return jsonify({"running": running, "pending": pending})
    except Exception as e:
        return jsonify({"running": [], "pending": [], "error": str(e)})


@app.route("/api/cancel/<prompt_id>", methods=["POST"])
def cancel(prompt_id):
    try:
        requests.post(f"{COMFY_URL}/queue",
                      json={"delete": [prompt_id]}, timeout=5)
        requests.post(f"{COMFY_URL}/interrupt", timeout=5)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cancel_all", methods=["POST"])
def cancel_all():
    try:
        requests.post(f"{COMFY_URL}/queue", json={"clear": True}, timeout=5)
        requests.post(f"{COMFY_URL}/interrupt", timeout=5)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/lora_preview/<path:lora_name>")
def lora_preview(lora_name):
    """Return preview image for a LoRA if a .preview.png/.jpg sibling exists."""
    import os
    lora_dir = r"C:\AI\ComfyUI\models\loras"
    base = os.path.splitext(lora_name)[0]
    for ext in (".preview.png", ".preview.jpg", ".png", ".jpg"):
        p = os.path.join(lora_dir, base + ext)
        if os.path.exists(p):
            return send_from_directory(lora_dir, base + ext)
    return jsonify({"error": "no preview"}), 404


@app.route("/api/vary", methods=["POST"])
def vary():
    data = request.json or {}
    filename  = data.get("filename", "")
    subfolder = data.get("subfolder", "")
    img_type  = data.get("type", "output")
    prompt    = data.get("prompt", "").strip()
    denoise   = float(data.get("denoise", 0.75))
    steps     = max(1, min(100, int(data.get("steps", 20))))
    sampler   = data.get("sampler", "euler")
    scheduler = data.get("scheduler", "simple")
    cfg       = float(data.get("cfg", 2.0))
    seed      = random.randint(0, 2**31 - 1)

    if not filename:
        return jsonify({"error": "filename is required"}), 400

    if prompt and _is_japanese(prompt):
        prompt = _translate(prompt)

    try:
        uploaded_name = _fetch_and_upload_image(filename, subfolder, img_type)
        workflow = build_img2img_workflow(
            uploaded_name, prompt, steps, seed, denoise, sampler, scheduler, cfg
        )
        prompt_id, _ = _queue_workflow(workflow)
        _gallery_pending[prompt_id] = {
            "prompt": prompt, "seed": seed,
            "steps": steps, "sampler": sampler, "scheduler": scheduler, "cfg": cfg,
            "tags": ["vary"], "is_video": False,
        }
        return jsonify({"prompt_id": prompt_id, "seed": seed})
    except requests.ConnectionError:
        return jsonify({"error": "ComfyUIに接続できません"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/upscale", methods=["POST"])
def upscale():
    data      = request.json or {}
    filename  = data.get("filename", "")
    subfolder = data.get("subfolder", "")
    img_type  = data.get("type", "output")
    scale_by  = float(data.get("scale_by", 2.0))
    denoise   = max(0.05, min(1.0, float(data.get("denoise", 0.35))))
    steps     = max(1, min(50, int(data.get("steps", 28))))
    guidance  = float(data.get("guidance", 3.5))
    redux_strength = max(0.0, min(2.0, float(data.get("redux_strength", 1.0))))
    cn_str    = float(data.get("cn_strength", 0.6))
    orig_w    = max(64, int(data.get("orig_w", 1024)))
    orig_h    = max(64, int(data.get("orig_h", 1024)))
    seed      = random.randint(0, 2**31 - 1)

    if not filename:
        return jsonify({"error": "filename is required"}), 400

    cn_path = os.path.join(CN_UPSCALER_DIR, CN_UPSCALER_MODEL)
    if not os.path.exists(cn_path):
        return jsonify({"error": f"CN Upscalerモデルが見つかりません: {CN_UPSCALER_MODEL}\nComfyUI/models/controlnet/ に配置してください"}), 400

    try:
        uploaded_name = _fetch_and_upload_image(filename, subfolder, img_type)
        workflow = build_cn_upscaler_workflow(
            uploaded_name, scale_by, denoise, steps, seed, guidance, cn_str, orig_w, orig_h
        )
        prompt_id, _ = _queue_workflow(workflow)
        _gallery_pending[prompt_id] = {
            "seed": seed, "tags": ["upscale"], "is_video": False,
        }
        return jsonify({"prompt_id": prompt_id, "seed": seed})
    except requests.ConnectionError:
        return jsonify({"error": "ComfyUIに接続できません"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/video_upscale", methods=["POST"])
def video_upscale():
    data = request.json or {}
    filename = data.get("filename", "")
    subfolder = data.get("subfolder", "") or ""
    img_type = data.get("type", "output") or "output"
    scale_by = max(1.0, min(4.0, float(data.get("scale_by", 2.0))))
    orig_w = max(1, int(data.get("orig_w", data.get("width", 0)) or 0))
    orig_h = max(1, int(data.get("orig_h", data.get("height", 0)) or 0))
    batch_size = max(1, min(8, int(data.get("batch_size", 1))))
    seed = random.randint(0, 2**31 - 1)
    if not filename:
        return jsonify({"error": "filename is required"}), 400
    if img_type != "output":
        return jsonify({"error": "output動画だけ対応しています"}), 400
    try:
        info = requests.get(f"{COMFY_URL}/object_info", timeout=8).json()
        missing = [n for n in ("LoadVideo", "GetVideoComponents", "SeedVR2VideoUpscaler",
                               "SeedVR2LoadDiTModel", "SeedVR2LoadVAEModel",
                               "SeedVR2TorchCompileSettings", "CreateVideo", "SaveVideo")
                   if n not in info]
        if missing:
            return jsonify({"error": "SeedVR2/Videoノードが未ロードです。ComfyUIを再起動してください: " + ", ".join(missing)}), 400
    except requests.ConnectionError:
        return jsonify({"error": "ComfyUIに接続できません"}), 503
    except Exception:
        pass
    try:
        input_video = _copy_output_video_to_input(filename, subfolder)
        base = max(orig_w, orig_h, 540)
        resolution = min(2160, max(720, int(round(base * scale_by))))
        workflow = build_seedvr2_video_upscale_workflow(
            input_video, resolution=resolution, batch_size=batch_size, seed=seed
        )
        prompt_id, client_id = _queue_workflow(workflow, {"mode": "video_upscale", "model": "SeedVR2"})
        _gallery_pending[prompt_id] = {
            "prompt": "[SeedVR2 Video Upscale] " + filename,
            "seed": seed,
            "width": orig_w,
            "height": orig_h,
            "steps": 0,
            "sampler": "SeedVR2",
            "scheduler": "video",
            "cfg": 0,
            "tags": ["video", "seedvr2", "upscale"],
            "is_video": True,
        }
        return jsonify({"prompt_id": prompt_id, "client_id": client_id, "seed": seed,
                        "resolution": resolution, "input_video": input_video})
    except requests.ConnectionError:
        return jsonify({"error": "ComfyUIに接続できません"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/redux", methods=["POST"])
def redux():
    """FLUX.1 Redux image variation (BFL official)."""
    data      = request.json or {}
    filename  = data.get("filename", "")
    subfolder = data.get("subfolder", "")
    img_type  = data.get("type", "input")
    prompt    = data.get("prompt", "").strip()
    steps     = max(1, min(100, int(data.get("steps", 20))))
    cfg       = float(data.get("cfg", 2.0))
    sampler   = data.get("sampler", "euler")
    scheduler = data.get("scheduler", "simple")
    width     = max(64, min(2048, int(data.get("width", 1024))))
    height    = max(64, min(2048, int(data.get("height", 1024))))
    guidance       = float(data.get("guidance", 3.5))
    redux_strength = max(0.0, min(2.0, float(data.get("redux_strength", 1.0))))
    batch_size     = max(1, min(4, int(data.get("batch_size", 1))))
    seed           = random.randint(0, 2**31 - 1)

    if not filename:
        return jsonify({"error": "filename is required"}), 400

    style_path = os.path.join(REDUX_MODEL_DIR, REDUX_MODEL)
    clip_path  = os.path.join(REDUX_CLIP_DIR, REDUX_CLIP_MODEL)
    if not os.path.exists(style_path):
        return jsonify({"error": f"Redux モデルが見つかりません: {REDUX_MODEL}"}), 400
    if not os.path.exists(clip_path):
        return jsonify({"error": f"CLIP Vision が見つかりません: {REDUX_CLIP_MODEL}"}), 400

    if prompt and _is_japanese(prompt):
        prompt = _translate(prompt)

    try:
        uploaded_name = _fetch_and_upload_image(filename, subfolder, img_type)
        workflow = build_redux_workflow(uploaded_name, prompt, steps, seed, sampler, scheduler, cfg,
                                        width=width, height=height, guidance=guidance,
                                        redux_strength=redux_strength, batch_size=batch_size)
        prompt_id, client_id = _queue_workflow(workflow)
        _gallery_pending[prompt_id] = {
            "prompt": prompt, "seed": seed,
            "width": width, "height": height,
            "steps": steps, "sampler": sampler, "scheduler": scheduler, "cfg": cfg,
            "tags": ["redux"], "is_video": False,
        }
        return jsonify({"prompt_id": prompt_id, "client_id": client_id, "seed": seed})
    except requests.ConnectionError:
        return jsonify({"error": "ComfyUIに接続できません"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/img2img", methods=["POST"])
def img2img():
    """Image-to-image generation endpoint."""
    data = request.json or {}
    filename  = data.get("filename", "")
    subfolder = data.get("subfolder", "")
    img_type  = data.get("type", "output")
    prompt    = data.get("prompt", "").strip()
    negative  = data.get("negative", "").strip()
    denoise   = float(data.get("denoise", 0.75))
    steps     = max(1, min(100, int(data.get("steps", 20))))
    cfg       = float(data.get("cfg", 1.0))
    sampler   = data.get("sampler", "euler")
    scheduler = data.get("scheduler", "simple")
    loras     = data.get("loras") or []

    seed = data.get("seed")
    if seed is None or seed == -1:
        seed = random.randint(0, 2**31 - 1)
    seed = int(seed)

    if not filename:
        return jsonify({"error": "filename is required"}), 400
    if not prompt:
        return jsonify({"error": "プロンプトを入力してください"}), 400

    if _is_japanese(prompt):
        prompt = _translate(prompt)
    if negative and _is_japanese(negative):
        negative = _translate(negative)

    try:
        uploaded_name = _fetch_and_upload_image(filename, subfolder, img_type)
        workflow = build_img2img_full_workflow(
            uploaded_name, prompt, negative, steps, seed, denoise, sampler, scheduler, cfg, loras
        )
        prompt_id, client_id = _queue_workflow(workflow)
        _gallery_pending[prompt_id] = {
            "prompt": prompt, "seed": seed,
            "steps": steps, "sampler": sampler, "scheduler": scheduler, "cfg": cfg,
            "tags": ["img2img"], "is_video": False,
        }
        return jsonify({"prompt_id": prompt_id, "client_id": client_id, "seed": seed})
    except requests.ConnectionError:
        return jsonify({"error": "ComfyUIに接続できません"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/upload_img2img", methods=["POST"])
def upload_img2img():
    """Upload a local file to ComfyUI and return its name for use in img2img."""
    if "image" not in request.files:
        return jsonify({"error": "image file required"}), 400
    f = request.files["image"]
    raw = f.read()
    if not raw:
        return jsonify({"error": "empty image file"}), 400
    try:
        raw, img_w, img_h, was_resized = _shrink_for_flux(raw)
    except Exception as e:
        return jsonify({"error": f"画像を読み込めません: {e}"}), 400
    base = os.path.splitext(os.path.basename(f.filename or "upload"))[0] or "upload"
    upload_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", base) + ".png"
    files = {"image": (upload_name, raw, "image/png"),
             "overwrite": (None, "true")}
    try:
        r = requests.post(f"{COMFY_URL}/upload/image", files=files, timeout=30)
        r.raise_for_status()
        d = r.json()
        return jsonify({"name": d.get("name", f.filename), "subfolder": d.get("subfolder",""),
                        "type": "input", "width": img_w, "height": img_h, "resized": was_resized})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/translate", methods=["POST"])
def translate():
    data = request.json or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    translated = _translate(text)
    return jsonify({"original": text, "translated": translated})


@app.route("/api/enhance", methods=["POST"])
def enhance():
    data = request.json or {}
    prompt = data.get("prompt", "").strip()
    style  = data.get("style", "photo")
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    if _is_japanese(prompt):
        prompt = _translate(prompt)

    suffix = STYLE_SUFFIXES.get(style, "")
    enhanced = prompt + suffix
    return jsonify({"enhanced": enhanced, "style": style})


def build_controlnet_workflow(control_image_name, prompt, width, height, steps, seed,
                               controlnet_name, controlnet_strength=1.0,
                               preprocessor="none",
                               sampler="euler", scheduler="simple", cfg=1.0):
    wf = {}
    wf.update(_build_model_nodes())

    wf["6"]  = {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["11", 0]}}
    wf["33"] = {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["11", 0]}}
    wf["20"] = {"class_type": "LoadImage", "inputs": {"image": control_image_name, "upload": "image"}}

    if preprocessor and preprocessor != "none":
        wf["21"] = {"class_type": "AIO_Preprocessor",
                    "inputs": {"preprocessor": preprocessor, "image": ["20", 0],
                               "resolution": max(width, height)}}
        ctrl_img = ["21", 0]
    else:
        ctrl_img = ["20", 0]

    wf["22"] = {"class_type": "ControlNetLoader", "inputs": {"control_net_name": controlnet_name}}
    wf["23"] = {"class_type": "ControlNetApplyAdvanced", "inputs": {
        "positive": ["6", 0], "negative": ["33", 0],
        "control_net": ["22", 0], "vae": ["10", 0], "image": ctrl_img,
        "strength": controlnet_strength, "start_percent": 0.0, "end_percent": 1.0,
    }}
    wf["27"] = {"class_type": "EmptyLatentImage",
                "inputs": {"batch_size": 1, "height": height, "width": width}}
    wf["13"] = {"class_type": "KSampler", "inputs": {
        "cfg": cfg, "denoise": 1.0,
        "latent_image": ["27", 0], "model": ["12", 0],
        "negative": ["23", 1], "positive": ["23", 0],
        "sampler_name": sampler, "scheduler": scheduler,
        "seed": seed, "steps": steps,
    }}
    wf["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["10", 0]}}
    wf["9"] = {"class_type": "SaveImage",
               "inputs": {"images": ["8", 0], "filename_prefix": "flux_controlnet"}}
    return wf


def _model_file_exists(folder, name):
    return bool(name) and os.path.exists(_local_model_path(folder, name))


def _wan22_model_exists(name):
    """UNET_DIR と DIFFM_DIR の両方を確認（GGUF / safetensors 両対応）。"""
    return (_model_file_exists(UNET_DIR, name) or
            _model_file_exists(DIFFM_DIR, name))


def _resolve_wan22_unet(candidates):
    """候補ファイル名リストから実際に存在するものを返す。"""
    for name in candidates:
        if _wan22_model_exists(name):
            return name
    return candidates[0]


def _local_model_path(folder, name):
    path = os.path.join(folder, name)
    if os.name != "nt":
        m = re.match(r"^([A-Za-z]):\\(.*)$", path)
        if m:
            drive = m.group(1).lower()
            rest = m.group(2).replace("\\", "/")
            return f"/mnt/{drive}/{rest}"
    return path


def _control_kind_from_name(name):
    for kind, model in BFL_CONTROL_LORAS.items():
        if name == model:
            return kind
    for kind, model in BFL_CONTROL_FULL_MODELS.items():
        if name == model:
            return kind
    for kind, model in BFL_CN_MODELS.items():
        if name == model:
            return kind
    return None


def _resolve_bfl_control(kind, requested_name=""):
    if kind not in BFL_CONTROL_LORAS:
        return None

    lora = BFL_CONTROL_LORAS[kind]
    full = BFL_CONTROL_FULL_MODELS[kind]
    fallback = BFL_CN_MODELS[kind]
    if requested_name == lora and not _model_file_exists(LORA_MODEL_DIR, lora):
        raise RuntimeError(f"{lora} が models/loras にありません")
    if requested_name == full and not _model_file_exists(KONTEXT_MODEL_DIR, full):
        raise RuntimeError(f"{full} が models/diffusion_models にありません")

    if _model_file_exists(LORA_MODEL_DIR, lora):
        return {"kind": kind, "mode": "lora", "name": lora}
    if _model_file_exists(KONTEXT_MODEL_DIR, full):
        return {"kind": kind, "mode": "full", "name": full}
    if _model_file_exists(CN_UPSCALER_DIR, fallback):
        return {"kind": kind, "mode": "controlnet", "name": fallback}
    if _model_file_exists(CN_UPSCALER_DIR, full):
        raise RuntimeError(
            f"{full} は ControlNetLoader では読めません。"
            f"C:\\AI\\ComfyUI\\models\\diffusion_models に移動するか、"
            f"{lora} を C:\\AI\\ComfyUI\\models\\loras に置いてください。"
        )
    return None


def _bfl_control_status():
    status = {}
    for kind in BFL_CONTROL_LORAS:
        resolved = _resolve_bfl_control(kind)
        status[kind] = {
            "available": bool(resolved),
            "mode": resolved["mode"] if resolved else "missing",
            "model": resolved["name"] if resolved else BFL_CONTROL_LORAS[kind],
            "lora": BFL_CONTROL_LORAS[kind],
            "full": BFL_CONTROL_FULL_MODELS[kind],
            "fallback": BFL_CN_MODELS[kind],
            "misplaced_full_model": _model_file_exists(CN_UPSCALER_DIR, BFL_CONTROL_FULL_MODELS[kind]),
        }
    return status


def build_bfl_ip2p_control_workflow(control_image_name, prompt, width, height, steps, seed,
                                    kind, resolved, strength=1.0,
                                    sampler="euler", scheduler="normal", cfg=1.0,
                                    guidance=30.0, preprocessor="none", batch_size=1):
    if resolved["mode"] == "lora":
        cfg = max(float(cfg), 2.0)
        if float(guidance) < 10:
            guidance = 35.0 if kind == "depth" else 30.0
    elif float(guidance) < 10:
        guidance = 30.0

    wf = {}
    wf.update(_build_model_nodes())
    wf["12"]["inputs"]["weight_dtype"] = "fp8_e4m3fn"
    model_ref = ["12", 0]
    if resolved["mode"] == "full":
        wf["12"]["inputs"]["unet_name"] = resolved["name"]
    elif resolved["mode"] == "lora":
        wf["43"] = {"class_type": "LoraLoaderModelOnly",
                    "inputs": {"model": model_ref, "lora_name": resolved["name"],
                               "strength_model": float(strength)}}
        model_ref = ["43", 0]

    wf["7"] = {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["11", 0]}}
    wf["23"] = {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["11", 0]}}
    wf["26"] = {"class_type": "FluxGuidance",
                "inputs": {"guidance": float(guidance), "conditioning": ["23", 0]}}
    wf["17"] = {"class_type": "LoadImage", "inputs": {"image": control_image_name, "upload": "image"}}
    image_ref = ["17", 0]
    if kind == "canny":
        wf["18"] = {"class_type": "Canny",
                    "inputs": {"low_threshold": 0.15, "high_threshold": 0.3,
                               "image": image_ref}}
        image_ref = ["18", 0]
    elif kind == "depth" and preprocessor and preprocessor != "none":
        wf["18"] = {"class_type": "AIO_Preprocessor",
                    "inputs": {"preprocessor": preprocessor,
                               "image": image_ref, "resolution": max(width, height)}}
        image_ref = ["18", 0]

    wf["35"] = {"class_type": "InstructPixToPixConditioning",
                "inputs": {"positive": ["26", 0], "negative": ["7", 0],
                           "vae": ["10", 0], "pixels": image_ref}}
    latent_ref = ["35", 2]
    if int(batch_size) > 1:
        wf["36"] = {"class_type": "RepeatLatentBatch",
                    "inputs": {"samples": ["35", 2], "amount": int(batch_size)}}
        latent_ref = ["36", 0]
    wf["3"] = {"class_type": "KSampler",
               "inputs": {"seed": seed, "steps": steps, "cfg": cfg,
                          "sampler_name": sampler, "scheduler": scheduler,
                          "denoise": 1.0, "model": model_ref,
                          "positive": ["35", 0], "negative": ["35", 1],
                          "latent_image": latent_ref}}
    wf["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["10", 0]}}
    wf["9"] = {"class_type": "SaveImage",
               "inputs": {"images": ["8", 0], "filename_prefix": f"flux_{kind}_{resolved['mode']}"}}
    return wf


@app.route("/api/controlnet", methods=["POST"])
def controlnet():
    data     = request.json or {}
    filename  = data.get("filename", "")
    subfolder = data.get("subfolder", "")
    img_type  = data.get("type", "output")
    prompt    = data.get("prompt", "").strip()
    cn_name   = data.get("controlnet_name", "")
    cn_str    = float(data.get("controlnet_strength", 1.0))
    preproc   = data.get("preprocessor", "none")
    width     = max(64, min(2048, int(data.get("width", 1024))))
    height    = max(64, min(2048, int(data.get("height", 1024))))
    steps     = max(1, min(100, int(data.get("steps", 20))))
    sampler   = data.get("sampler", "euler")
    scheduler = data.get("scheduler", "simple")
    cfg       = float(data.get("cfg", 1.0))
    seed      = random.randint(0, 2**31 - 1)

    if not filename:
        return jsonify({"error": "filename is required"}), 400
    if not cn_name:
        return jsonify({"error": "controlnet_name is required"}), 400

    if prompt and _is_japanese(prompt):
        prompt = _translate(prompt)

    try:
        uploaded_name = _fetch_and_upload_image(filename, subfolder, img_type)
        kind = data.get("control_type") or _control_kind_from_name(cn_name)
        resolved = _resolve_bfl_control(kind, cn_name) if kind else None
        if resolved and resolved["mode"] in ("lora", "full"):
            workflow = build_bfl_ip2p_control_workflow(
                uploaded_name, prompt, width, height, steps, seed,
                kind, resolved, cn_str, sampler, scheduler, cfg,
                float(data.get("guidance", 30.0)), preproc
            )
        else:
            workflow = build_controlnet_workflow(
                uploaded_name, prompt, width, height, steps, seed,
                cn_name, cn_str, preproc, sampler, scheduler, cfg
            )
        prompt_id, _ = _queue_workflow(workflow)
        return jsonify({"prompt_id": prompt_id, "seed": seed})
    except requests.ConnectionError:
        return jsonify({"error": "ComfyUIに接続できません"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _fetch_models(kind):
    """Fetch model files for a kind. Filters cache/hidden paths."""
    try:
        r = requests.get(f"{COMFY_URL}/models/{kind}", timeout=5)
        r.raise_for_status()
        raw = r.json()
        return [m for m in raw if not m.startswith(("_", ".")) and "_hf_cache" not in m]
    except Exception:
        return []


def _local_model_files(kind):
    dirs = {
        "diffusion_models": DIFFM_DIR,
        "unet": UNET_DIR,
    }
    root = dirs.get(kind)
    if not root or not os.path.isdir(root):
        return []
    models = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(("_", ".")) and "_hf_cache" not in d]
        for filename in filenames:
            if filename.startswith(("_", ".")):
                continue
            if not filename.lower().endswith((".safetensors", ".gguf", ".ckpt", ".pt", ".pth")):
                continue
            rel = os.path.relpath(os.path.join(dirpath, filename), root)
            if "_hf_cache" in rel:
                continue
            models.append(rel.replace("/", "\\"))
    return models


def _is_visible_base_model(name):
    n = (name or "").lower()
    if any(x in n for x in ("canny", "depth", "fill", "kontext", "redux", "controlnet", "upscale", "inpaint", "outpaint")):
        return False
    return bool(re.search(r"(flux\.?1|flux[-_ ]?1|flux\.?2|flux[-_ ]?2|krea)", n))


@app.route("/api/comfy/models")
def comfy_models():
    unet_all = (
        (_fetch_models("diffusion_models") or []) +
        (_fetch_models("unet") or []) +
        _local_model_files("diffusion_models") +
        _local_model_files("unet")
    )
    seen = set()
    unet = []
    for model in unet_all:
        if model in seen or not _is_visible_base_model(model):
            continue
        seen.add(model)
        unet.append(model)
    if not unet:
        unet = ["flux1-dev.safetensors"]
    raw_cn = _fetch_models("controlnet")
    # BFL official models only (Canny + Depth)
    allowed = set(BFL_CN_MODELS.values())
    controlnets = [m for m in raw_cn if m in allowed]
    bfl_control = _bfl_control_status()
    return jsonify({
        "unet":               unet,
        "flux2_info":         _flux2_model_info(),
        "flux2_missing":      _flux2_missing_requirements(),
        "loras":              _fetch_models("loras"),
        "controlnets":        controlnets,
        "bfl_control":        bfl_control,
        "cn_preprocessors":   CN_PREPROCESSOR_MAP,
        "samplers":           DEFAULT_SAMPLERS,
        "schedulers":         DEFAULT_SCHEDULERS,
        "kontext_available":  bool(_kontext_models()),
        "kontext_models":     _kontext_models(),
        "redux_available":    _model_file_exists(REDUX_MODEL_DIR, REDUX_MODEL) and
                              _model_file_exists(REDUX_CLIP_DIR, REDUX_CLIP_MODEL),
        "upscaler_available": _model_file_exists(CN_UPSCALER_DIR, CN_UPSCALER_MODEL),
        "video_upscale_available": os.path.isdir(
            os.path.join(_COMFYUI_DIR, "custom_nodes", "ComfyUI-SeedVR2_VideoUpscaler")
        ),
        "fill_available":     _model_file_exists(FILL_MODEL_DIR, FILL_MODEL),
        "wan22_available": (
            any(_wan22_model_exists(n) for n in WAN22_HIGH_UNET_CANDIDATES) and
            any(_wan22_model_exists(n) for n in WAN22_LOW_UNET_CANDIDATES)
        ),
        "wan22_high_available": any(_wan22_model_exists(n) for n in WAN22_HIGH_UNET_CANDIDATES),
        "wan22_low_available":  any(_wan22_model_exists(n) for n in WAN22_LOW_UNET_CANDIDATES),
    })


@app.route("/api/kontext_status")
def kontext_status():
    model_name = _kontext_model_name(request.args.get("model"))
    model_path = _local_model_path(KONTEXT_MODEL_DIR, model_name)
    exists = os.path.exists(model_path)
    size_gb = round(os.path.getsize(model_path) / 1024**3, 1) if exists else 0
    return jsonify({"available": bool(_kontext_models()), "model": model_name, "models": _kontext_models(), "size_gb": size_gb})


@app.route("/api/kontext_download", methods=["POST"])
def kontext_download():
    """Download FLUX.1 Kontext dev model using provided HF token."""
    data = request.json or {}
    hf_token = data.get("hf_token", "").strip()
    if not hf_token:
        return jsonify({"error": "HuggingFaceトークンが必要です"}), 400
    model_path = os.path.join(KONTEXT_MODEL_DIR, KONTEXT_MODEL)
    if os.path.exists(model_path):
        return jsonify({"ok": True, "message": "既にダウンロード済みです"})
    try:
        from huggingface_hub import hf_hub_download
        import threading
        def _dl():
            try:
                p = hf_hub_download(
                    repo_id="black-forest-labs/FLUX.1-Kontext-dev",
                    filename="flux1-kontext-dev.safetensors",
                    local_dir=KONTEXT_MODEL_DIR,
                    local_dir_use_symlinks=False,
                    token=hf_token,
                )
                if p != model_path:
                    os.rename(p, model_path)
            except Exception as e:
                print(f"Kontext download failed: {e}")
        t = threading.Thread(target=_dl, daemon=True)
        t.start()
        return jsonify({"ok": True, "message": "ダウンロード開始（~24GB、完了まで時間がかかります）"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _tile_images_for_kontext(main_name, ref_list):
    """Tile main image + reference images horizontally and upload to ComfyUI."""
    from PIL import Image as PILImage
    imgs = []
    # Fetch main image
    r = requests.get(f"{COMFY_URL}/view",
                     params={"filename": main_name, "subfolder": "", "type": "input"},
                     timeout=30)
    r.raise_for_status()
    imgs.append(PILImage.open(io.BytesIO(r.content)).convert("RGB"))
    # Fetch references
    for ref in ref_list:
        r = requests.get(f"{COMFY_URL}/view",
                         params={"filename": ref["filename"],
                                 "subfolder": ref.get("subfolder", ""),
                                 "type": ref.get("type", "input")},
                         timeout=30)
        r.raise_for_status()
        imgs.append(PILImage.open(io.BytesIO(r.content)).convert("RGB"))
    # Resize all to same height (max height of all images)
    max_h = max(i.height for i in imgs)
    resized = []
    for img in imgs:
        w = int(img.width * max_h / img.height)
        resized.append(img.resize((w, max_h), PILImage.LANCZOS))
    total_w = sum(i.width for i in resized)
    canvas = PILImage.new("RGB", (total_w, max_h))
    x = 0
    for img in resized:
        canvas.paste(img, (x, 0))
        x += img.width
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    tiled_name = f"ktx_tiled_{random.randint(0,999999)}.png"
    files = {"image": (tiled_name, buf.read(), "image/png"), "overwrite": (None, "true")}
    up = requests.post(f"{COMFY_URL}/upload/image", files=files, timeout=30)
    up.raise_for_status()
    return up.json().get("name", tiled_name)


@app.route("/api/kontext", methods=["POST"])
def kontext():
    """FLUX.1 Kontext [dev] image editing with at most one optional reference image."""
    data = request.json or {}
    filename    = data.get("filename", "")
    subfolder   = data.get("subfolder", "")
    img_type    = data.get("type", "output")
    instruction = data.get("instruction", "").strip()
    guidance    = float(data.get("guidance", 2.5))
    steps       = max(1, min(50, int(data.get("steps", 28))))
    sampler     = data.get("sampler", "euler")
    scheduler   = data.get("scheduler", "simple")
    model_name  = data.get("kontext_model") or data.get("model")
    refs        = (data.get("refs", []) or [])[:1]  # [{filename, subfolder, type}]
    batch_size  = max(1, min(16, int(data.get("batch_size", 1))))
    seed        = random.randint(0, 2**31 - 1)

    if not filename:
        return jsonify({"error": "filename is required"}), 400
    if not instruction:
        return jsonify({"error": "編集指示を入力してください"}), 400

    if not _kontext_models():
        return jsonify({"error": f"Kontextモデル未インストール ({KONTEXT_FP8_MODEL} または {KONTEXT_MODEL})"}), 400
    model_name = _kontext_model_name(model_name)

    if _is_japanese(instruction):
        instruction = _translate(instruction)

    try:
        uploaded_name = _fetch_and_upload_image(filename, subfolder, img_type)
        # If reference images provided, tile them horizontally
        if refs:
            tiled = _tile_images_for_kontext(uploaded_name, refs)
            workflow = build_kontext_workflow(tiled, instruction, steps, seed, guidance, sampler, scheduler, model_name, batch_size)
        else:
            workflow = build_kontext_workflow(uploaded_name, instruction, steps, seed, guidance, sampler, scheduler, model_name, batch_size)
        prompt_id, client_id = _queue_workflow(workflow)
        _gallery_pending[prompt_id] = {
            "prompt": instruction, "seed": seed,
            "steps": steps, "sampler": sampler, "scheduler": scheduler,
            "tags": ["kontext"], "is_video": False,
        }
        return jsonify({"prompt_id": prompt_id, "client_id": client_id, "seed": seed})
    except requests.ConnectionError:
        return jsonify({"error": "ComfyUIに接続できません"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/status/<prompt_id>")
def status(prompt_id):
    try:
        queue   = requests.get(f"{COMFY_URL}/queue", timeout=5).json()
        running = [item[1] for item in queue.get("queue_running", [])]
        pending = [item[1] for item in queue.get("queue_pending", [])]

        if prompt_id in running:
            return jsonify({"status": "running"})
        if prompt_id in pending:
            return jsonify({"status": "pending"})

        hist = requests.get(f"{COMFY_URL}/history/{prompt_id}", timeout=5).json()
        if prompt_id in hist:
            entry = hist[prompt_id]
            # Check for execution errors
            st = entry.get("status", {})
            if st.get("status_str") == "error":
                err_msg = "ComfyUI実行エラー"
                node_type = ""
                for msg in st.get("messages", []):
                    if isinstance(msg, (list, tuple)) and len(msg) >= 2:
                        kind, detail = msg[0], msg[1]
                        if kind == "execution_error" and isinstance(detail, dict):
                            err_msg = detail.get("exception_message", err_msg)
                            node_type = detail.get("node_type", "")
                            if node_type:
                                err_msg = f"[{node_type}] {err_msg}"
                            break
                        if kind in ("execution_cached", "execution_interrupted"):
                            continue
                return jsonify({"status": "error", "error": err_msg, "node_type": node_type})
            images = []
            seen = set()
            for node_out in entry.get("outputs", {}).values():
                for img in node_out.get("images", []):
                    key = (img.get("filename"), img.get("subfolder"), img.get("type"))
                    if key not in seen:
                        seen.add(key)
                        img_copy = dict(img)
                        if _is_video_output(img_copy):
                            img_copy["isVideo"] = True
                        _record_gallery_item(img_copy, _gallery_pending.get(prompt_id))
                        images.append(img_copy)
                for vid in node_out.get("videos", node_out.get("gifs", [])):
                    key = (vid.get("filename"), vid.get("subfolder"), vid.get("type"))
                    if key not in seen:
                        seen.add(key)
                        vid_copy = dict(vid)
                        vid_copy["isVideo"] = True
                        _record_gallery_item(vid_copy, _gallery_pending.get(prompt_id))
                        images.append(vid_copy)
            _gallery_pending.pop(prompt_id, None)
            return jsonify({"status": "done", "images": images})

        return jsonify({"status": "not_found"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/upload_control", methods=["POST"])
def upload_control():
    if "image" not in request.files:
        return jsonify({"error": "image file required"}), 400
    f = request.files["image"]
    raw, _, _, _ = _shrink_for_flux(f.read())
    files = {"image": (f.filename, raw, "image/png"),
             "overwrite": (None, "true")}
    try:
        r = requests.post(f"{COMFY_URL}/upload/image", files=files, timeout=30)
        r.raise_for_status()
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


COMFY_OUTPUT_DIR = os.path.join(_COMFYUI_DIR, "output")
GALLERY_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gallery.db")
GALLERY_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm", ".mov", ".gif"}
GALLERY_VIDEO_EXTS = {".mp4", ".webm", ".mov", ".gif"}


def _gallery_conn():
    conn = sqlite3.connect(GALLERY_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            subfolder TEXT DEFAULT '',
            type TEXT DEFAULT 'output',
            is_video INTEGER DEFAULT 0,
            prompt TEXT,
            seed INTEGER,
            width INTEGER,
            height INTEGER,
            steps INTEGER,
            sampler TEXT,
            scheduler TEXT,
            cfg REAL,
            tags TEXT,
            created_at REAL,
            updated_at REAL,
            UNIQUE(filename, subfolder, type)
        )
    """)
    conn.commit()
    return conn


def _safe_output_path(filename, subfolder=""):
    filename = os.path.basename(filename or "")
    subfolder = (subfolder or "").replace("\\", os.sep).replace("/", os.sep).strip(os.sep)
    base = os.path.abspath(COMFY_OUTPUT_DIR)
    path = os.path.abspath(os.path.join(base, subfolder, filename))
    if not filename or not (path == base or path.startswith(base + os.sep)):
        raise ValueError("invalid output path")
    return path


def _image_dims(path):
    try:
        from PIL import Image as PILImage
        with PILImage.open(path) as im:
            return im.width, im.height
    except Exception:
        return None, None


def _gallery_item_from_file(path):
    rel = os.path.relpath(path, COMFY_OUTPUT_DIR)
    subfolder = os.path.dirname(rel)
    if subfolder == ".":
        subfolder = ""
    filename = os.path.basename(path)
    ext = os.path.splitext(filename)[1].lower()
    is_video = 1 if ext in GALLERY_VIDEO_EXTS else 0
    st = os.stat(path)
    w, h = (None, None) if is_video else _image_dims(path)
    return {
        "filename": filename,
        "subfolder": subfolder.replace(os.sep, "/"),
        "type": "output",
        "is_video": is_video,
        "width": w,
        "height": h,
        "created_at": st.st_mtime,
    }


_gallery_pending = {}   # {prompt_id: meta dict passed to _record_gallery_item}
_last_gallery_scan = 0.0


def _scan_gallery_outputs(limit_new=None):
    global _last_gallery_scan
    now = time.time()
    if not limit_new and now - _last_gallery_scan < 30:
        return 0
    _last_gallery_scan = now
    if not os.path.isdir(COMFY_OUTPUT_DIR):
        return 0
    conn = _gallery_conn()
    added = 0
    try:
        for root, _, files in os.walk(COMFY_OUTPUT_DIR):
            for name in files:
                if os.path.splitext(name)[1].lower() not in GALLERY_EXTS:
                    continue
                path = os.path.join(root, name)
                try:
                    item = _gallery_item_from_file(path)
                    before = conn.total_changes
                    conn.execute(
                        """INSERT OR IGNORE INTO images
                           (filename, subfolder, type, is_video, width, height, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            item["filename"], item["subfolder"], item["type"],
                            item["is_video"], item["width"], item["height"],
                            item["created_at"], time.time(),
                        ),
                    )
                    if conn.total_changes > before:
                        added += 1
                    if limit_new and added >= limit_new:
                        conn.commit()
                        return added
                except Exception:
                    continue
        conn.commit()
        return added
    finally:
        conn.close()


def _record_gallery_item(item, meta=None):
    if not item:
        return
    filename = item.get("filename", "")
    subfolder = item.get("subfolder", "") or ""
    img_type = item.get("type", "output") or "output"
    if img_type != "output":
        return
    meta = meta or {}
    try:
        path = _safe_output_path(filename, subfolder)
        if os.path.isfile(path):
            file_item = _gallery_item_from_file(path)
        else:
            file_item = {}
    except Exception:
        file_item = {}
    tags = meta.get("tags") or meta.get("autoTags")
    if isinstance(tags, (list, tuple)):
        tags = json.dumps(list(tags), ensure_ascii=False)
    conn = _gallery_conn()
    try:
        conn.execute(
            """INSERT INTO images
               (filename, subfolder, type, is_video, prompt, seed, width, height, steps, sampler, scheduler, cfg, tags, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(filename, subfolder, type) DO UPDATE SET
                 is_video=excluded.is_video,
                 prompt=COALESCE(excluded.prompt, images.prompt),
                 seed=COALESCE(excluded.seed, images.seed),
                 width=COALESCE(excluded.width, images.width),
                 height=COALESCE(excluded.height, images.height),
                 steps=COALESCE(excluded.steps, images.steps),
                 sampler=COALESCE(excluded.sampler, images.sampler),
                 scheduler=COALESCE(excluded.scheduler, images.scheduler),
                 cfg=COALESCE(excluded.cfg, images.cfg),
                 tags=COALESCE(excluded.tags, images.tags),
                 created_at=COALESCE(images.created_at, excluded.created_at),
                 updated_at=excluded.updated_at""",
            (
                os.path.basename(filename), subfolder.replace("\\", "/").strip("/"), "output",
                1 if (item.get("isVideo") or item.get("is_video") or file_item.get("is_video")) else 0,
                meta.get("prompt"), meta.get("seed"),
                meta.get("width") or meta.get("w") or file_item.get("width"),
                meta.get("height") or meta.get("h") or file_item.get("height"),
                meta.get("steps"), meta.get("sampler"), meta.get("scheduler"),
                meta.get("cfg"), tags, file_item.get("created_at") or time.time(), time.time(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _gallery_row(row):
    tags = []
    if row["tags"]:
        try:
            tags = json.loads(row["tags"])
        except Exception:
            tags = []
    subfolder = row["subfolder"] or ""
    rtype = row["type"] or "output"
    url = f"/api/image?filename={row['filename']}&subfolder={subfolder}&type={rtype}"
    return {
        "url": url,
        "filename": row["filename"],
        "subfolder": subfolder,
        "type": rtype,
        "isVideo": bool(row["is_video"]),
        "is_video": bool(row["is_video"]),
        "prompt": row["prompt"] or "",
        "seed": row["seed"],
        "w": row["width"],
        "h": row["height"],
        "width": row["width"],
        "height": row["height"],
        "steps": row["steps"],
        "sampler": row["sampler"] or "",
        "scheduler": row["scheduler"] or "",
        "cfg": row["cfg"],
        "autoTags": tags,
        "tags": tags,
        "ts": int((row["created_at"] or 0) * 1000),
        "created_at": row["created_at"],
    }
def _gallery_row_file_exists(row):
    try:
        rtype = row["type"] or "output"
        if rtype != "output":
            return True
        return os.path.isfile(_safe_output_path(row["filename"], row["subfolder"] or ""))
    except Exception:
        return False


def _prune_missing_gallery_rows(conn):
    rows = conn.execute("SELECT id, filename, subfolder, type FROM images WHERE type='output'").fetchall()
    missing = [r["id"] for r in rows if not _gallery_row_file_exists(r)]
    if missing:
        conn.executemany("DELETE FROM images WHERE id = ?", [(i,) for i in missing])
        conn.commit()
    return len(missing)

@app.route("/api/gallery")
def gallery_list():
    _scan_gallery_outputs()
    page = max(0, int(request.args.get("page", 0)))
    per_page = max(1, min(100, int(request.args.get("per_page", 40))))
    flt = request.args.get("filter", "all")
    now = time.time()
    where = ["type = 'output'"]
    args = []
    if flt == "today":
        lt = time.localtime(now)
        start = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, lt.tm_wday, lt.tm_yday, lt.tm_isdst))
        where.append("created_at >= ?")
        args.append(start)
    elif flt == "week":
        where.append("created_at >= ?")
        args.append(now - 7 * 86400)
    elif flt == "month":
        where.append("created_at >= ?")
        args.append(now - 31 * 86400)
    where_sql = " AND ".join(where)
    conn = _gallery_conn()
    try:
        _prune_missing_gallery_rows(conn)
        total = conn.execute(f"SELECT COUNT(*) FROM images WHERE {where_sql}", args).fetchone()[0]
        rows = conn.execute(
            f"""SELECT * FROM images WHERE {where_sql}
                ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?""",
            args + [per_page, page * per_page],
        ).fetchall()
        return jsonify({
            "items": [_gallery_row(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "has_more": (page + 1) * per_page < total,
        })
    finally:
        conn.close()


@app.route("/api/gallery/record", methods=["POST"])
def gallery_record():
    data = request.json or {}
    item = data.get("item") or data
    meta = data.get("meta") or item
    _record_gallery_item(item, meta)
    return jsonify({"ok": True})


@app.route("/api/gallery/migrate", methods=["POST"])
def gallery_migrate():
    data = request.json or {}
    items = data.get("items", [])
    count = 0
    for item in items:
        try:
            _record_gallery_item(item, item)
            count += 1
        except Exception:
            continue
    return jsonify({"ok": True, "count": count})


@app.route("/api/gallery/delete", methods=["DELETE", "POST"])
def gallery_delete():
    data = request.json or {}
    filename = data.get("filename", "")
    subfolder = data.get("subfolder", "") or ""
    img_type = data.get("type", "output") or "output"
    if img_type != "output":
        return jsonify({"error": "output file only"}), 400
    try:
        path = _safe_output_path(filename, subfolder)
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    removed_file = False
    if os.path.isfile(path):
        os.remove(path)
        removed_file = True
    conn = _gallery_conn()
    try:
        conn.execute(
            "DELETE FROM images WHERE filename=? AND subfolder=? AND type=?",
            (os.path.basename(filename), subfolder.replace("\\", "/").strip("/"), img_type),
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "removed_file": removed_file})


@app.route("/api/gallery/scan", methods=["POST"])
def gallery_scan():
    global _last_gallery_scan
    _last_gallery_scan = 0.0  # force re-scan
    added = _scan_gallery_outputs()
    return jsonify({"ok": True, "added": added})


@app.route("/api/gallery/clear", methods=["DELETE"])
def gallery_clear():
    flt = request.args.get("filter", "all")
    now = time.time()
    conn = _gallery_conn()
    try:
        if flt == "today":
            lt = time.localtime(now)
            start = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, lt.tm_wday, lt.tm_yday, lt.tm_isdst))
            rows = conn.execute("SELECT filename, subfolder FROM images WHERE type='output' AND created_at >= ?", (start,)).fetchall()
        elif flt == "week":
            rows = conn.execute("SELECT filename, subfolder FROM images WHERE type='output' AND created_at >= ?", (now - 7 * 86400,)).fetchall()
        elif flt == "month":
            rows = conn.execute("SELECT filename, subfolder FROM images WHERE type='output' AND created_at >= ?", (now - 31 * 86400,)).fetchall()
        else:
            rows = conn.execute("SELECT filename, subfolder FROM images WHERE type='output'").fetchall()
    finally:
        conn.close()

    deleted = 0
    for filename, subfolder in rows:
        try:
            path = _safe_output_path(filename, subfolder or "")
            if os.path.isfile(path):
                os.remove(path)
                deleted += 1
        except Exception:
            pass

    conn = _gallery_conn()
    try:
        if flt == "today":
            conn.execute("DELETE FROM images WHERE type='output' AND created_at >= ?", (start,))
        elif flt == "week":
            conn.execute("DELETE FROM images WHERE type='output' AND created_at >= ?", (now - 7 * 86400,))
        elif flt == "month":
            conn.execute("DELETE FROM images WHERE type='output' AND created_at >= ?", (now - 31 * 86400,))
        else:
            conn.execute("DELETE FROM images WHERE type='output'")
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True, "deleted": deleted})

@app.route("/api/image")
def get_image():
    filename = request.args.get("filename", "")
    subfolder = request.args.get("subfolder", "")
    img_type  = request.args.get("type", "output")
    if img_type == "input":
        base = os.path.join(os.path.dirname(COMFY_OUTPUT_DIR), "input")
    elif img_type == "temp":
        base = os.path.join(os.path.dirname(COMFY_OUTPUT_DIR), "temp")
    else:
        base = COMFY_OUTPUT_DIR
    if subfolder:
        path = os.path.join(base, subfolder, filename)
    else:
        path = os.path.join(base, filename)
    if not os.path.isfile(path):
        return jsonify({"error": "not found"}), 404
    ext = os.path.splitext(filename.lower())[1]
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "application/octet-stream")
    return send_file(path, mimetype=mime, conditional=True)

@app.route("/api/video")
def get_video():
    filename = request.args.get("filename", "")
    subfolder = request.args.get("subfolder", "")
    # Serve directly so Flask handles Range requests (required for iOS Safari)
    if subfolder:
        path = os.path.join(COMFY_OUTPUT_DIR, subfolder, filename)
    else:
        path = os.path.join(COMFY_OUTPUT_DIR, filename)
    if not os.path.isfile(path):
        return jsonify({"error": "not found"}), 404
    ext = os.path.splitext(filename.lower())[1]
    mime = {".webm": "video/webm", ".mov": "video/quicktime", ".gif": "image/gif"}.get(ext, "video/mp4")
    return send_file(path, mimetype=mime, conditional=True)

# ── Outpainting ──────────────────────────────────────────────────
def build_outpaint_workflow(image_name, prompt, pad_top, pad_right, pad_bottom, pad_left,
                             steps, seed, cfg=2.0, sampler="euler", scheduler="normal",
                             guidance=30.0):
    wf = {}
    wf.update(_build_model_nodes())
    wf["12"] = {"class_type": "UNETLoader",
                "inputs": {"unet_name": _fill_model_name(), "weight_dtype": "fp8_e4m3fn"}}
    wf["14"] = {"class_type": "DifferentialDiffusion",
                "inputs": {"model": ["12", 0]}}
    wf["1"]  = {"class_type": "LoadImage",
                "inputs": {"image": image_name, "upload": "image"}}
    wf["2"]  = {"class_type": "ImagePadForOutpaint",
                "inputs": {"image": ["1", 0], "left": pad_left, "top": pad_top,
                           "right": pad_right, "bottom": pad_bottom, "feathering": 40}}
    wf["6"]  = {"class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["11", 0]}}
    wf["15"] = {"class_type": "FluxGuidance",
                "inputs": {"guidance": guidance, "conditioning": ["6", 0]}}
    wf["33"] = {"class_type": "CLIPTextEncode",
                "inputs": {"text": "", "clip": ["11", 0]}}
    wf["3"]  = {"class_type": "InpaintModelConditioning",
                "inputs": {"noise_mask": False,
                           "positive": ["15", 0], "negative": ["33", 0],
                           "vae": ["10", 0], "pixels": ["2", 0], "mask": ["2", 1]}}
    wf["13"] = {"class_type": "KSampler",
                "inputs": {"cfg": cfg, "denoise": 1.0,
                           "latent_image": ["3", 2], "model": ["14", 0],
                           "negative": ["3", 1], "positive": ["3", 0],
                           "sampler_name": sampler, "scheduler": scheduler,
                           "seed": seed, "steps": steps}}
    wf["8"]  = {"class_type": "VAEDecode",
                "inputs": {"samples": ["13", 0], "vae": ["10", 0]}}
    wf["9"]  = {"class_type": "SaveImage",
                "inputs": {"images": ["8", 0], "filename_prefix": "flux_outpaint"}}
    return wf


@app.route("/api/outpaint", methods=["POST"])
def outpaint():
    data = request.json or {}
    filename  = data.get("filename", "")
    subfolder = data.get("subfolder", "")
    img_type  = data.get("type", "output")
    prompt    = data.get("prompt", "").strip()
    pad_top    = int(data.get("pad_top", 0))
    pad_right  = int(data.get("pad_right", 0))
    pad_bottom = int(data.get("pad_bottom", 0))
    pad_left   = int(data.get("pad_left", 0))
    steps     = max(1, min(100, int(data.get("steps", 20))))
    cfg       = float(data.get("cfg", 1.0))
    seed      = random.randint(0, 2**31 - 1)

    if not filename:
        return jsonify({"error": "filename is required"}), 400
    if pad_top + pad_right + pad_bottom + pad_left == 0:
        return jsonify({"error": "少なくとも1辺の拡張量を指定してください"}), 400
    if prompt and _is_japanese(prompt):
        prompt = _translate(prompt)
    try:
        uploaded = _fetch_and_upload_image(filename, subfolder, img_type)
        wf = build_outpaint_workflow(uploaded, prompt, pad_top, pad_right, pad_bottom, pad_left,
                                      steps, seed, cfg)
        pid, cid = _queue_workflow(wf)
        _gallery_pending[pid] = {
            "prompt": prompt, "seed": seed,
            "steps": steps, "cfg": cfg,
            "tags": ["outpaint"], "is_video": False,
        }
        return jsonify({"prompt_id": pid, "client_id": cid, "seed": seed})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Multi-ControlNet ─────────────────────────────────────────────
def build_multicn_workflow(prompt, width, height, steps, seed,
                            cn_list, sampler="euler", scheduler="simple", cfg=1.0,
                            guidance=3.5, batch_size=1):
    """cn_list: [{image_name, name, strength, preprocessor, start_percent, end_percent}]"""
    if len(cn_list) == 1:
        cn = cn_list[0]
        kind = cn.get("kind") or _control_kind_from_name(cn.get("name"))
        resolved = _resolve_bfl_control(kind, cn.get("name")) if kind else None
        if resolved and resolved["mode"] in ("lora", "full"):
            return build_bfl_ip2p_control_workflow(
                cn["image_name"], prompt, width, height, steps, seed,
                kind, resolved, float(cn.get("strength", 1.0)),
                sampler, scheduler, cfg, guidance, cn.get("preprocessor", "none"),
                batch_size=batch_size
            )
    official_modes = []
    for cn in cn_list:
        kind = cn.get("kind") or _control_kind_from_name(cn.get("name"))
        resolved = _resolve_bfl_control(kind, cn.get("name")) if kind else None
        if resolved and resolved["mode"] in ("lora", "full"):
            official_modes.append(f"{kind}:{resolved['mode']}")
    if official_modes:
        raise RuntimeError(
            "BFL公式Canny/DepthのLoRA/fullモデルは1種類ずつ実行してください。"
            f" 同時指定: {', '.join(official_modes)}"
        )

    wf = {}
    wf.update(_build_model_nodes())
    wf["6"]  = {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["11", 0]}}
    wf["33"] = {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["11", 0]}}
    pos_ref = ["6", 0]
    neg_ref = ["33", 0]
    base = 200
    for i, cn in enumerate(cn_list):
        if not cn.get("image_name") or not cn.get("name"):
            continue
        img_id  = str(base + i*10 + 0)
        ld_id   = str(base + i*10 + 1)
        app_id  = str(base + i*10 + 2)
        pre_id  = str(base + i*10 + 3)
        wf[img_id] = {"class_type": "LoadImage",
                       "inputs": {"image": cn["image_name"], "upload": "image"}}
        ctrl_img = [img_id, 0]
        preproc = cn.get("preprocessor", "none")
        if preproc and preproc != "none":
            wf[pre_id] = {"class_type": "AIO_Preprocessor",
                           "inputs": {"preprocessor": preproc, "image": ctrl_img,
                                      "resolution": max(width, height)}}
            ctrl_img = [pre_id, 0]
        wf[ld_id] = {"class_type": "ControlNetLoader",
                      "inputs": {"control_net_name": cn["name"]}}
        wf[app_id] = {"class_type": "ControlNetApplyAdvanced",
                       "inputs": {"positive":      pos_ref,
                                  "negative":      neg_ref,
                                  "control_net":   [ld_id, 0],
                                  "vae":           ["10", 0],
                                  "image":         ctrl_img,
                                  "strength":      float(cn.get("strength", 0.8)),
                                  "start_percent": float(cn.get("start_percent", 0.0)),
                                  "end_percent":   float(cn.get("end_percent", 1.0))}}
        pos_ref = [app_id, 0]
        neg_ref = [app_id, 1]
    # FluxGuidance is required for BFL Canny/Depth ControlNet models
    wf["fg"] = {"class_type": "FluxGuidance",
                "inputs": {"conditioning": pos_ref, "guidance": float(guidance)}}
    wf["27"] = {"class_type": "EmptyLatentImage",
                "inputs": {"batch_size": int(batch_size), "height": height, "width": width}}
    wf["13"] = {"class_type": "KSampler",
                "inputs": {"cfg": 1.0, "denoise": 1.0,
                           "latent_image": ["27", 0], "model": ["12", 0],
                           "negative": neg_ref, "positive": ["fg", 0],
                           "sampler_name": sampler, "scheduler": scheduler,
                           "seed": seed, "steps": steps}}
    wf["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["10", 0]}}
    wf["9"] = {"class_type": "SaveImage",
               "inputs": {"images": ["8", 0], "filename_prefix": "flux_multicn"}}
    return wf


@app.route("/api/multicn", methods=["POST"])
def multicn():
    data = request.json or {}
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "プロンプトが必要"}), 400
    if _is_japanese(prompt):
        prompt = _translate(prompt)
    cn_list = data.get("controlnets", [])
    if not cn_list:
        return jsonify({"error": "ControlNetが指定されていません"}), 400
    width    = max(64, min(2048, int(data.get("width", 1024))))
    height   = max(64, min(2048, int(data.get("height", 1024))))
    steps    = max(1, min(100, int(data.get("steps", 20))))
    cfg        = float(data.get("cfg", 1.0))
    guidance   = float(data.get("guidance", 3.5))
    batch_size = max(1, min(4, int(data.get("batch_size", 1))))
    seed       = random.randint(0, 2**31 - 1)
    try:
        # Upload all CN images
        prepared = []
        for cn in cn_list:
            if not cn.get("filename"):
                continue
            name = _fetch_and_upload_image(cn["filename"], cn.get("subfolder",""), cn.get("type","output"))
            prepared.append({"image_name": name, "name": cn["name"],
                            "kind": cn.get("kind") or _control_kind_from_name(cn.get("name", "")),
                            "strength": cn.get("strength", 0.8),
                            "preprocessor": cn.get("preprocessor", "none"),
                            "start_percent": cn.get("start_percent", 0.0),
                            "end_percent": cn.get("end_percent", 1.0)})
        wf = build_multicn_workflow(prompt, width, height, steps, seed, prepared,
                                    cfg=cfg, guidance=guidance, batch_size=batch_size)
        pid, cid = _queue_workflow(wf)
        _gallery_pending[pid] = {
            "prompt": prompt, "seed": seed,
            "width": width, "height": height,
            "steps": steps, "cfg": cfg,
            "tags": ["controlnet"], "is_video": False,
        }
        return jsonify({"prompt_id": pid, "client_id": cid, "seed": seed})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Logs & diagnostics ───────────────────────────────────────────
@app.route("/api/logs")
def api_logs():
    """Return recent ComfyUI job history, start.log, and model/node diagnostics."""
    # start.log (last 80 lines)
    log_text = ""
    log_path = os.path.join(os.path.dirname(__file__), "start.log")
    try:
        for enc in ("utf-8", "cp932", "latin-1"):
            try:
                with open(log_path, "r", encoding=enc, errors="replace") as f:
                    lines = f.readlines()
                log_text = "".join(lines[-80:])
                break
            except UnicodeDecodeError:
                continue
    except Exception as e:
        log_text = f"(ログ読み込み失敗: {e})"

    # ComfyUI job history (most recent 30)
    jobs = []
    history_runlog = []
    try:
        hist = requests.get(f"{COMFY_URL}/history", timeout=5).json()
        for pid, entry in list(hist.items()):
            st = entry.get("status", {})
            status_str = st.get("status_str", "unknown")
            error_msg = node_type = None
            if status_str == "error":
                for msg in st.get("messages", []):
                    if isinstance(msg, (list, tuple)) and len(msg) >= 2:
                        kind, detail = msg[0], msg[1]
                        if kind == "execution_error" and isinstance(detail, dict):
                            error_msg = detail.get("exception_message", "unknown error")[:300]
                            node_type = detail.get("node_type")
                            break
            outputs = entry.get("outputs", {})
            num_images = 0
            num_videos = 0
            for o in outputs.values():
                for img in o.get("images", []):
                    if _is_video_output(img):
                        num_videos += 1
                    else:
                        num_images += 1
                num_videos += len(o.get("videos", [])) + len(o.get("gifs", []))
            jobs.append({"prompt_id": pid, "status": status_str,
                         "error": error_msg, "node_type": node_type,
                         "num_images": num_images, "num_videos": num_videos})
            prompt_payload = entry.get("prompt") or {}
            wf = prompt_payload
            if isinstance(prompt_payload, list) and len(prompt_payload) >= 3:
                wf = prompt_payload[2]
            if isinstance(wf, dict):
                history_runlog.append({
                    "ts": "ComfyUI history",
                    "mode": _infer_mode(wf),
                    "models": _extract_models(wf),
                    "pid": pid,
                    "status": status_str,
                    "error": error_msg,
                    "node_type": node_type,
                    "num_images": num_images,
                    "num_videos": num_videos,
                    "source": "history",
                })
        jobs = jobs[-30:]
        history_runlog = history_runlog[-30:]
    except Exception as e:
        jobs = [{"prompt_id": "ERROR", "status": "error",
                 "error": str(e), "node_type": None, "num_images": 0}]
    runlog = _sync_run_log_with_jobs(jobs)
    known_pids = {r.get("pid") for r in runlog if isinstance(r, dict)}
    for row in history_runlog:
        if row.get("pid") not in known_pids:
            runlog.append(row)
    runlog = runlog[-_RUN_LOG_MAX:]

    # Model file diagnostics
    UNET_DIR   = os.path.join(_COMFYUI_DIR, "models", "unet")
    DIFFM_DIR  = os.path.join(_COMFYUI_DIR, "models", "diffusion_models")
    CN_DIR     = os.path.join(_COMFYUI_DIR, "models", "controlnet")
    def _model_exists(dirs, name):
        return any(os.path.exists(os.path.join(d, name)) for d in dirs)
    bfl_status = _bfl_control_status()
    diag_models = {
        "FLUX.1 dev (base)":             _model_exists([UNET_DIR, DIFFM_DIR], MODEL_CONFIG["unet"]),
        "FLUX.2 dev":                    _model_file_exists(DIFFM_DIR, FLUX2_CONFIG["unet"]),
        f"FLUX.2 model: {FLUX2_CONFIG['unet']}": _model_file_exists(DIFFM_DIR, FLUX2_CONFIG["unet"]),
        "FLUX.2 text encoder":           _model_file_exists(TEXT_ENCODER_DIR, FLUX2_CONFIG["clip"]),
        f"FLUX.2 encoder: {_flux2_clip_name()}":
                                         _model_file_exists(TEXT_ENCODER_DIR, _flux2_clip_name()) or
                                         _model_file_exists(CLIP_DIR, _flux2_clip_name()),
        "FLUX.2 VAE":                    _model_file_exists(VAE_DIR, FLUX2_CONFIG["vae"]),
        f"FLUX.2 vae: {FLUX2_CONFIG['vae']}": _model_file_exists(VAE_DIR, FLUX2_CONFIG["vae"]),
        "Canny BFL full":                _model_file_exists(DIFFM_DIR, BFL_CONTROL_FULL_MODELS["canny"]),
        "Canny BFL LoRA":                _model_file_exists(LORA_MODEL_DIR, BFL_CONTROL_LORAS["canny"]),
        "Canny CN (flux1-canny-instantx)": _model_file_exists(CN_DIR, BFL_CN_MODELS["canny"]),
        "Canny active":                  bfl_status["canny"]["available"],
        "Depth BFL full":                _model_file_exists(DIFFM_DIR, BFL_CONTROL_FULL_MODELS["depth"]),
        "Depth BFL LoRA":                _model_file_exists(LORA_MODEL_DIR, BFL_CONTROL_LORAS["depth"]),
        "Depth CN (xlabs-flux-depth-v3)": _model_file_exists(CN_DIR, BFL_CN_MODELS["depth"]),
        "Depth active":                  bfl_status["depth"]["available"],
        "CN Upscaler (jasperai)":        _model_file_exists(CN_UPSCALER_DIR, CN_UPSCALER_MODEL),
        "Fill (inpaint/outpaint)":       _model_file_exists(FILL_MODEL_DIR, FILL_MODEL),
        "Redux":                         _model_file_exists(REDUX_MODEL_DIR, REDUX_MODEL),
        "Redux CLIP Vision":             _model_file_exists(REDUX_CLIP_DIR, REDUX_CLIP_MODEL),
        "Kontext":                       _model_file_exists(KONTEXT_MODEL_DIR, KONTEXT_MODEL) or
                                         _model_file_exists(KONTEXT_MODEL_DIR, KONTEXT_FP8_MODEL),
        "Kontext fp8":                   _model_file_exists(KONTEXT_MODEL_DIR, KONTEXT_FP8_MODEL),
        "Kontext full":                  _model_file_exists(KONTEXT_MODEL_DIR, KONTEXT_MODEL),
        f"Wan2.2 High": any(_wan22_model_exists(n) for n in WAN22_HIGH_UNET_CANDIDATES),
        f"Wan2.2 Low":  any(_wan22_model_exists(n) for n in WAN22_LOW_UNET_CANDIDATES),
        f"Wan2.2 VAE ({WAN22_CONFIG['vae']})":  _model_file_exists(VAE_DIR, WAN22_CONFIG["vae"]),
        f"Wan2.2 TextEnc ({WAN22_CONFIG['text_encoder']})": (
            _model_file_exists(TEXT_ENCODER_DIR, WAN22_CONFIG["text_encoder"]) or
            _model_file_exists(CLIP_DIR, WAN22_CONFIG["text_encoder"])
        ),
        f"Wan2.2 LoRA High ({WAN22_CONFIG['high']['lora']})": _model_file_exists(LORA_MODEL_DIR, WAN22_CONFIG["high"]["lora"]),
        f"Wan2.2 LoRA Low ({WAN22_CONFIG['low']['lora']})":   _model_file_exists(LORA_MODEL_DIR, WAN22_CONFIG["low"]["lora"]),
    }

    # ComfyUI node diagnostics (check keys only — avoids loading full object_info body)
    diag_nodes = {}
    try:
        obj_info = requests.get(f"{COMFY_URL}/object_info", timeout=8).json()
        for name in ["AIO_Preprocessor", "CannyEdgePreprocessor", "DepthAnythingV2Preprocessor",
                     "ControlNetApplyAdvanced", "StyleModelLoader", "StyleModelApply",
                     "CLIPVisionLoader", "CLIPVisionEncode", "InpaintModelConditioning",
                     "ImagePadForOutpaint", "FluxKontextImageScale",
                     "InstructPixToPixConditioning", "FluxKontextMultiReferenceLatentMethod",
                     "ReferenceLatent", "ConditioningZeroOut",
                     "FluxGuidance", "ModelSamplingFlux", "Flux2Scheduler", "EmptyFlux2LatentImage",
                     "ImageScaleToTotalPixels",
                     "KSampler", "KSamplerAdvanced", "SamplerCustomAdvanced", "CLIPLoader", "BasicGuider", "RandomNoise",
                     "ModelSamplingSD3", "UnetLoaderGGUF",
                     "WanImageToVideo", "WanFirstLastFrameToVideo", "CreateVideo", "SaveVideo",
                     "FaceDetailer", "WD14Tagger|pysssss"]:
            diag_nodes[name] = name in obj_info
    except Exception as e:
        diag_nodes = {"error": str(e)}

    return jsonify({
        "start_log": log_text,
        "jobs":      jobs,
        "runlog":    runlog,
        "diag": {"models": diag_models, "nodes": diag_nodes},
    })


@app.route("/api/runlog")
def api_runlog():
    return jsonify({"items": _read_run_log()})


# ── System stats (VRAM) ──────────────────────────────────────────
@app.route("/api/stats")
def stats():
    try:
        r = requests.get(f"{COMFY_URL}/system_stats", timeout=3).json()
        devs = r.get("devices", [])
        if devs:
            d = devs[0]
            total = d.get("vram_total", 0)
            free  = d.get("vram_free", 0)
            used  = max(total - free, 0)
            return jsonify({
                "vram_total": total, "vram_used": used, "vram_free": free,
                "vram_pct": round(used / total * 100, 1) if total else 0,
                "name": d.get("name", ""),
            })
    except Exception:
        pass
    return jsonify({"vram_total": 0, "vram_used": 0, "vram_free": 0, "vram_pct": 0})


# ── Image interrogation (prompt extraction) ──────────────────────
@app.route("/api/interrogate", methods=["POST"])
def interrogate():
    """Try to extract a prompt from an image via WD14 or BLIP custom nodes."""
    data = request.json or {}
    filename  = data.get("filename", "")
    subfolder = data.get("subfolder", "")
    img_type  = data.get("type", "output")
    if not filename:
        return jsonify({"error": "filename required"}), 400
    try:
        # Probe for the available interrogator node
        info = requests.get(f"{COMFY_URL}/object_info", timeout=5).json()
        if "WD14Tagger|pysssss" in info:
            class_type = "WD14Tagger|pysssss"
            input_key  = "image"
            extra = {"model": "wd-v1-4-moat-tagger-v2", "threshold": 0.35,
                     "character_threshold": 0.85, "replace_underscore": True,
                     "trailing_comma": False, "exclude_tags": ""}
        elif "BLIP_Loader" in info and "BLIP_Caption" in info:
            class_type = "BLIP_Caption"
            input_key  = "image"
            extra = {}
        else:
            return jsonify({"error": "WD14TaggerまたはBLIPカスタムノードが必要です"}), 400

        uploaded = _fetch_and_upload_image(filename, subfolder, img_type)
        wf = {
            "1": {"class_type": "LoadImage", "inputs": {"image": uploaded, "upload": "image"}},
            "2": {"class_type": class_type,  "inputs": {input_key: ["1", 0], **extra}},
            "3": {"class_type": "ShowText|pysssss", "inputs": {"text": ["2", 0]}},
        }
        pid, _ = _queue_workflow(wf)
        # Poll for result
        import time
        for _ in range(30):
            time.sleep(1)
            hist = requests.get(f"{COMFY_URL}/history/{pid}", timeout=5).json()
            if pid in hist:
                outs = hist[pid].get("outputs", {})
                for o in outs.values():
                    if "text" in o:
                        return jsonify({"text": " ".join(o["text"])})
                    if "tags" in o:
                        return jsonify({"text": ", ".join(o["tags"])})
                return jsonify({"error": "出力にテキストなし"}), 500
        return jsonify({"error": "timeout"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Background removal (rembg) ───────────────────────────────────
@app.route("/api/bg_remove", methods=["POST"])
def bg_remove():
    data = request.json or {}
    filename  = data.get("filename", "")
    subfolder = data.get("subfolder", "")
    img_type  = data.get("type", "output")
    if not filename:
        return jsonify({"error": "filename required"}), 400
    try:
        from rembg import remove
        params = {"filename": filename, "subfolder": subfolder, "type": img_type}
        r = requests.get(f"{COMFY_URL}/view", params=params, timeout=30)
        r.raise_for_status()
        output = remove(r.content)
        return Response(output, mimetype="image/png",
                       headers={"Content-Disposition": "inline; filename=bg_removed.png"})
    except ImportError:
        return jsonify({"error": "rembgパッケージが必要: pip install rembg"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Face detailer (FaceDetailer custom node) ─────────────────────
def build_face_fix_workflow(image_name, steps, seed, denoise=0.5):
    """Uses Impact Pack's FaceDetailer if present."""
    wf = {}
    wf.update(_build_model_nodes())
    wf["1"] = {"class_type": "LoadImage", "inputs": {"image": image_name, "upload": "image"}}
    wf["2"] = {"class_type": "UltralyticsDetectorProvider",
               "inputs": {"model_name": "bbox/face_yolov8m.pt"}}
    wf["6"]  = {"class_type": "CLIPTextEncode", "inputs": {"text": "detailed face, high quality", "clip": ["11", 0]}}
    wf["33"] = {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["11", 0]}}
    wf["3"] = {"class_type": "FaceDetailer",
               "inputs": {
                   "image": ["1", 0], "model": ["12", 0],
                   "clip": ["11", 0], "vae": ["10", 0],
                   "positive": ["6", 0], "negative": ["33", 0],
                   "bbox_detector": ["2", 0],
                   "guide_size": 384, "guide_size_for": True, "max_size": 1024,
                   "seed": seed, "steps": steps, "cfg": 1.0,
                   "sampler_name": "euler", "scheduler": "simple",
                   "denoise": denoise, "feather": 5,
                   "noise_mask": True, "force_inpaint": True,
                   "bbox_threshold": 0.5, "bbox_dilation": 10, "bbox_crop_factor": 3.0,
                   "sam_detection_hint": "center-1", "sam_dilation": 0, "sam_threshold": 0.93,
                   "sam_bbox_expansion": 0, "sam_mask_hint_threshold": 0.7,
                   "sam_mask_hint_use_negative": "False",
                   "drop_size": 10, "cycle": 1, "wildcard": "",
               }}
    wf["9"] = {"class_type": "SaveImage", "inputs": {"images": ["3", 0], "filename_prefix": "flux_facefix"}}
    return wf


@app.route("/api/face_fix", methods=["POST"])
def face_fix():
    data = request.json or {}
    filename  = data.get("filename", "")
    subfolder = data.get("subfolder", "")
    img_type  = data.get("type", "output")
    if not filename:
        return jsonify({"error": "filename required"}), 400
    try:
        info = requests.get(f"{COMFY_URL}/object_info", timeout=5).json()
        if "FaceDetailer" not in info:
            return jsonify({"error": "FaceDetailer (Impact Pack)が必要です"}), 400
        uploaded = _fetch_and_upload_image(filename, subfolder, img_type)
        seed = random.randint(0, 2**31 - 1)
        steps = int(data.get("steps", 20))
        wf = build_face_fix_workflow(uploaded, steps, seed)
        pid, cid = _queue_workflow(wf)
        return jsonify({"prompt_id": pid, "client_id": cid, "seed": seed})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── EXIF / PNG metadata ──────────────────────────────────────────
@app.route("/api/exif", methods=["POST"])
def exif():
    """Read PNG metadata from a ComfyUI image."""
    data = request.json or {}
    filename  = data.get("filename", "")
    subfolder = data.get("subfolder", "")
    img_type  = data.get("type", "output")
    if not filename:
        return jsonify({"error": "filename required"}), 400
    try:
        from PIL import Image
        params = {"filename": filename, "subfolder": subfolder, "type": img_type}
        r = requests.get(f"{COMFY_URL}/view", params=params, timeout=15)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content))
        meta = {}
        for k, v in (img.info or {}).items():
            try:
                meta[k] = str(v)[:5000]
            except Exception:
                pass
        # Try to parse ComfyUI's stored workflow / prompt JSON
        parsed = {}
        for key in ("prompt", "workflow"):
            if key in meta:
                try:
                    parsed[key] = json.loads(meta[key])
                except Exception:
                    pass
        return jsonify({"raw": meta, "parsed": parsed, "size": list(img.size)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Background removal via uploaded URL ──────────────────────────


# ── SNS resize ───────────────────────────────────────────────────
@app.route("/api/resize", methods=["POST"])
def resize_img():
    """Resize a ComfyUI image to a target preset and return as PNG."""
    data = request.json or {}
    filename  = data.get("filename", "")
    subfolder = data.get("subfolder", "")
    img_type  = data.get("type", "output")
    preset    = data.get("preset", "square_1080")
    if not filename:
        return jsonify({"error": "filename required"}), 400
    presets = {
        "square_1080":     (1080, 1080),
        "story_1080x1920": (1080, 1920),
        "twitter_1600":    (1600, 900),
        "ogp_1200x630":    (1200, 630),
        "youtube_1280":    (1280, 720),
    }
    if preset not in presets:
        return jsonify({"error": "unknown preset"}), 400
    try:
        from PIL import Image
        params = {"filename": filename, "subfolder": subfolder, "type": img_type}
        r = requests.get(f"{COMFY_URL}/view", params=params, timeout=15)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        tw, th = presets[preset]
        # cover-fit
        src_ratio = img.width / img.height
        tgt_ratio = tw / th
        if src_ratio > tgt_ratio:
            new_h = th
            new_w = int(th * src_ratio)
        else:
            new_w = tw
            new_h = int(tw / src_ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - tw) // 2
        top  = (new_h - th) // 2
        img = img.crop((left, top, left + tw, top + th))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return send_file(buf, mimetype="image/png",
                        as_attachment=True,
                        download_name=f"{preset}.png")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Batch export (ZIP) ───────────────────────────────────────────
@app.route("/api/export_zip", methods=["POST"])
def export_zip():
    """Take a list of {filename, subfolder, type} and return a ZIP."""
    data = request.json or {}
    items = data.get("items", [])
    if not items:
        return jsonify({"error": "items required"}), 400
    try:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            meta_lines = []
            for i, it in enumerate(items):
                params = {"filename": it["filename"], "subfolder": it.get("subfolder",""),
                         "type": it.get("type","output")}
                try:
                    r = requests.get(f"{COMFY_URL}/view", params=params, timeout=30)
                    r.raise_for_status()
                    name = it.get("filename") or f"image_{i}.png"
                    z.writestr(name, r.content)
                    if it.get("meta"):
                        meta_lines.append(f"{name}\n{json.dumps(it['meta'], ensure_ascii=False, indent=2)}\n")
                except Exception:
                    continue
            if meta_lines:
                z.writestr("metadata.txt", "\n---\n".join(meta_lines))
        buf.seek(0)
        return send_file(buf, mimetype="application/zip",
                        as_attachment=True, download_name="flux_export.zip")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Prompt suggestion (template-based) ───────────────────────────
SUGGEST_TEMPLATES = {
    "quality":   ["highly detailed", "8k", "ultra realistic", "masterpiece", "professional"],
    "lighting":  ["cinematic lighting", "golden hour", "soft natural light", "dramatic shadows", "studio lighting"],
    "camera":    ["shot on Canon EOS R5", "85mm portrait lens", "wide angle", "macro shot", "drone shot"],
    "mood":      ["serene", "moody", "ethereal", "vibrant", "mysterious"],
    "style":     ["photorealistic", "concept art", "oil painting", "watercolor", "anime style"],
    "negative":  ["blurry, low quality, distorted, watermark, text, jpeg artifacts"],
}


@app.route("/api/suggest", methods=["POST"])
def suggest():
    data = request.json or {}
    kind = data.get("kind", "quality")
    return jsonify({"suggestions": SUGGEST_TEMPLATES.get(kind, [])})


# ── Settings (server-side) ───────────────────────────────────────
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")


@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        data = request.json or {}
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                return jsonify(json.load(f))
    except Exception:
        pass
    return jsonify({})


# ── Keepalive / auto-shutdown ──────────────────────────────────
_last_ping = [time.time()]
_started_at = time.time()
_AUTO_CLOSE = os.environ.get("FLUX_AUTO_CLOSE", "0") == "1"
_SHUTDOWN_GRACE_SECONDS = 15


@app.route("/api/keepalive", methods=["POST"])
def keepalive():
    _last_ping[0] = time.time()
    return jsonify({"ok": True})


@app.route("/api/shutdown", methods=["POST"])
def shutdown():
    if _AUTO_CLOSE:
        # リモートアクセスモード: ローカルブラウザ以外のbeaconでは終了しない
        if FLASK_PASSWORD and request.remote_addr not in ("127.0.0.1", "::1"):
            return jsonify({"ok": True, "ignored": "remote"})
        if time.time() - _started_at < _SHUTDOWN_GRACE_SECONDS:
            return jsonify({"ok": True, "ignored": "startup_grace"})
        threading.Thread(target=lambda: (time.sleep(0.5), os._exit(0)), daemon=True).start()
    return jsonify({"ok": True})


def _keepalive_monitor():
    time.sleep(60)  # ComfyUI ロード中はブラウザが ping を送れないので余裕を持たせる
    while True:
        time.sleep(5)
        # リモートアクセスモード: パスワードが設定されている場合は自動終了しない
        if not FLASK_PASSWORD and time.time() - _last_ping[0] > 30:
            os._exit(0)



@app.route("/api/config")
def api_config():
    return jsonify({
        "comfyui_dir": _COMFYUI_DIR,
        "comfyui_python": _COMFYUI_PYTHON,
        "flask_port": _FLASK_PORT,
        "config_path": _CONFIG_PATH,
    })


@app.route("/api/config/update", methods=["POST"])
def api_config_update():
    data = request.json or {}
    cfg = _load_comfyui_config()
    for key in ("comfyui_dir", "comfyui_python", "flask_port"):
        if key in data:
            cfg[key] = data[key]
    try:
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return jsonify({"ok": True, "message": "設定を保存しました。再起動で反映されます。"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    _gallery_conn().close()          # テーブル作成
    _scan_gallery_outputs()          # 既存ファイルをDBへ
    print("=" * 52)
    print("  FLUX UI  →  http://localhost:5000")
    print(f"  ComfyUI  →  {COMFY_URL}")
    print(f"  モデル   →  {MODEL_CONFIG['unet']}")
    print(f"  自動終了 →  {'有効' if _AUTO_CLOSE else '無効'}")
    print("=" * 52)
    if _AUTO_CLOSE:
        threading.Thread(target=_keepalive_monitor, daemon=True).start()
    app.run(host="127.0.0.1", port=_FLASK_PORT, debug=False)
