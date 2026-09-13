#!/usr/bin/env bash
# Fetch a Hugging Face file with authenticated hf_xet parallel download + % progress.
# Usage: fetch_model.sh <repo_id> <repo_path> <dest_path>
# Used at Docker build (bake) and at runtime (handler ensure_lora_on_disk / entrypoint).
set -euo pipefail

REPO_ID="${1:?repo id required}"
REPO_PATH="${2:?repo path required}"
DEST="${3:?dest path required}"

DEST_DIR="$(dirname "$DEST")"
mkdir -p "$DEST_DIR"

if [ -f "$DEST" ] && [ -s "$DEST" ]; then
  echo "✅ already present: $DEST ($(du -h "$DEST" | awk '{print $1}'))"
  exit 0
fi

TOKEN="${BFL_READ_TOKEN:-${HF_TOKEN:-${HUGGING_FACE_HUB_TOKEN:-${RUNPOD_HF_TOKEN:-}}}}"
if [ -n "$TOKEN" ]; then
  export HF_TOKEN="$TOKEN"
  export HUGGING_FACE_HUB_TOKEN="$TOKEN"
  export BFL_READ_TOKEN="$TOKEN"
  echo "▶ Authenticated Hugging Face download (token length=${#TOKEN})"
else
  echo "▶ Public Hugging Face download (no token — slower rate limits)" >&2
fi

# Scratch only — never leave Hub/xet blobs next to baked models
export HF_HOME="${HF_HOME:-/tmp/hf_home}"
export HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-${HF_HOME}/hub}"
export HF_HUB_CACHE="${HF_HUB_CACHE:-$HUGGINGFACE_HUB_CACHE}"

# Fast Xet parallel chunked downloads (build + runtime)
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-0}"
export HF_XET_HIGH_PERFORMANCE="${HF_XET_HIGH_PERFORMANCE:-1}"
export HF_HUB_ENABLE_HF_TRANSFER="${HF_HUB_ENABLE_HF_TRANSFER:-0}"
export HF_HUB_DISABLE_TELEMETRY="${HF_HUB_DISABLE_TELEMETRY:-1}"
# Force our newline progress reporter (not interactive \r bars)
export HF_HUB_DISABLE_PROGRESS_BARS="${HF_HUB_DISABLE_PROGRESS_BARS:-0}"
export TQDM_MININTERVAL="${TQDM_MININTERVAL:-1}"

echo "▶ Downloading ${REPO_ID}/${REPO_PATH}"
echo "  → ${DEST}"
echo "  hf_xet: DISABLE_XET=${HF_HUB_DISABLE_XET} HIGH_PERFORMANCE=${HF_XET_HIGH_PERFORMANCE}"
echo "  HF_HOME=${HF_HOME}"

python3 - "$REPO_ID" "$REPO_PATH" "$DEST" <<'PY'
import os
import sys
import shutil
import time
from pathlib import Path

repo_id, repo_path, dest = sys.argv[1:4]
token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or None
progress_step = max(1, int(os.environ.get("HF_PROGRESS_STEP_PCT", "5")))

try:
    from huggingface_hub import hf_hub_download, HfApi
except Exception as e:
    print(f"❌ huggingface_hub import failed: {e}", file=sys.stderr)
    sys.exit(2)

try:
    import hf_xet  # noqa: F401
    print(
        f"▶ hf_xet available "
        f"(HIGH_PERFORMANCE={os.environ.get('HF_XET_HIGH_PERFORMANCE')}, "
        f"DISABLE_XET={os.environ.get('HF_HUB_DISABLE_XET')})",
        flush=True,
    )
except Exception:
    print("⚠ hf_xet not installed — falling back to standard Hub download", file=sys.stderr)


def _fmt_bytes(n: float) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024.0 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.1f} GB"


# Log-friendly tqdm: prints percent on new lines (RunPod / Docker build logs)
try:
    from tqdm.auto import tqdm as _tqdm_base
except Exception:
    _tqdm_base = None


if _tqdm_base is not None:

    class LogProgressTqdm(_tqdm_base):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("mininterval", 1.0)
            kwargs.setdefault("file", sys.stdout)
            kwargs.setdefault("dynamic_ncols", False)
            kwargs.setdefault("leave", True)
            # Disable bar rendering; we emit our own percent lines
            kwargs["bar_format"] = "{desc}"
            kwargs["disable"] = False
            super().__init__(*args, **kwargs)
            self._last_logged_pct = -progress_step
            self._last_log_t = 0.0
            self._label = Path(repo_path).name

        def display(self, msg=None, pos=None):
            # Skip default \r bar; percent lines come from update()
            return

        def update(self, n=1):
            out = super().update(n)
            self._maybe_log()
            return out

        def _maybe_log(self, force: bool = False):
            total = self.total or 0
            n = self.n or 0
            now = time.time()
            if total > 0:
                pct = int(100.0 * n / total)
                if force or pct >= self._last_logged_pct + progress_step or pct >= 100:
                    self._last_logged_pct = pct if pct < 100 else 100
                    self._last_log_t = now
                    print(
                        f"⬇ progress: {self._label} {pct}% "
                        f"({_fmt_bytes(n)} / {_fmt_bytes(total)})",
                        flush=True,
                    )
            elif force or (now - self._last_log_t) >= 5.0:
                self._last_log_t = now
                print(f"⬇ progress: {self._label} {_fmt_bytes(n)} downloaded…", flush=True)

        def close(self):
            try:
                self._maybe_log(force=True)
            except Exception:
                pass
            return super().close()

    # Register for huggingface_hub downloads
    try:
        import huggingface_hub.utils.tqdm as hub_tqdm

        hub_tqdm._tqdm_class = LogProgressTqdm
    except Exception:
        try:
            import huggingface_hub.file_download as fd

            fd.tqdm = LogProgressTqdm
        except Exception as e:
            print(f"⚠ could not install progress tqdm: {e}", file=sys.stderr)

expected_size = None
try:
    api = HfApi(token=token)
    info = api.model_info(repo_id, files_metadata=True)
    print(f"▶ model_info ok: id={info.id} gated={getattr(info, 'gated', None)}", flush=True)
    for sib in info.siblings or []:
        if getattr(sib, "rfilename", None) == repo_path:
            expected_size = getattr(sib, "size", None)
            if expected_size:
                print(
                    f"▶ expected size: {_fmt_bytes(expected_size)} ({expected_size} bytes)",
                    flush=True,
                )
            break
except Exception as e:
    print(f"⚠ model_info/size lookup: {type(e).__name__}: {e}", flush=True)
    try:
        info = HfApi(token=token).model_info(repo_id)
        print(f"▶ model_info ok: id={info.id} gated={getattr(info, 'gated', None)}", flush=True)
    except Exception as e2:
        print(f"❌ Cannot access repo {repo_id}: {type(e2).__name__}: {e2}", file=sys.stderr)
        print(
            "   If gated, accept the license for the same HF account as the token:",
            file=sys.stderr,
        )
        print(f"   https://huggingface.co/{repo_id}", file=sys.stderr)
        sys.exit(3)

print(
    f"▶ starting hf_hub_download (hf_xet parallel={'yes' if os.environ.get('HF_HUB_DISABLE_XET','0')=='0' else 'no'})…",
    flush=True,
)
# Hang kill is OPT-IN (runtime LoRAs only). Docker bake of multi-GB weights must NOT default to 300s.
# Handler sets HF_DOWNLOAD_HANG_TIMEOUT_SEC=300 for runtime LoRA downloads.
hang_raw = (os.environ.get("HF_DOWNLOAD_HANG_TIMEOUT_SEC") or "0").strip()
try:
    hang_sec = int(hang_raw)
except ValueError:
    hang_sec = 0
if hang_sec > 0:
    print(f"▶ download hang timeout: {hang_sec}s (runtime LoRA mode)", flush=True)
else:
    print("▶ download hang timeout: disabled (bake / large-model mode)", flush=True)
t0 = time.time()


def _do_download():
    try:
        return hf_hub_download(
            repo_id=repo_id,
            filename=repo_path,
            token=token,
            force_download=False,
            resume_download=True,
        )
    except TypeError:
        return hf_hub_download(
            repo_id=repo_id,
            filename=repo_path,
            token=token,
            force_download=False,
        )


import concurrent.futures

with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
    fut = pool.submit(_do_download)
    try:
        if hang_sec > 0:
            path = fut.result(timeout=hang_sec)
        else:
            path = fut.result()
    except concurrent.futures.TimeoutError:
        print(
            f"❌ hf_hub_download hung after {hang_sec}s (XET/Hub hang kill) — aborting",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(4)
    except Exception as e:
        print(f"❌ hf_hub_download failed: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(4)

elapsed = time.time() - t0
if token:
    print("▶ hf_hub_download used authenticated token (hf_xet parallel when available)", flush=True)
else:
    print("⚠ hf_hub_download unauthenticated — expect HF rate-limit warnings", file=sys.stderr)

src = Path(path)
dst = Path(dest)
if not src.is_file() or src.stat().st_size <= 0:
    print(f"❌ downloaded path missing/empty: {src}", file=sys.stderr)
    sys.exit(5)

dst.parent.mkdir(parents=True, exist_ok=True)
tmp = dst.with_suffix(dst.suffix + ".partial")
shutil.copy2(src, tmp)
tmp.replace(dst)
size = dst.stat().st_size
speed = size / elapsed if elapsed > 0 else 0
print(
    f"✅ download ok: {dst} ({_fmt_bytes(size)}) in {elapsed:.1f}s "
    f"(~{_fmt_bytes(speed)}/s)",
    flush=True,
)


def purge_hf_temp():
    """Remove Hub/xet scratch so Docker layers / runtime disk aren't doubled."""
    roots = set()
    for key in ("HF_HOME",):
        v = os.environ.get(key)
        if v:
            roots.add(Path(v))
    roots.update(
        [
            Path("/tmp/hf_home"),
            Path.home() / ".cache" / "huggingface",
            Path("/root/.cache/huggingface"),
        ]
    )
    for root in roots:
        if not root.exists():
            continue
        shutil.rmtree(root, ignore_errors=True)
        print(f"▶ purged {root}", flush=True)
    for extra in (
        Path("/tmp/hf_home"),
        Path("/root/.cache/huggingface"),
        Path.home() / ".cache" / "huggingface",
    ):
        if extra.exists():
            shutil.rmtree(extra, ignore_errors=True)
            print(f"▶ purged {extra}", flush=True)


purge_hf_temp()
PY
