import runpod
import os
import websocket
import base64
import json
import uuid
import logging
import urllib.request
import urllib.error
import binascii
import subprocess
import time
import shutil
import threading
from pathlib import Path
from PIL import Image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

server_address = os.getenv("SERVER_ADDRESS", "127.0.0.1")
client_id = str(uuid.uuid4())

COMFY_INPUT_DIR = os.getenv("COMFY_INPUT_DIR", "/ComfyUI/input")
WORKFLOW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workflow")
WORKFLOW_T2V_PATH = os.path.join(WORKFLOW_DIR, "minimax_h3_t2v_api.json")
WORKFLOW_I2V_PATH = os.path.join(WORKFLOW_DIR, "minimax_h3_i2v_api.json")
WORKFLOW_R2V_PATHS = {
    1: os.path.join(WORKFLOW_DIR, "minimax_h3_r2v_1ref_api.json"),
    2: os.path.join(WORKFLOW_DIR, "minimax_h3_r2v_2ref_api.json"),
    3: os.path.join(WORKFLOW_DIR, "minimax_h3_r2v_3ref_api.json"),
    4: os.path.join(WORKFLOW_DIR, "minimax_h3_r2v_4ref_api.json"),
}

# Shared node IDs (T2V + I2V official API exports)
NODE_SAVE = "92"
NODE_RES = "115"
NODE_LOAD_IMAGE = "114"  # I2V only
NODE_IMAGE_SCALE = "119"  # I2V only — scale to megapixels, keep aspect
NODE_IMAGE_SIZE = "120"  # I2V only — width/height from scaled image
NODE_VAE_VIDEO = "105:11"
NODE_VAE_AUDIO = "105:24"
NODE_SAMPLER_SELECT = "105:17"
NODE_SCHEDULER = "105:9"
NODE_UNET = "105:6"
NODE_CLIP = "105:13"
NODE_NOISE = "105:15"
NODE_CREATE_VIDEO = "105:91"
NODE_H3 = "105:104"
NODE_DURATION = "105:111"
NODE_MATH_LENGTH = "105:107"
NODE_TURBO_LORA = "105:121"
NODE_POWER_LORA = "105:121"  # Power Lora Loader (rgthree): turbo + realism + extras
NODE_TURBO_MODEL_SWITCH = "105:122"
NODE_TURBO_STEPS_SWITCH = "105:123"
NODE_STEPS_NORMAL = "105:124"
NODE_STEPS_TURBO = "105:125"
NODE_TURBO_MODE = "105:126"
NODE_GUIDER = "105:16"

# R2V API export node IDs (shared across 1–4 ref graphs)
R2V_NODE_RES = "115"
R2V_NODE_DURATION = "132"
R2V_NODE_LENGTH_MATH = "131"
R2V_NODE_PROMPT = "138"
R2V_NODE_PROMPT_PREFIX = "160"
R2V_NODE_UNET = "161"
R2V_NODE_POWER_LORA = "162"  # Power Lora Loader (rgthree): turbo + realism + extras
R2V_NODE_TURBO_LORA = "162"  # alias — turbo is lora_1 on the power loader
R2V_NODE_CLIP = "163"
R2V_NODE_VAE_VIDEO = "164"
R2V_NODE_VAE_AUDIO = "165"
R2V_NODE_NOISE = "171"
R2V_NODE_SCHEDULER = "170"
R2V_NODE_SAMPLER = "169"
R2V_NODE_H3 = "178"
R2V_NODE_OUTPUT = "176"
R2V_LOAD_IMAGE_NODES = ["148", "149", "155", "156"]  # ref 0..3

DEFAULT_PROMPT = (
    "Realistic live-action cinematic look, shallow depth of field, film grain, "
    "natural motion, high quality, no text, no watermark."
)
DEFAULT_TURBO_LORA = "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"
DEFAULT_R2V_TURBO_LORA = "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"
# Hub realism (runtime download); Comfy alias keeps (r34l1sm) trigger compatibility
DEFAULT_REALISM_LORA_REPO = "fal/MiniMax-H3-Realism-People-LoRA"
DEFAULT_REALISM_LORA_HUB_FILE = "h3-realism-people-t2v-i2v-r2v.safetensors"
DEFAULT_REALISM_LORA = "h3-realism-people-t2v-i2v-r2v(r34l1sm).safetensors"
DEFAULT_R2V_PROMPT_PREFIX = "r34l1sm , create realism style cinematic video."
DEFAULT_R2V_UNET = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
FPS = 24

# Network-volume LoRA roots (only used when input JSON overrides / extra loras)
COMFY_LORAS_DIR = os.getenv("COMFY_LORAS_DIR", "/ComfyUI/models/loras")
LORA_SEARCH_DIRS = [
    "/runpod-volume/loras",
    "/runpod-volume/models/loras",
    COMFY_LORAS_DIR,
    "/workspace/loras",
]
# Optional operator default Hub repo when job entry omits repo (empty = require explicit repo)
HF_LORA_REPO = os.getenv("HF_LORA_REPO", "").strip()
# XET/Hub download hang kill only (generation uses COMFY_JOB_TIMEOUT_SEC separately)
LORA_DOWNLOAD_TIMEOUT = int(os.getenv("LORA_DOWNLOAD_TIMEOUT", "300"))
_FETCH_MODEL_SH = os.getenv(
    "FETCH_MODEL_SH",
    "/usr/local/bin/fetch_model.sh",
)
_RUNTIME_LORA_READY = set()  # basenames already ensured this process
_RUNTIME_LORA_LOCKS = {}  # basename -> threading.Lock
_RUNTIME_LORA_LOCKS_GUARD = threading.Lock()
_HF_TOKEN_ENV_KEYS = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "BFL_READ_TOKEN",
    "RUNPOD_HF_TOKEN",
)


# ResolutionSelector COMBO options (must match ComfyUI node exactly).
OFFICIAL_ASPECTS = (
    "1:1 (Square)",
    "2:3 (Portrait Photo)",
    "3:2 (Photo)",
    "3:4 (Portrait Standard)",
    "4:3 (Standard)",
    "9:16 (Portrait Widescreen)",
    "16:9 (Widescreen)",
    "21:9 (Ultrawide)",
)

# Short / legacy labels → official COMBO strings
_ASPECT_ALIASES = {
    "1:1": "1:1 (Square)",
    "1:1 (square)": "1:1 (Square)",
    "square": "1:1 (Square)",
    "2:3": "2:3 (Portrait Photo)",
    "2:3 (portrait)": "2:3 (Portrait Photo)",
    "2:3 (portrait photo)": "2:3 (Portrait Photo)",
    "3:2": "3:2 (Photo)",
    "3:2 (photo)": "3:2 (Photo)",
    "3:4": "3:4 (Portrait Standard)",
    "3:4 (portrait)": "3:4 (Portrait Standard)",
    "3:4 (portrait standard)": "3:4 (Portrait Standard)",
    "4:3": "4:3 (Standard)",
    "4:3 (standard)": "4:3 (Standard)",
    "9:16": "9:16 (Portrait Widescreen)",
    "9:16 (portrait)": "9:16 (Portrait Widescreen)",
    "9:16 (portrait widescreen)": "9:16 (Portrait Widescreen)",
    "16:9": "16:9 (Widescreen)",
    "16:9 (widescreen)": "16:9 (Widescreen)",
    "widescreen": "16:9 (Widescreen)",
    "21:9": "21:9 (Ultrawide)",
    "21:9 (ultrawide)": "21:9 (Ultrawide)",
    "ultrawide": "21:9 (Ultrawide)",
}


def normalize_aspect_ratio(value, default="16:9 (Widescreen)"):
    """Map short/legacy aspect labels to ResolutionSelector COMBO options."""
    if value is None:
        return default
    s = str(value).strip()
    if not s:
        return default
    if s in OFFICIAL_ASPECTS:
        return s
    mapped = _ASPECT_ALIASES.get(s.lower())
    if mapped:
        return mapped
    # Ratio-only prefix match, e.g. "9:16 something"
    ratio = s.split()[0] if s else ""
    if ":" in ratio:
        mapped = _ASPECT_ALIASES.get(ratio.lower())
        if mapped:
            return mapped
    logger.warning("Unknown aspect_ratio %r — using %r", value, default)
    return default


def align_frame_count(n: int) -> int:
    """Snap to MiniMax H3 17k+5 grid (same as ComfyUI nodes_minimax_h3.align_frame_count)."""
    n = max(5, int(n))
    while n % 17 != 5:
        n += 1
    return n


def frames_from_duration(duration: float, fps: float = FPS) -> int:
    """Match sample ComfyMathExpression: max(5, round(duration*fps)) then align."""
    return align_frame_count(max(5, int(round(float(duration) * float(fps)))))


def to_nearest_multiple(value, multiple=32, minimum=None):
    """Snap dimension to nearest valid latent multiple (MiniMax H3 requires 32)."""
    multiple = max(1, int(multiple))
    v = int(round(float(value) / multiple) * multiple)
    min_v = multiple if minimum is None else max(multiple, int(minimum))
    return max(min_v, v)


def read_image_size(path):
    with Image.open(path) as im:
        return im.size  # (width, height)


def compute_size_from_megapixels(src_w, src_h, megapixels, multiple=32):
    """Scale to target megapixels, preserve aspect, snap both sides to `multiple`."""
    target = max(1e-6, float(megapixels)) * 1_000_000.0
    scale = (target / max(1.0, float(src_w) * float(src_h))) ** 0.5
    return (
        to_nearest_multiple(src_w * scale, multiple),
        to_nearest_multiple(src_h * scale, multiple),
    )


def resize_image_cover(src_path, dest_path, width, height):
    """Center-crop cover resize so first_frame exactly matches sampler W×H."""
    width, height = int(width), int(height)
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    with Image.open(src_path) as im:
        im = im.convert("RGB")
        sw, sh = im.size
        scale = max(width / max(1, sw), height / max(1, sh))
        nw = max(width, int(round(sw * scale)))
        nh = max(height, int(round(sh * scale)))
        im = im.resize((nw, nh), Image.Resampling.LANCZOS)
        left = max(0, (nw - width) // 2)
        top = max(0, (nh - height) // 2)
        im = im.crop((left, top, left + width, top + height))
        im.save(dest_path, format="PNG")
    logger.info("🖼️ Auto-resized %s → %sx%s (%s)", src_path, width, height, dest_path)
    return dest_path


def resolve_i2v_output_size(job_input, image_path, megapixels, multiple):
    """
    Resolve final (width, height) for MiniMax H3 I2V.
    - Explicit width+height → snap each to multiple (fixes 853→864 etc.)
    - Else size from input image aspect × megapixels, snapped to multiple
    """
    src_w, src_h = read_image_size(image_path)
    raw_w = job_input.get("width")
    raw_h = job_input.get("height")

    if raw_w is not None and raw_h is not None:
        width = to_nearest_multiple(raw_w, multiple)
        height = to_nearest_multiple(raw_h, multiple)
        if int(raw_w) != width or int(raw_h) != height:
            logger.info(
                "📐 Snapped explicit size %sx%s → %sx%s (multiple=%s)",
                raw_w,
                raw_h,
                width,
                height,
                multiple,
            )
        return width, height, "explicit_snapped"

    if raw_w is not None or raw_h is not None:
        # One side given: keep source aspect, snap both
        aspect = src_w / max(1, src_h)
        if raw_w is not None:
            width = to_nearest_multiple(raw_w, multiple)
            height = to_nearest_multiple(width / aspect, multiple)
        else:
            height = to_nearest_multiple(raw_h, multiple)
            width = to_nearest_multiple(height * aspect, multiple)
        logger.info(
            "📐 Partial size from %s → %sx%s (src=%sx%s, multiple=%s)",
            f"w={raw_w}" if raw_w is not None else f"h={raw_h}",
            width,
            height,
            src_w,
            src_h,
            multiple,
        )
        return width, height, "partial_snapped"

    width, height = compute_size_from_megapixels(src_w, src_h, megapixels, multiple)
    logger.info(
        "📐 Auto size from image %sx%s → %sx%s (%.3f MP, multiple=%s)",
        src_w,
        src_h,
        width,
        height,
        megapixels,
        multiple,
    )
    return width, height, "auto_megapixels"


def queue_prompt(prompt):
    url = f"http://{server_address}:8188/prompt"
    logger.info("Queueing prompt (%d nodes) → %s", len(prompt), url)
    data = json.dumps({"prompt": prompt, "client_id": client_id}).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        logger.error("ComfyUI /prompt HTTP %s: %s", e.code, body[:2000])
        raise RuntimeError(f"ComfyUI rejected workflow (HTTP {e.code}): {body[:800]}") from e


def get_history(prompt_id):
    url = f"http://{server_address}:8188/history/{prompt_id}"
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read())


def _comfy_alive():
    try:
        urllib.request.urlopen(f"http://{server_address}:8188/", timeout=5)
        return True
    except Exception:
        return False


def _history_error_message(history):
    chunks = []
    status = history.get("status") or {}
    for msg in status.get("messages") or []:
        try:
            chunks.append(json.dumps(msg))
        except Exception:
            chunks.append(str(msg))
    blob = "\n".join(chunks)
    low = blob.lower()
    if any(x in low for x in ("out of memory", "oom", "cuda error", "cudamemalloc")):
        return (
            "GPU out of memory during MiniMax H3 generation. "
            "Try shorter duration, lower megapixels, or a 48GB+ GPU."
        )
    if status.get("status_str") == "error" or "exception" in low:
        return f"ComfyUI prompt failed: {blob[:800] or status}"
    return None


def _collect_videos_from_history(history):
    output_videos = {}
    for node_id, node_output in (history.get("outputs") or {}).items():
        videos_output = []
        for key in ("gifs", "videos", "images"):
            if key not in node_output:
                continue
            for item in node_output[key]:
                filepath = item.get("fullpath")
                if not filepath or not os.path.exists(filepath):
                    filename = item.get("filename")
                    if filename:
                        filepath = os.path.join(
                            "/ComfyUI/output", item.get("subfolder", ""), filename
                        )
                if not filepath or not os.path.exists(filepath):
                    continue
                ext = Path(filepath).suffix.lower()
                if key == "images" and ext not in (".mp4", ".webm", ".mkv", ".mov", ".avi"):
                    continue
                with open(filepath, "rb") as f:
                    videos_output.append(base64.b64encode(f.read()).decode("utf-8"))
                logger.info("✅ Loaded output media: %s", filepath)
        if videos_output:
            output_videos[node_id] = videos_output
    return output_videos


def _prompt_finished(history):
    if not history:
        return False
    if history.get("outputs"):
        return True
    status = history.get("status") or {}
    if status.get("completed") is True:
        return True
    if status.get("status_str") in ("success", "error"):
        return True
    return False


def get_videos(prompt, timeout_sec=None):
    timeout_sec = int(timeout_sec or os.getenv("COMFY_JOB_TIMEOUT_SEC", "2400"))
    prompt_id = queue_prompt(prompt)["prompt_id"]
    logger.info("Queued prompt_id=%s (timeout=%ss)", prompt_id, timeout_sec)

    ws = None
    deadline = time.time() + timeout_sec
    last_hist_check = 0.0
    poll_every = float(os.getenv("COMFY_HISTORY_POLL_SEC", "5"))

    try:
        while time.time() < deadline:
            now = time.time()
            if now - last_hist_check >= poll_every:
                last_hist_check = now
                try:
                    hist_all = get_history(prompt_id)
                except Exception as e:
                    if not _comfy_alive():
                        raise RuntimeError(
                            "ComfyUI died mid-job (connection lost). Often GPU OOM."
                        ) from e
                    logger.warning("history poll failed: %s", e)
                    hist_all = {}
                if prompt_id in hist_all:
                    history = hist_all[prompt_id]
                    if _prompt_finished(history):
                        err = _history_error_message(history)
                        videos = _collect_videos_from_history(history)
                        if videos:
                            return videos
                        if err:
                            raise RuntimeError(err)
                        if (history.get("status") or {}).get("status_str") == "error":
                            raise RuntimeError(err or "ComfyUI prompt failed with no output")

            try:
                if ws is None:
                    ws = connect_ws()
                    try:
                        ws.settimeout(poll_every)
                    except Exception:
                        pass
                out = ws.recv()
                if isinstance(out, str):
                    message = json.loads(out)
                    if message.get("type") == "executing":
                        data = message.get("data") or {}
                        if data.get("node") is None and data.get("prompt_id") == prompt_id:
                            history = get_history(prompt_id).get(prompt_id) or {}
                            err = _history_error_message(history)
                            videos = _collect_videos_from_history(history)
                            if videos:
                                return videos
                            if err:
                                raise RuntimeError(err)
                            raise RuntimeError("ComfyUI finished but no output video was produced.")
                    elif message.get("type") == "execution_error":
                        data = message.get("data") or {}
                        raise RuntimeError(f"ComfyUI execution_error: {json.dumps(data)[:800]}")
            except websocket.WebSocketTimeoutException:
                continue
            except (
                websocket.WebSocketConnectionClosedException,
                ConnectionError,
                OSError,
            ) as e:
                logger.warning("WebSocket lost (%s) — history poll fallback", e)
                try:
                    if ws is not None:
                        ws.close()
                except Exception:
                    pass
                ws = None
                if not _comfy_alive():
                    raise RuntimeError("ComfyUI connection lost mid-job (server down).") from e
                time.sleep(2)
                continue

        raise RuntimeError(f"Timed out waiting for ComfyUI after {timeout_sec}s (prompt_id={prompt_id})")
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass


_MODEL_PATH_KEYS = (
    "lora_name",
    "unet_name",
    "clip_name",
    "vae_name",
    "ckpt_name",
    "model_name",
)

# Roots checked only when input JSON overrides a model name
_OVERRIDE_MODEL_ROOTS = {
    "vae_name": [
        "/runpod-volume/vae",
        "/runpod-volume/models/vae",
        "/ComfyUI/models/vae",
    ],
    "unet_name": [
        "/runpod-volume/diffusion_models",
        "/runpod-volume/models",
        "/runpod-volume/models/diffusion_models",
        "/ComfyUI/models/diffusion_models",
        "/ComfyUI/models/unet",
    ],
    "clip_name": [
        "/runpod-volume/text_encoders",
        "/runpod-volume/models/text_encoders",
        "/ComfyUI/models/text_encoders",
        "/ComfyUI/models/clip",
    ],
    "lora_name": LORA_SEARCH_DIRS,
}


def _flat_model_name(requested: str) -> str:
    """Workflows bake flat filenames; strip nested Windows/Linux prefixes."""
    name = (requested or "").strip().replace("\\", "/")
    if not name:
        return name
    return os.path.basename(name)


def resolve_override_model_name(input_key: str, requested: str) -> str:
    """
    Resolve a model name from input JSON.
    Prefer Network Volume, then baked /ComfyUI/models. Returns flat relative name.
    """
    requested = _flat_model_name(requested)
    if not requested:
        return requested

    roots = [d for d in (_OVERRIDE_MODEL_ROOTS.get(input_key) or []) if d and os.path.isdir(d)]
    for root in roots:
        full = os.path.join(root, requested)
        if os.path.isfile(full):
            # relative to this root (may include subdirs if user passed nested after flatten — rare)
            rel = os.path.relpath(full, root).replace("\\", "/")
            logger.info("📦 Override [%s] from %s → %s", input_key, root, rel)
            return rel
        # allow nested volume layouts: **/requested
        for dirpath, _dirs, files in os.walk(root):
            if requested in files:
                rel = os.path.relpath(os.path.join(dirpath, requested), root).replace("\\", "/")
                logger.info("📦 Override [%s] found %s under %s", input_key, rel, root)
                return rel

    logger.warning("⚠️ Override model not on volume/disk yet [%s]: %s (using name as-is)", input_key, requested)
    return requested


def _normalize_workflow_paths(prompt):
    """Slash-normalize and flatten baked model filenames (no volume scan)."""
    for node in prompt.values():
        inputs = node.get("inputs") or {}
        for key in _MODEL_PATH_KEYS:
            val = inputs.get(key)
            if isinstance(val, str) and val.strip():
                inputs[key] = _flat_model_name(val)
    return prompt


def load_workflow(workflow_path):
    with open(workflow_path, "r", encoding="utf-8") as f:
        return _normalize_workflow_paths(json.load(f))


def download_file_from_url(url, output_path):
    result = subprocess.run(
        ["wget", "-O", output_path, "--no-verbose", url],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise Exception(f"URL download failed: {result.stderr}")
    return output_path


def save_base64_to_file(base64_data, temp_dir, output_filename):
    if isinstance(base64_data, str) and "," in base64_data and base64_data.strip().startswith("data:"):
        base64_data = base64_data.split(",", 1)[1]
    try:
        decoded = base64.b64decode(base64_data)
    except (binascii.Error, ValueError) as e:
        raise Exception(f"Base64 decode failed: {e}")
    os.makedirs(temp_dir, exist_ok=True)
    path = os.path.abspath(os.path.join(temp_dir, output_filename))
    with open(path, "wb") as f:
        f.write(decoded)
    return path


def process_input(input_data, temp_dir, output_filename, input_type):
    if input_type == "path":
        return input_data
    if input_type == "url":
        os.makedirs(temp_dir, exist_ok=True)
        path = os.path.abspath(os.path.join(temp_dir, output_filename))
        return download_file_from_url(input_data, path)
    if input_type == "base64":
        return save_base64_to_file(input_data, temp_dir, output_filename)
    raise Exception(f"Unsupported input type: {input_type}")


def resolve_media_input(job_input, prefixes, temp_dir, default_filename):
    for prefix in prefixes:
        for kind, key in (
            ("path", f"{prefix}_path"),
            ("url", f"{prefix}_url"),
            ("base64", f"{prefix}_base64"),
        ):
            if key in job_input and job_input[key]:
                return process_input(job_input[key], temp_dir, default_filename, kind)
        # Bare aliases: image / image_url / image_base64 / image_path
        if prefix == "image":
            if job_input.get("image_path"):
                return process_input(job_input["image_path"], temp_dir, default_filename, "path")
            if job_input.get("image_url"):
                return process_input(job_input["image_url"], temp_dir, default_filename, "url")
            if job_input.get("image_base64"):
                return process_input(job_input["image_base64"], temp_dir, default_filename, "base64")
            if job_input.get("image"):
                val = job_input["image"]
                if isinstance(val, str) and (val.startswith("http://") or val.startswith("https://")):
                    return process_input(val, temp_dir, default_filename, "url")
                if isinstance(val, str) and len(val) > 100:
                    return process_input(val, temp_dir, default_filename, "base64")
                if isinstance(val, str):
                    return process_input(val, temp_dir, default_filename, "path")
    return None


def stage_into_comfy_input(src_path, filename):
    os.makedirs(COMFY_INPUT_DIR, exist_ok=True)
    dest = os.path.join(COMFY_INPUT_DIR, filename)
    shutil.copy2(src_path, dest)
    logger.info("✅ Staged: %s", dest)
    return filename


def _lora_candidates(name: str):
    """Generate plausible relative LoRA path variants for ComfyUI / network volume."""
    raw = (name or "").strip().replace("\\", "/")
    if not raw:
        return []
    base = os.path.basename(raw)
    stem = base
    out = []
    for cand in (
        raw,
        base,
        f"minimax-h3/{base}",
        f"minimax_h3/{base}",
        f"minimax-h3/{stem}",
    ):
        if cand and cand not in out:
            out.append(cand)
        # Comfy on Windows-style exports sometimes needs backslashes
        alt = cand.replace("/", "\\")
        if alt not in out:
            out.append(alt)
    return out


def _lora_basename(name: str) -> str:
    return os.path.basename((name or "").strip().replace("\\", "/"))


def _find_lora_on_disk(requested: str, default=None):
    """
    Search LORA_SEARCH_DIRS for requested LoRA.
    Returns relative path for ComfyUI, or None if not found.
    """
    requested = (requested or "").strip()
    if not requested:
        requested = default or ""
    if not requested:
        return None

    candidates = _lora_candidates(requested)
    if default:
        for c in _lora_candidates(default):
            if c not in candidates:
                candidates.append(c)

    search_dirs = [d for d in LORA_SEARCH_DIRS if d and os.path.isdir(d)]
    for rel in candidates:
        rel_norm = rel.replace("\\", "/")
        for root in search_dirs:
            full = os.path.join(root, rel_norm)
            if os.path.isfile(full) and os.path.getsize(full) > 0:
                return rel_norm
            base = os.path.basename(rel_norm)
            for dirpath, _dirs, files in os.walk(root):
                if base in files:
                    full_found = os.path.join(dirpath, base)
                    if os.path.getsize(full_found) > 0:
                        return os.path.relpath(full_found, root).replace("\\", "/")
    return None


def _lora_lock_for(basename: str) -> threading.Lock:
    with _RUNTIME_LORA_LOCKS_GUARD:
        lock = _RUNTIME_LORA_LOCKS.get(basename)
        if lock is None:
            lock = threading.Lock()
            _RUNTIME_LORA_LOCKS[basename] = lock
        return lock


def _resolve_fetch_model_sh() -> str:
    candidates = [
        _FETCH_MODEL_SH,
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "fetch_model.sh"),
        "/usr/local/bin/fetch_model.sh",
    ]
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
        if path and os.path.isfile(path):
            return path
    return candidates[0]


def _mask_hf_token(token: str) -> str:
    t = (token or "").strip()
    if not t:
        return "(none)"
    if len(t) <= 8:
        return "hf_…****"
    return f"{t[:3]}…{t[-4:]}"


def _job_hf_token(job_input) -> str:
    """Job-level Hugging Face token (never logs the raw value)."""
    if not isinstance(job_input, dict):
        return ""
    for key in (
        "hf_token",
        "huggingface_token",
        "HUGGING_FACE_HUB_TOKEN",
        "huggingface_hub_token",
    ):
        val = job_input.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _split_hf_repo_path(path: str):
    """
    Split 'org/repo/subdir/file.safetensors' into (repo_id, hub_path).
    Hub repo ids are always namespace/name (two segments).
    """
    raw = (path or "").strip().replace("\\", "/").lstrip("/")
    if not raw:
        return "", ""
    parts = [p for p in raw.split("/") if p]
    if len(parts) < 3:
        return "", raw
    repo_id = f"{parts[0]}/{parts[1]}"
    hub_path = "/".join(parts[2:])
    return repo_id, hub_path


def _parse_hf_download_url(url: str):
    """
    Parse a Hugging Face file URL into (repo_id, hub_path).

    Supports:
      https://huggingface.co/org/repo/resolve/main/file.safetensors
      https://huggingface.co/org/repo/resolve/main/subdir/file.safetensors
      https://huggingface.co/org/repo/blob/main/file.safetensors
      https://hf.co/org/repo/resolve/main/file.safetensors
    """
    raw = (url or "").strip()
    if not raw:
        return "", ""
    lower = raw.lower()
    if "huggingface.co/" not in lower and "hf.co/" not in lower:
        return "", ""

    path = raw.split("?", 1)[0].split("#", 1)[0]
    for marker in ("huggingface.co/", "hf.co/"):
        idx = path.lower().find(marker)
        if idx >= 0:
            path = path[idx + len(marker) :]
            break
    path = path.strip("/")
    parts = [p for p in path.split("/") if p]
    if len(parts) < 3:
        return "", ""

    repo_id = f"{parts[0]}/{parts[1]}"
    rest = parts[2:]
    if rest and rest[0] in ("resolve", "blob", "raw"):
        rest = rest[1:]
        if rest:
            if rest[0] == "refs" and len(rest) >= 3:
                rest = rest[3:]
            else:
                rest = rest[1:]
    hub_path = "/".join(rest)
    if not hub_path:
        return "", ""
    return repo_id, hub_path


def parse_hf_lora_ref(entry, default_token: str = None):
    """
    Normalize a LoRA entry into {repo, name, hub_path, strength, token}.

    Preferred simple form (download link):
      "https://huggingface.co/org/repo/resolve/main/file.safetensors"
      {"url": "https://huggingface.co/...", "strength": 0.8}

    Also accepts:
      {"repo": "org/repo", "name": "file.safetensors", "strength": 0.8}
      {"hf": "org/repo/subdir/file.safetensors", "strength": 1.0, "hf_token": "..."}
      "org/repo/file.safetensors"
      "file.safetensors"  (local / HF_LORA_REPO fallback)
    """
    default_token = (default_token or "").strip() or None
    strength = 1.0
    token = default_token
    repo = ""
    hub_path = ""
    name = ""

    if isinstance(entry, str):
        text = entry.strip()
        repo, hub_path = _parse_hf_download_url(text)
        if not repo:
            repo, hub_path = _split_hf_repo_path(text)
        if repo and hub_path:
            name = _lora_basename(hub_path)
        else:
            name = _lora_basename(text) or text
            hub_path = text.replace("\\", "/") if text else ""
    elif isinstance(entry, dict):
        strength = float(entry.get("strength", entry.get("strength_model", 1.0)))
        entry_token = (
            entry.get("hf_token")
            or entry.get("huggingface_token")
            or entry.get("HUGGING_FACE_HUB_TOKEN")
            or entry.get("token")
        )
        if isinstance(entry_token, str) and entry_token.strip():
            token = entry_token.strip()

        url = (
            entry.get("url")
            or entry.get("link")
            or entry.get("download_url")
            or entry.get("hf_url")
            or entry.get("lora_url")
        )
        if url:
            repo, hub_path = _parse_hf_download_url(str(url))
            name = _lora_basename(hub_path) if hub_path else ""
        else:
            hf_path = entry.get("hf") or entry.get("huggingface") or entry.get("path")
            if hf_path and not entry.get("repo"):
                repo, hub_path = _parse_hf_download_url(str(hf_path))
                if not repo:
                    repo, hub_path = _split_hf_repo_path(str(hf_path))
                name = _lora_basename(hub_path) if hub_path else ""
            else:
                repo = str(entry.get("repo") or "").strip()
                raw_name = entry.get("name") or entry.get("file") or entry.get("lora") or ""
                raw_name = str(raw_name).strip().replace("\\", "/")
                if raw_name:
                    url_repo, url_hub = _parse_hf_download_url(raw_name)
                    if url_repo and url_hub:
                        if not repo:
                            repo = url_repo
                        hub_path = url_hub
                        name = _lora_basename(url_hub)
                    else:
                        hub_path = raw_name
                        name = _lora_basename(raw_name)
                elif hf_path:
                    hub_path = str(hf_path).strip().replace("\\", "/").lstrip("/")
                    name = _lora_basename(hub_path)
    else:
        return None

    if not name:
        return None

    return {
        "repo": repo or None,
        "name": name,
        "hub_path": hub_path or name,
        "strength": strength,
        "token": token,
    }


def _ensure_realism_alias_symlink(hub_basename: str):
    """Link Hub realism file to the (r34l1sm) Comfy alias after runtime download."""
    hub_basename = _lora_basename(hub_basename)
    if not hub_basename:
        return
    src = os.path.join(COMFY_LORAS_DIR, hub_basename)
    if not (os.path.isfile(src) and os.path.getsize(src) > 0):
        return
    alias = DEFAULT_REALISM_LORA
    if hub_basename == alias:
        return
    dst = os.path.join(COMFY_LORAS_DIR, alias)
    try:
        if os.path.islink(dst) or os.path.exists(dst):
            if os.path.islink(dst) or (
                os.path.isfile(dst) and os.path.getsize(dst) > 0
            ):
                return
            os.remove(dst)
        os.symlink(hub_basename, dst)
        logger.info("🔗 Realism alias: %s → %s", alias, hub_basename)
    except OSError as e:
        logger.warning("Could not create realism alias symlink %s: %s", alias, e)


def _runtime_fetch_env(token: str = None) -> dict:
    """
    Env for runtime Hub downloads: optional job/entry token + parallel hf_xet.
    Does not reuse the Dockerfile bake token for user LoRAs — only `token` if set.
    """
    env = os.environ.copy()
    for key in _HF_TOKEN_ENV_KEYS:
        env.pop(key, None)

    explicit = (token or "").strip()
    if explicit:
        env["HF_TOKEN"] = explicit
        env["HUGGING_FACE_HUB_TOKEN"] = explicit
        env["BFL_READ_TOKEN"] = explicit

    env.setdefault("HF_HOME", "/tmp/hf_home")
    env.setdefault("HUGGINGFACE_HUB_CACHE", f"{env['HF_HOME']}/hub")
    env.setdefault("HF_HUB_CACHE", env["HUGGINGFACE_HUB_CACHE"])
    env["HF_HUB_DISABLE_XET"] = env.get("HF_HUB_DISABLE_XET", "0")
    env["HF_XET_HIGH_PERFORMANCE"] = env.get("HF_XET_HIGH_PERFORMANCE", "1")
    env["HF_HUB_ENABLE_HF_TRANSFER"] = env.get("HF_HUB_ENABLE_HF_TRANSFER", "0")
    env["HF_HUB_DISABLE_TELEMETRY"] = "1"
    env["HF_PROGRESS_STEP_PCT"] = env.get("HF_PROGRESS_STEP_PCT", "5")
    # Runtime LoRA only: 5-min XET hang kill (NOT used for Docker multi-GB bakes)
    env["HF_DOWNLOAD_HANG_TIMEOUT_SEC"] = str(LORA_DOWNLOAD_TIMEOUT)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _run_fetch_model_streaming(
    fetch_sh: str,
    repo_id: str,
    basename: str,
    dest: str,
    token: str = None,
) -> int:
    """
    Run fetch_model.sh and stream stdout/stderr to logs in real time
    (so download percent progress appears in RunPod worker logs).
    """
    env = _runtime_fetch_env(token=token)
    logger.info(
        "⬇ Runtime LoRA download (hf_xet parallel): repo=%s file=%s → %s (timeout=%ss, token=%s)",
        repo_id,
        basename,
        dest,
        LORA_DOWNLOAD_TIMEOUT,
        _mask_hf_token(token),
    )
    proc = subprocess.Popen(
        [fetch_sh, repo_id, basename, dest],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    deadline = time.time() + LORA_DOWNLOAD_TIMEOUT
    try:
        assert proc.stdout is not None
        while True:
            if time.time() > deadline:
                proc.kill()
                try:
                    proc.wait(timeout=10)
                except Exception:
                    pass
                raise RuntimeError(
                    f"LoRA download timed out after {LORA_DOWNLOAD_TIMEOUT}s: {basename}"
                )
            line = proc.stdout.readline()
            if line:
                logger.info("[fetch_model] %s", line.rstrip())
                continue
            if proc.poll() is not None:
                break
            time.sleep(0.05)
        for line in proc.stdout:
            logger.info("[fetch_model] %s", line.rstrip())
        return int(proc.returncode or 0)
    except RuntimeError:
        raise
    except Exception:
        if proc.poll() is None:
            proc.kill()
        raise


def ensure_lora_on_disk(
    name: str,
    repo: str = None,
    token: str = None,
    hub_filename: str = None,
) -> str:
    """
    Ensure a LoRA file exists under Comfy/volume for this worker's lifetime.
    If missing, download once via fetch_model.sh (authenticated hf_xet + % progress)
    using job/entry token only (never the Dockerfile bake token).
    Returns relative basename for ComfyUI.
    """
    basename = _lora_basename(name)
    if not basename:
        raise RuntimeError("LoRA name is empty")

    hub_path = (hub_filename or name or "").strip().replace("\\", "/") or basename
    # If hub_path looks like org/repo/file, strip to in-repo path
    maybe_repo, maybe_hub = _split_hf_repo_path(hub_path)
    if maybe_repo and maybe_hub:
        if not (repo or "").strip():
            repo = maybe_repo
        hub_path = maybe_hub
        basename = _lora_basename(hub_path) or basename

    found = _find_lora_on_disk(basename)
    if found:
        _RUNTIME_LORA_READY.add(basename)
        return found

    if basename in _RUNTIME_LORA_READY:
        dest_ready = os.path.join(COMFY_LORAS_DIR, basename)
        if os.path.isfile(dest_ready) and os.path.getsize(dest_ready) > 0:
            return basename

    repo_id = (repo or "").strip() or HF_LORA_REPO
    dest = os.path.join(COMFY_LORAS_DIR, basename)
    lock = _lora_lock_for(basename)

    with lock:
        found = _find_lora_on_disk(basename)
        if found:
            _RUNTIME_LORA_READY.add(basename)
            logger.info("📦 LoRA cache hit (after lock): %s → %s", basename, found)
            return found

        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            _RUNTIME_LORA_READY.add(basename)
            logger.info("📦 LoRA already on disk: %s", dest)
            return basename

        if not repo_id:
            raise RuntimeError(
                f"LoRA not on disk and no Hugging Face repo specified: {basename}. "
                "Pass repo+name, hf: 'org/repo/file.safetensors', or set HF_LORA_REPO."
            )

        os.makedirs(COMFY_LORAS_DIR, exist_ok=True)
        fetch_sh = _resolve_fetch_model_sh()
        if not os.path.isfile(fetch_sh):
            raise RuntimeError(
                f"LoRA download failed: fetch_model.sh not found ({fetch_sh}). "
                f"Missing LoRA: {basename}"
            )

        explicit_token = (token or "").strip() or None
        try:
            rc = _run_fetch_model_streaming(
                fetch_sh, repo_id, hub_path, dest, token=explicit_token
            )
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"LoRA download failed: {basename}: {e}") from e

        if rc != 0 or not (os.path.isfile(dest) and os.path.getsize(dest) > 0):
            token_hint = (
                f"token={_mask_hf_token(explicit_token)}"
                if explicit_token
                else "no hf_token — public Hub only; private repos need job/entry hf_token"
            )
            raise RuntimeError(
                f"LoRA download failed: {basename} from {repo_id} "
                f"(exit={rc}, {token_hint}). "
                "Check the file exists in the repo and that hf_token is valid for private repos."
            )

        _RUNTIME_LORA_READY.add(basename)
        logger.info(
            "✅ Runtime LoRA ready: %s (%s bytes) — cached until worker dies",
            dest,
            os.path.getsize(dest),
        )
        return basename


def resolve_lora_name(
    requested: str,
    default=None,
    download=False,
    repo=None,
    token=None,
    hub_filename=None,
) -> str:
    """
    Resolve a LoRA filename against local + network-volume loras roots.
    When download=True and the file is missing, fetch once into COMFY_LORAS_DIR
    (worker-lifetime cache via ensure_lora_on_disk).
    """
    requested = (requested or "").strip()
    if not requested:
        requested = default or ""
    if not requested:
        return requested

    found = _find_lora_on_disk(requested, default=default)
    if found:
        logger.info("📦 LoRA resolved: %s → %s", requested, found)
        return found

    if download:
        basename = _lora_basename(requested) or _lora_basename(default or "")
        ensured = ensure_lora_on_disk(
            basename,
            repo=repo,
            token=token,
            hub_filename=hub_filename or requested,
        )
        found = _find_lora_on_disk(ensured) or ensured
        if found:
            logger.info("📦 LoRA resolved after download: %s → %s", requested, found)
            return found
        raise RuntimeError(f"LoRA still missing after download: {requested}")

    # Prefer forward-slash relative form for Comfy (baked/entrypoint defaults)
    candidates = _lora_candidates(requested)
    if default:
        for c in _lora_candidates(default):
            if c not in candidates:
                candidates.append(c)
    fallback = candidates[0].replace("\\", "/") if candidates else requested
    logger.warning("⚠️ LoRA not found on disk yet, using: %s", fallback)
    return fallback


def _parse_lora_entries(job_input):
    """
    Normalize optional dynamic LoRAs from job input.

    Preferred simple form:
      lora_url: "https://huggingface.co/org/repo/resolve/main/file.safetensors"
      lora_urls: ["https://...", ...]
      loras: ["https://...", {"url": "...", "strength": 0.8}]

    Also accepts repo/name, hf path strings, style_lora_name, etc.
    """
    job_token = _job_hf_token(job_input)
    entries = []

    # Simple single / multi URL fields
    for key in ("lora_url", "lora_link", "hf_lora_url"):
        raw = job_input.get(key)
        if not raw:
            continue
        items = raw if isinstance(raw, (list, tuple)) else [raw]
        for item in items:
            parsed = parse_hf_lora_ref(item, default_token=job_token)
            if parsed:
                # Allow job-level strength for single URL form
                if key == "lora_url" and "lora_strength" in job_input:
                    parsed["strength"] = float(job_input.get("lora_strength", 1.0))
                entries.append(parsed)

    raw_urls = job_input.get("lora_urls") or job_input.get("hf_lora_urls")
    if raw_urls:
        if isinstance(raw_urls, dict):
            raw_urls = [raw_urls]
        if isinstance(raw_urls, (list, tuple)):
            for item in raw_urls:
                parsed = parse_hf_lora_ref(item, default_token=job_token)
                if parsed:
                    entries.append(parsed)

    for key in ("loras", "extra_loras", "additional_loras"):
        raw = job_input.get(key)
        if not raw:
            continue
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, (list, tuple)):
            continue
        for item in raw:
            parsed = parse_hf_lora_ref(item, default_token=job_token)
            if parsed:
                entries.append(parsed)

    # Single optional aesthetic LoRA (not the turbo one)
    single = job_input.get("style_lora_name") or job_input.get("aesthetic_lora_name")
    if single:
        entry = {
            "name": str(single),
            "strength": float(
                job_input.get("style_lora_strength", job_input.get("aesthetic_lora_strength", 1.0))
            ),
        }
        repo = job_input.get("style_lora_repo") or job_input.get("aesthetic_lora_repo")
        if repo:
            entry["repo"] = str(repo).strip()
        parsed = parse_hf_lora_ref(entry, default_token=job_token)
        if parsed:
            entries.append(parsed)
    return entries


def inject_lora_chain(prompt, upstream_node_id, lora_specs, id_prefix="dyn_lora"):
    """
    Stack LoraLoaderModelOnly nodes after `upstream_node_id`.
    Each spec may set download (default True) and optional repo/token.
    Returns (final_tip_id, created_node_ids).
    """
    tip = upstream_node_id
    created = []
    for i, spec in enumerate(lora_specs):
        name = resolve_lora_name(
            spec["name"],
            download=bool(spec.get("download", True)),
            repo=spec.get("repo"),
            token=spec.get("token"),
            hub_filename=spec.get("hub_path"),
        )
        if not name:
            continue
        nid = f"{id_prefix}_{i}"
        prompt[nid] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "lora_name": name,
                "strength_model": float(spec.get("strength", 1.0)),
                "model": [tip, 0],
            },
            "_meta": {"title": f"Dynamic LoRA {i}: {os.path.basename(name)}"},
        }
        created.append(nid)
        tip = nid
        logger.info(
            "🧩 Dynamic LoRA[%s] %s @ %s (after %s)",
            i,
            name,
            spec.get("strength", 1.0),
            upstream_node_id,
        )
    return tip, created


def _is_custom_lora_name(requested, default_name) -> bool:
    """True when job overrides a baked default LoRA with a different filename."""
    req = _lora_basename(requested or "")
    dflt = _lora_basename(default_name or "")
    return bool(req) and bool(dflt) and req != dflt


def _clear_power_lora_slots(inputs):
    """Remove lora_N keys from Power Lora Loader (rgthree) inputs."""
    for key in list(inputs.keys()):
        if key.lower().startswith("lora_"):
            del inputs[key]


def _set_power_lora_slot(inputs, slot, lora_name, strength, enabled=True):
    on = bool(enabled) and float(strength) != 0.0 and bool(lora_name)
    inputs[f"lora_{slot}"] = {
        "on": on,
        "lora": lora_name,
        "strength": float(strength),
    }


def apply_r2v_power_lora(prompt, job_input, turbo_mode):
    """
    Configure R2V node 162 (Power Lora Loader rgthree):
      lora_1 = turbo (baked), lora_2 = realism (runtime if on), lora_3+ = extras
    """
    node_id = R2V_NODE_POWER_LORA
    if node_id not in prompt:
        logger.warning("R2V Power LoRA node %s missing from workflow", node_id)
        return

    node = prompt[node_id]
    if node.get("class_type") != "Power Lora Loader (rgthree)":
        logger.warning(
            "R2V node %s is %s, expected Power Lora Loader (rgthree)",
            node_id,
            node.get("class_type"),
        )
        return

    inputs = node.setdefault("inputs", {})
    inputs.setdefault("PowerLoraLoaderHeaderWidget", {"type": "PowerLoraLoaderHeaderWidget"})
    if "model" not in inputs:
        inputs["model"] = [R2V_NODE_UNET, 0]

    _clear_power_lora_slots(inputs)

    for nid in list(prompt.keys()):
        if str(nid).startswith("r2v_extra_lora_"):
            del prompt[nid]

    sage_node = "167"
    if sage_node in prompt:
        prompt[sage_node]["inputs"]["model"] = [node_id, 0]

    job_token = _job_hf_token(job_input)

    turbo_requested = (
        job_input.get("turbo_lora_name")
        or job_input.get("lightning_lora_name")
        or job_input.get("r2v_turbo_lora_name")
        or DEFAULT_R2V_TURBO_LORA
    )
    turbo_repo = job_input.get("turbo_lora_repo") or job_input.get("lightning_lora_repo")
    turbo_download = bool(turbo_repo) or _is_custom_lora_name(
        turbo_requested, DEFAULT_R2V_TURBO_LORA
    )
    turbo_name = resolve_lora_name(
        turbo_requested,
        default=DEFAULT_R2V_TURBO_LORA,
        download=turbo_download,
        repo=turbo_repo,
        token=job_token if turbo_download else None,
    )
    turbo_strength = job_input.get(
        "turbo_model_strength",
        job_input.get("turbo_lora_strength", job_input.get("lightning_lora_strength", 1.0)),
    )
    if not turbo_mode:
        turbo_strength = 0.0
    _set_power_lora_slot(inputs, 1, turbo_name, turbo_strength, enabled=turbo_mode)

    realism_enabled = _coerce_bool(
        job_input.get("realism_lora", job_input.get("realism_lora_enabled", True)),
        default=True,
    )
    realism_custom = (
        job_input.get("realism_lora_name")
        or job_input.get("realism_lora_file")
    )
    realism_repo = (
        job_input.get("realism_lora_repo")
        or (DEFAULT_REALISM_LORA_REPO if not realism_custom else None)
    )
    if realism_custom:
        realism_requested = str(realism_custom).strip()
        realism_hub = realism_requested
        realism_comfy = _lora_basename(realism_requested)
    else:
        realism_requested = DEFAULT_REALISM_LORA_HUB_FILE
        realism_hub = DEFAULT_REALISM_LORA_HUB_FILE
        realism_comfy = DEFAULT_REALISM_LORA

    if realism_enabled:
        # Prefer alias / hub file already on disk; otherwise always download
        found = _find_lora_on_disk(realism_comfy) or _find_lora_on_disk(
            DEFAULT_REALISM_LORA_HUB_FILE
        )
        if found:
            if not realism_custom and _lora_basename(found) == DEFAULT_REALISM_LORA_HUB_FILE:
                _ensure_realism_alias_symlink(found)
                realism_name = (
                    _find_lora_on_disk(DEFAULT_REALISM_LORA) or found
                )
            else:
                realism_name = found
        else:
            hub_base = ensure_lora_on_disk(
                realism_requested,
                repo=realism_repo or DEFAULT_REALISM_LORA_REPO,
                token=job_token,
                hub_filename=realism_hub,
            )
            if not realism_custom:
                _ensure_realism_alias_symlink(hub_base)
                realism_name = (
                    _find_lora_on_disk(DEFAULT_REALISM_LORA)
                    or _find_lora_on_disk(hub_base)
                    or hub_base
                )
            else:
                realism_name = _find_lora_on_disk(hub_base) or hub_base
    else:
        realism_name = realism_comfy or DEFAULT_REALISM_LORA

    realism_strength = float(
        job_input.get("realism_lora_strength", job_input.get("realism_strength", 1.0))
    )
    if not realism_enabled:
        realism_strength = 0.0
    _set_power_lora_slot(inputs, 2, realism_name, realism_strength, enabled=realism_enabled)

    extras = _parse_lora_entries(job_input)
    slot = 3
    applied_extras = 0
    for spec in extras:
        name = resolve_lora_name(
            spec["name"],
            download=True,
            repo=spec.get("repo"),
            token=spec.get("token"),
            hub_filename=spec.get("hub_path"),
        )
        if not name:
            continue
        _set_power_lora_slot(inputs, slot, name, spec.get("strength", 1.0), enabled=True)
        slot += 1
        applied_extras += 1

    logger.info(
        "🧩 R2V Power LoRA: turbo=%s@%s realism=%s@%s extras=%s",
        turbo_name,
        inputs["lora_1"]["strength"],
        realism_name,
        inputs["lora_2"]["strength"],
        applied_extras,
    )


def apply_ti2v_power_lora(prompt, job_input, turbo_mode):
    """
    Configure T2V/I2V node 105:121 (Power Lora Loader rgthree):
      lora_1 = fl2v turbo (baked), lora_2 = realism (runtime if on), lora_3+ = extras
    Model switch (105:122) always takes this node so realism/extras apply with turbo on or off.
    """
    node_id = NODE_POWER_LORA
    if node_id not in prompt:
        logger.warning("T2V/I2V Power LoRA node %s missing from workflow", node_id)
        return

    node = prompt[node_id]
    if node.get("class_type") != "Power Lora Loader (rgthree)":
        logger.warning(
            "T2V/I2V node %s is %s, expected Power Lora Loader (rgthree)",
            node_id,
            node.get("class_type"),
        )
        return

    inputs = node.setdefault("inputs", {})
    inputs.setdefault("PowerLoraLoaderHeaderWidget", {"type": "PowerLoraLoaderHeaderWidget"})
    if "model" not in inputs:
        inputs["model"] = [NODE_UNET, 0]

    _clear_power_lora_slots(inputs)

    # Drop any legacy dynamic LoraLoaderModelOnly chain nodes
    for nid in list(prompt.keys()):
        if str(nid).startswith("t2v_lora_"):
            del prompt[nid]

    # Always route model switch through Power Lora (turbo = strength, not bypass)
    if NODE_TURBO_MODEL_SWITCH in prompt:
        sw = prompt[NODE_TURBO_MODEL_SWITCH].setdefault("inputs", {})
        sw["on_true"] = [node_id, 0]
        sw["on_false"] = [node_id, 0]

    job_token = _job_hf_token(job_input)

    turbo_requested = (
        job_input.get("turbo_lora_name")
        or job_input.get("lightning_lora_name")
        or job_input.get("lora_name")
        or DEFAULT_TURBO_LORA
    )
    turbo_repo = job_input.get("turbo_lora_repo") or job_input.get("lightning_lora_repo")
    turbo_download = bool(turbo_repo) or _is_custom_lora_name(
        turbo_requested, DEFAULT_TURBO_LORA
    )
    turbo_name = resolve_lora_name(
        turbo_requested,
        default=DEFAULT_TURBO_LORA,
        download=turbo_download,
        repo=turbo_repo,
        token=job_token if turbo_download else None,
    )
    turbo_strength = job_input.get(
        "turbo_model_strength",
        job_input.get("turbo_lora_strength", job_input.get("lightning_lora_strength", 1.0)),
    )
    if not turbo_mode:
        turbo_strength = 0.0
    _set_power_lora_slot(inputs, 1, turbo_name, turbo_strength, enabled=turbo_mode)

    realism_enabled = _coerce_bool(
        job_input.get("realism_lora", job_input.get("realism_lora_enabled", True)),
        default=True,
    )
    realism_custom = (
        job_input.get("realism_lora_name")
        or job_input.get("realism_lora_file")
    )
    realism_repo = (
        job_input.get("realism_lora_repo")
        or (DEFAULT_REALISM_LORA_REPO if not realism_custom else None)
    )
    if realism_custom:
        realism_requested = str(realism_custom).strip()
        realism_hub = realism_requested
        realism_comfy = _lora_basename(realism_requested)
    else:
        realism_requested = DEFAULT_REALISM_LORA_HUB_FILE
        realism_hub = DEFAULT_REALISM_LORA_HUB_FILE
        realism_comfy = DEFAULT_REALISM_LORA

    if realism_enabled:
        found = _find_lora_on_disk(realism_comfy) or _find_lora_on_disk(
            DEFAULT_REALISM_LORA_HUB_FILE
        )
        if found:
            if not realism_custom and _lora_basename(found) == DEFAULT_REALISM_LORA_HUB_FILE:
                _ensure_realism_alias_symlink(found)
                realism_name = (
                    _find_lora_on_disk(DEFAULT_REALISM_LORA) or found
                )
            else:
                realism_name = found
        else:
            hub_base = ensure_lora_on_disk(
                realism_requested,
                repo=realism_repo or DEFAULT_REALISM_LORA_REPO,
                token=job_token,
                hub_filename=realism_hub,
            )
            if not realism_custom:
                _ensure_realism_alias_symlink(hub_base)
                realism_name = (
                    _find_lora_on_disk(DEFAULT_REALISM_LORA)
                    or _find_lora_on_disk(hub_base)
                    or hub_base
                )
            else:
                realism_name = _find_lora_on_disk(hub_base) or hub_base
    else:
        realism_name = realism_comfy or DEFAULT_REALISM_LORA

    realism_strength = float(
        job_input.get("realism_lora_strength", job_input.get("realism_strength", 1.0))
    )
    if not realism_enabled:
        realism_strength = 0.0
    _set_power_lora_slot(inputs, 2, realism_name, realism_strength, enabled=realism_enabled)

    extras = _parse_lora_entries(job_input)
    slot = 3
    applied_extras = 0
    for spec in extras:
        name = resolve_lora_name(
            spec["name"],
            download=True,
            repo=spec.get("repo"),
            token=spec.get("token"),
            hub_filename=spec.get("hub_path"),
        )
        if not name:
            continue
        _set_power_lora_slot(inputs, slot, name, spec.get("strength", 1.0), enabled=True)
        slot += 1
        applied_extras += 1

    logger.info(
        "🧩 T2V/I2V Power LoRA: turbo=%s@%s realism=%s@%s extras=%s",
        turbo_name,
        inputs["lora_1"]["strength"],
        realism_name,
        inputs["lora_2"]["strength"],
        applied_extras,
    )


def retarget_model_inputs(prompt, old_node_id, new_node_id, skip_nodes=None):
    """Point model inputs that referenced old_node_id at new_node_id."""
    skip = set(skip_nodes or [])
    for nid, node in prompt.items():
        if nid in skip or nid == new_node_id:
            continue
        inputs = node.get("inputs") or {}
        for key, val in list(inputs.items()):
            if isinstance(val, list) and len(val) >= 1 and val[0] == old_node_id:
                if key in ("model", "on_true", "on_false") or key.endswith("model"):
                    inputs[key] = [new_node_id, val[1] if len(val) > 1 else 0]


def apply_realism_and_dynamic_loras(prompt, job_input, mode, turbo_mode=True):
    """
    Apply realism + dynamic LoRAs.
    - R2V: handled by apply_r2v_power_lora() (Power Lora Loader on node 162)
    - T2V/I2V: Power Lora Loader on node 105:121 (turbo + realism + extras)
    """
    if mode == "r2v":
        return R2V_NODE_POWER_LORA

    apply_ti2v_power_lora(prompt, job_input, turbo_mode)
    return NODE_POWER_LORA


def collect_reference_images(job_input, temp_dir):
    """
    Collect up to 4 R2V reference images from job input.
    Supports:
      - reference_images / ref_images / refs / images: list of url|base64|path|dict
      - reference_image / reference_image_2..4
      - ref_image / ref_image_0..3 / ref_image_url / ref_image_base64
      - image_1..image_4
    """
    collected = []

    def _add_media(value, idx):
        if value is None or value == "":
            return
        if isinstance(value, dict):
            for kind, key in (
                ("url", "url"),
                ("url", "image_url"),
                ("base64", "base64"),
                ("base64", "image_base64"),
                ("path", "path"),
                ("path", "image_path"),
                ("path", "image"),
            ):
                if value.get(key):
                    path = process_input(
                        value[key], temp_dir, f"ref_{idx}.png", kind
                    )
                    collected.append(path)
                    return
            return
        if not isinstance(value, str):
            return
        val = value.strip()
        if val.startswith("http://") or val.startswith("https://"):
            collected.append(process_input(val, temp_dir, f"ref_{idx}.png", "url"))
        elif val.startswith("data:") or len(val) > 256:
            collected.append(process_input(val, temp_dir, f"ref_{idx}.png", "base64"))
        else:
            collected.append(process_input(val, temp_dir, f"ref_{idx}.png", "path"))

    # Lists first (preserve order)
    for list_key in ("reference_images", "ref_images", "refs", "images"):
        raw = job_input.get(list_key)
        if isinstance(raw, (list, tuple)):
            for item in raw:
                if len(collected) >= 4:
                    break
                _add_media(item, len(collected))

    # Named singles
    named_keys = []
    for i in range(0, 4):
        named_keys.extend(
            [
                f"reference_image_{i}",
                f"ref_image_{i}",
                f"image_{i + 1}",
                f"reference_image_{i + 1}" if i > 0 else "reference_image",
                f"ref_image_{i + 1}" if i > 0 else "ref_image",
            ]
        )
        named_keys.extend(
            [
                f"reference_image_{i}_url",
                f"ref_image_{i}_url",
                f"reference_image_{i}_base64",
                f"ref_image_{i}_base64",
                f"reference_image_{i}_path",
                f"ref_image_{i}_path",
            ]
        )
    # Also bare aliases used by clients
    for key in (
        "reference_image",
        "reference_image_url",
        "reference_image_base64",
        "reference_image_path",
        "ref_image",
        "ref_image_url",
        "ref_image_base64",
        "ref_image_path",
        "reference_image_2",
        "reference_image_3",
        "reference_image_4",
        "ref_image_2",
        "ref_image_3",
        "ref_image_4",
        "image_1",
        "image_2",
        "image_3",
        "image_4",
    ):
        if key not in named_keys:
            named_keys.append(key)

    seen_paths = set(collected)
    for key in named_keys:
        if len(collected) >= 4:
            break
        if not job_input.get(key):
            continue
        before = len(collected)
        _add_media(job_input[key], len(collected))
        # dedupe if same path added twice
        if len(collected) > before and collected[-1] in seen_paths:
            collected.pop()
        elif len(collected) > before:
            seen_paths.add(collected[-1])

    return collected[:4]


def wait_for_comfy_http(max_attempts=180):
    http_url = f"http://{server_address}:8188/"
    for attempt in range(max_attempts):
        try:
            urllib.request.urlopen(http_url, timeout=5)
            logger.info("HTTP ready (attempt %s)", attempt + 1)
            return
        except Exception as e:
            logger.warning("HTTP not ready (%s/%s): %s", attempt + 1, max_attempts, e)
            if attempt == max_attempts - 1:
                raise Exception("Cannot connect to ComfyUI server")
            time.sleep(1)


def connect_ws(max_attempts=36):
    ws_url = f"ws://{server_address}:8188/ws?clientId={client_id}"
    ws = websocket.WebSocket()
    for attempt in range(max_attempts):
        try:
            ws.connect(ws_url)
            logger.info("WebSocket connected (attempt %s)", attempt + 1)
            return ws
        except Exception as e:
            logger.warning("WebSocket failed (%s/%s): %s", attempt + 1, max_attempts, e)
            if attempt == max_attempts - 1:
                raise Exception("WebSocket connection timed out")
            time.sleep(5)
    raise Exception("WebSocket connection failed")


def wire_optional_frame(prompt, job_input, prefixes, node_id, input_name, temp_dir, filename):
    path = resolve_media_input(job_input, prefixes, temp_dir, filename)
    if not path:
        return False
    staged = stage_into_comfy_input(path, f"{uuid.uuid4().hex}_{filename}")
    prompt[node_id] = {
        "inputs": {"image": staged},
        "class_type": "LoadImage",
        "_meta": {"title": f"Load {input_name}"},
    }
    prompt[NODE_H3]["inputs"][input_name] = [node_id, 0]
    return True


def _coerce_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in ("1", "true", "yes", "on", "y"):
        return True
    if s in ("0", "false", "no", "off", "n"):
        return False
    return default


def _has_reference_hints(job_input) -> bool:
    if any(
        job_input.get(k)
        for k in (
            "reference_images",
            "ref_images",
            "refs",
            "reference_image",
            "reference_image_url",
            "reference_image_base64",
            "ref_image",
            "ref_image_url",
            "ref_image_base64",
            "reference_image_2",
            "ref_image_2",
            "image_1",
        )
    ):
        return True
    for k in ("reference_images", "ref_images", "refs", "images"):
        v = job_input.get(k)
        if isinstance(v, (list, tuple)) and len(v) > 0:
            return True
    return False


def detect_mode(job_input):
    """Return 'i2v', 't2v', or 'r2v'."""
    explicit = (
        job_input.get("mode")
        or job_input.get("workflow")
        or job_input.get("task")
        or ""
    )
    explicit = str(explicit).strip().lower()
    if explicit in (
        "r2v",
        "ref2v",
        "reference_to_video",
        "reference2video",
        "ref_to_video",
        "mv2v",
    ):
        return "r2v"
    if explicit in ("i2v", "image_to_video", "img2vid", "image2video"):
        return "i2v"
    if explicit in ("t2v", "text_to_video", "txt2vid", "text2video"):
        return "t2v"

    # Auto-detect R2V from reference image fields (don't download yet)
    if _has_reference_hints(job_input):
        return "r2v"

    if "text_to_video" in job_input:
        return "t2v" if _coerce_bool(job_input.get("text_to_video"), False) else "i2v"

    has_image = any(
        job_input.get(k)
        for k in (
            "image",
            "image_url",
            "image_base64",
            "image_path",
            "first_frame_url",
            "first_frame_base64",
            "first_frame_path",
            "start_image_url",
            "start_image_base64",
            "start_image_path",
        )
    )
    return "i2v" if has_image else "t2v"


def apply_turbo_mode(prompt, job_input, mode="t2v"):
    """Toggle turbo LoRA. T2V/I2V: steps switch + Power Lora slot 1; R2V: steps on 170."""
    turbo_mode = _coerce_bool(
        job_input.get(
            "turbo_mode",
            job_input.get("turbo", job_input.get("turbo_lora", True)),
        ),
        default=True,
    )

    if mode == "r2v":
        if "steps" in job_input:
            prompt[R2V_NODE_SCHEDULER]["inputs"]["steps"] = int(job_input["steps"])
        elif turbo_mode:
            prompt[R2V_NODE_SCHEDULER]["inputs"]["steps"] = int(job_input.get("turbo_steps", 8))
        else:
            prompt[R2V_NODE_SCHEDULER]["inputs"]["steps"] = int(job_input.get("normal_steps", 20))

        logger.info(
            "⚡ R2V turbo_mode=%s steps=%s",
            turbo_mode,
            prompt[R2V_NODE_SCHEDULER]["inputs"]["steps"],
        )
        return turbo_mode

    # T2V / I2V — boolean drives steps switch; LoRA stack configured by apply_ti2v_power_lora
    prompt[NODE_TURBO_MODE]["inputs"]["value"] = turbo_mode

    if "turbo_steps" in job_input:
        prompt[NODE_STEPS_TURBO]["inputs"]["value"] = int(job_input["turbo_steps"])
    if "normal_steps" in job_input:
        prompt[NODE_STEPS_NORMAL]["inputs"]["value"] = int(job_input["normal_steps"])

    if "steps" in job_input:
        steps_val = int(job_input["steps"])
        if turbo_mode:
            prompt[NODE_STEPS_TURBO]["inputs"]["value"] = steps_val
        else:
            prompt[NODE_STEPS_NORMAL]["inputs"]["value"] = steps_val

    logger.info(
        "⚡ turbo_mode=%s steps(turbo/normal)=%s/%s",
        turbo_mode,
        prompt[NODE_STEPS_TURBO]["inputs"]["value"],
        prompt[NODE_STEPS_NORMAL]["inputs"]["value"],
    )
    return turbo_mode


def handler(job):
    job_input = job.get("input", {}) or {}
    logger.info("Received job keys: %s", list(job_input.keys()))
    task_id = f"task_{uuid.uuid4()}"

    mode = detect_mode(job_input)

    ref_paths = []
    if mode == "r2v":
        ref_paths = collect_reference_images(job_input, task_id)
        if not ref_paths:
            return {
                "error": (
                    "R2V mode requires 1–4 reference images "
                    "(reference_images / ref_image_url / reference_image_base64 / …)."
                )
            }
        n_refs = len(ref_paths)
        workflow_path = WORKFLOW_R2V_PATHS[n_refs]
    else:
        workflow_path = WORKFLOW_I2V_PATH if mode == "i2v" else WORKFLOW_T2V_PATH

    if not os.path.exists(workflow_path):
        return {"error": f"Workflow not found: {workflow_path}"}

    logger.info(
        "Mode=%s workflow=%s refs=%s",
        mode,
        os.path.basename(workflow_path),
        len(ref_paths),
    )
    prompt = load_workflow(workflow_path)

    text = (
        job_input.get("prompt")
        or job_input.get("text")
        or job_input.get("positive")
        or DEFAULT_PROMPT
    )

    megapixels = float(job_input.get("megapixels", 0.8 if mode == "r2v" else 0.4))
    multiple = int(job_input.get("multiple", 32))
    if multiple < 8:
        multiple = 32

    use_auto_image_size = False
    resolved_width = None
    resolved_height = None
    size_mode = None
    fps = float(job_input.get("fps", job_input.get("frame_rate", FPS)))
    duration = float(job_input.get("duration", 5))
    length = None

    if mode == "r2v":
        # User prompt goes into PrimitiveStringMultiline; prefix stays on StringConcatenate
        prompt[R2V_NODE_PROMPT]["inputs"]["value"] = str(text)
        prefix = job_input.get("prompt_prefix", job_input.get("realism_prefix", DEFAULT_R2V_PROMPT_PREFIX))
        if prefix is not None:
            prompt[R2V_NODE_PROMPT_PREFIX]["inputs"]["string_a"] = str(prefix)

        aspect = normalize_aspect_ratio(
            job_input.get("aspect_ratio"), default="16:9 (Widescreen)"
        )
        prompt[R2V_NODE_RES]["inputs"]["aspect_ratio"] = aspect
        prompt[R2V_NODE_RES]["inputs"]["megapixels"] = megapixels
        prompt[R2V_NODE_RES]["inputs"]["multiple"] = multiple

        if "width" in job_input and "height" in job_input:
            resolved_width = to_nearest_multiple(job_input["width"], multiple)
            resolved_height = to_nearest_multiple(job_input["height"], multiple)
            prompt[R2V_NODE_H3]["inputs"]["width"] = resolved_width
            prompt[R2V_NODE_H3]["inputs"]["height"] = resolved_height
            size_mode = "explicit_snapped"
        else:
            prompt[R2V_NODE_H3]["inputs"]["width"] = [R2V_NODE_RES, 0]
            prompt[R2V_NODE_H3]["inputs"]["height"] = [R2V_NODE_RES, 1]
            size_mode = "resolution_selector"

        prompt[R2V_NODE_DURATION]["inputs"]["value"] = duration
        prompt[R2V_NODE_OUTPUT]["inputs"]["frame_rate"] = fps
        # Ensure VHS writes a collectible file (API exports often leave save_output=false)
        prompt[R2V_NODE_OUTPUT]["inputs"]["save_output"] = True

        if "length" in job_input or "frames" in job_input:
            length = align_frame_count(int(job_input.get("length", job_input.get("frames"))))
            prompt[R2V_NODE_H3]["inputs"]["length"] = length
        else:
            length = frames_from_duration(duration, fps)
            # Keep duration→frames math in sync when fps != 24
            if abs(fps - 24.0) > 1e-6:
                prompt[R2V_NODE_H3]["inputs"]["length"] = length

        if "ref_image_size" in job_input:
            prompt[R2V_NODE_H3]["inputs"]["ref_image_size"] = str(job_input["ref_image_size"])

        # Stage reference images into LoadImage nodes 148/149/155/156
        for i, src in enumerate(ref_paths):
            node_id = R2V_LOAD_IMAGE_NODES[i]
            staged = stage_into_comfy_input(src, f"{uuid.uuid4().hex}_ref_{i}.png")
            prompt[node_id]["inputs"]["image"] = staged
            prompt[R2V_NODE_H3]["inputs"][f"ref_images.ref_image_{i}"] = [node_id, 0]

        turbo_mode = apply_turbo_mode(prompt, job_input, mode="r2v")
        try:
            apply_r2v_power_lora(prompt, job_input, turbo_mode)
        except RuntimeError as e:
            logger.exception("R2V LoRA setup failed")
            return {"error": str(e)}

        if "seed" in job_input:
            prompt[R2V_NODE_NOISE]["inputs"]["noise_seed"] = int(job_input["seed"])
        if "denoise" in job_input:
            prompt[R2V_NODE_SCHEDULER]["inputs"]["denoise"] = float(job_input["denoise"])
        if "scheduler" in job_input:
            prompt[R2V_NODE_SCHEDULER]["inputs"]["scheduler"] = str(job_input["scheduler"])
        if "sampler_name" in job_input:
            prompt[R2V_NODE_SAMPLER]["inputs"]["sampler_name"] = str(job_input["sampler_name"])

        if job_input.get("unet_name"):
            prompt[R2V_NODE_UNET]["inputs"]["unet_name"] = resolve_override_model_name(
                "unet_name", str(job_input["unet_name"])
            )
        if job_input.get("clip_name"):
            prompt[R2V_NODE_CLIP]["inputs"]["clip_name"] = resolve_override_model_name(
                "clip_name", str(job_input["clip_name"])
            )
        if job_input.get("vae_name"):
            prompt[R2V_NODE_VAE_VIDEO]["inputs"]["vae_name"] = resolve_override_model_name(
                "vae_name", str(job_input["vae_name"])
            )
        if job_input.get("audio_vae_name"):
            prompt[R2V_NODE_VAE_AUDIO]["inputs"]["vae_name"] = resolve_override_model_name(
                "vae_name", str(job_input["audio_vae_name"])
            )

        save_node = R2V_NODE_OUTPUT
    else:
        # ── T2V / I2V ──────────────────────────────────────────────
        prompt[NODE_H3]["inputs"]["prompt"] = str(text)

        if mode == "t2v":
            aspect = normalize_aspect_ratio(
                job_input.get("aspect_ratio"), default="16:9 (Widescreen)"
            )
            prompt[NODE_RES]["inputs"]["aspect_ratio"] = aspect
            prompt[NODE_RES]["inputs"]["megapixels"] = megapixels
            prompt[NODE_RES]["inputs"]["multiple"] = multiple
            if "width" in job_input and "height" in job_input:
                resolved_width = to_nearest_multiple(job_input["width"], multiple)
                resolved_height = to_nearest_multiple(job_input["height"], multiple)
                prompt[NODE_H3]["inputs"]["width"] = resolved_width
                prompt[NODE_H3]["inputs"]["height"] = resolved_height
                size_mode = "explicit_snapped"
                if int(job_input["width"]) != resolved_width or int(job_input["height"]) != resolved_height:
                    logger.info(
                        "📐 T2V snapped %sx%s → %sx%s",
                        job_input["width"],
                        job_input["height"],
                        resolved_width,
                        resolved_height,
                    )
            else:
                prompt[NODE_H3]["inputs"]["width"] = [NODE_RES, 0]
                prompt[NODE_H3]["inputs"]["height"] = [NODE_RES, 1]
                size_mode = "resolution_selector"

        prompt[NODE_DURATION]["inputs"]["value"] = duration
        prompt[NODE_CREATE_VIDEO]["inputs"]["fps"] = fps

        if "length" in job_input or "frames" in job_input:
            length = align_frame_count(int(job_input.get("length", job_input.get("frames"))))
            prompt[NODE_H3]["inputs"]["length"] = length
        else:
            length = frames_from_duration(duration, fps)

        turbo_mode = apply_turbo_mode(prompt, job_input, mode=mode)
        try:
            apply_realism_and_dynamic_loras(prompt, job_input, mode=mode, turbo_mode=turbo_mode)
        except RuntimeError as e:
            logger.exception("T2V/I2V LoRA setup failed")
            return {"error": str(e)}

        if mode == "i2v":
            image_path = resolve_media_input(
                job_input,
                ["image", "first_frame", "start_image", "start"],
                task_id,
                "input_image.png",
            )
            if not image_path:
                return {
                    "error": "I2V mode requires an input image (image_url / image_base64 / image_path / first_frame_*)."
                }

            force_selector = (
                job_input.get("aspect_ratio") is not None
                and _coerce_bool(job_input.get("auto_size"), True) is False
                and "width" not in job_input
                and "height" not in job_input
            )

            if force_selector:
                aspect = normalize_aspect_ratio(
                    job_input.get("aspect_ratio"), default="1:1 (Square)"
                )
                prompt[NODE_RES]["inputs"]["aspect_ratio"] = aspect
                prompt[NODE_RES]["inputs"]["megapixels"] = megapixels
                prompt[NODE_RES]["inputs"]["multiple"] = multiple
                prompt[NODE_H3]["inputs"]["width"] = [NODE_RES, 0]
                prompt[NODE_H3]["inputs"]["height"] = [NODE_RES, 1]
                staged = stage_into_comfy_input(image_path, f"{uuid.uuid4().hex}_input_image.png")
                prompt[NODE_LOAD_IMAGE]["inputs"]["image"] = staged
                prompt[NODE_H3]["inputs"]["first_frame"] = [NODE_LOAD_IMAGE, 0]
                size_mode = "resolution_selector"
                use_auto_image_size = False
            else:
                mp = float(job_input.get("image_megapixels", megapixels))
                resolved_width, resolved_height, size_mode = resolve_i2v_output_size(
                    job_input, image_path, mp, multiple
                )
                use_auto_image_size = size_mode == "auto_megapixels"

                resized_name = f"{uuid.uuid4().hex}_i2v_{resolved_width}x{resolved_height}.png"
                resized_path = os.path.join(COMFY_INPUT_DIR, resized_name)
                resize_image_cover(image_path, resized_path, resolved_width, resolved_height)
                prompt[NODE_LOAD_IMAGE]["inputs"]["image"] = resized_name
                prompt[NODE_H3]["inputs"]["first_frame"] = [NODE_LOAD_IMAGE, 0]
                prompt[NODE_H3]["inputs"]["width"] = int(resolved_width)
                prompt[NODE_H3]["inputs"]["height"] = int(resolved_height)
                if NODE_IMAGE_SCALE in prompt:
                    prompt[NODE_IMAGE_SCALE]["inputs"]["megapixels"] = megapixels
                    prompt[NODE_IMAGE_SCALE]["inputs"]["resolution_steps"] = multiple
                    prompt[NODE_IMAGE_SCALE]["inputs"]["image"] = [NODE_LOAD_IMAGE, 0]
                if NODE_IMAGE_SIZE in prompt:
                    prompt[NODE_IMAGE_SIZE]["inputs"]["image"] = (
                        [NODE_IMAGE_SCALE, 0] if NODE_IMAGE_SCALE in prompt else [NODE_LOAD_IMAGE, 0]
                    )

            wire_optional_frame(
                prompt, job_input, ["last_frame", "end_image", "end"], "21", "last_frame", task_id, "last.png"
            )
        else:
            wire_optional_frame(
                prompt, job_input, ["first_frame", "start_image", "start"], "20", "first_frame", task_id, "first.png"
            )
            wire_optional_frame(
                prompt, job_input, ["last_frame", "end_image", "end"], "21", "last_frame", task_id, "last.png"
            )

        if "seed" in job_input:
            prompt[NODE_NOISE]["inputs"]["noise_seed"] = int(job_input["seed"])
        if "denoise" in job_input:
            prompt[NODE_SCHEDULER]["inputs"]["denoise"] = float(job_input["denoise"])
        if "scheduler" in job_input:
            prompt[NODE_SCHEDULER]["inputs"]["scheduler"] = str(job_input["scheduler"])
        if "sampler_name" in job_input:
            prompt[NODE_SAMPLER_SELECT]["inputs"]["sampler_name"] = str(job_input["sampler_name"])

        if "unet_name" in job_input and job_input["unet_name"]:
            prompt[NODE_UNET]["inputs"]["unet_name"] = resolve_override_model_name(
                "unet_name", job_input["unet_name"]
            )
        if "clip_name" in job_input and job_input["clip_name"]:
            prompt[NODE_CLIP]["inputs"]["clip_name"] = resolve_override_model_name(
                "clip_name", job_input["clip_name"]
            )
        if "vae_name" in job_input and job_input["vae_name"]:
            prompt[NODE_VAE_VIDEO]["inputs"]["vae_name"] = resolve_override_model_name(
                "vae_name", job_input["vae_name"]
            )
        if "audio_vae_name" in job_input and job_input["audio_vae_name"]:
            prompt[NODE_VAE_AUDIO]["inputs"]["vae_name"] = resolve_override_model_name(
                "vae_name", job_input["audio_vae_name"]
            )

        save_node = NODE_SAVE

    wait_for_comfy_http()
    try:
        videos = get_videos(prompt)
    except Exception as e:
        logger.exception("Job failed")
        return {"error": str(e)}

    result_base = {
        "mode": mode,
        "turbo_mode": turbo_mode,
        "auto_size": use_auto_image_size if mode == "i2v" else False,
        "size_mode": size_mode,
        "width": resolved_width,
        "height": resolved_height,
        "length": length,
        "fps": fps,
        "duration_requested": duration,
        "reference_count": len(ref_paths) if mode == "r2v" else 0,
    }
    if save_node in videos and videos[save_node]:
        return {"video": videos[save_node][0], **result_base}
    for _nid, vids in videos.items():
        if vids:
            return {"video": vids[0], **result_base}
    return {"error": "Generated video could not be found."}


runpod.serverless.start({"handler": handler})
