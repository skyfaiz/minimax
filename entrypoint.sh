#!/bin/bash
set -e

echo "Checking CUDA availability..."

python_cuda_check() {
    python3 -c "
import torch
try:
    if torch.cuda.is_available():
        print('CUDA_AVAILABLE')
        exit(0)
    else:
        print('CUDA_NOT_AVAILABLE')
        exit(1)
except Exception as e:
    print(f'CUDA_ERROR: {e}')
    exit(2)
" 2>/dev/null
}

cuda_status=$(python_cuda_check)
case $? in
    0)
        echo "✅ CUDA is available and working"
        export CUDA_VISIBLE_DEVICES=0
        export FORCE_CUDA=1
        ;;
    1)
        echo "❌ CUDA is not available"
        exit 1
        ;;
    2)
        echo "❌ CUDA check failed"
        exit 1
        ;;
esac

if command -v nvidia-smi &> /dev/null; then
    nvidia-smi || { echo "❌ nvidia-smi failed"; exit 1; }
else
    echo "❌ nvidia-smi not found"
    exit 1
fi

# hf_xet parallel downloads + scratch under /tmp (purged after each fetch)
export HF_HOME="${HF_HOME:-/tmp/hf_home}"
export HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-${HF_HOME}/hub}"
export HF_HUB_CACHE="${HF_HUB_CACHE:-$HUGGINGFACE_HUB_CACHE}"
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-0}"
export HF_XET_HIGH_PERFORMANCE="${HF_XET_HIGH_PERFORMANCE:-1}"
export HF_HUB_ENABLE_HF_TRANSFER="${HF_HUB_ENABLE_HF_TRANSFER:-0}"
export HF_HUB_DISABLE_TELEMETRY=1

purge_hf_temp() {
    rm -rf /tmp/hf_home /root/.cache/huggingface "${HOME}/.cache/huggingface" 2>/dev/null || true
    echo "▶ purged Hugging Face temp caches"
}

resolve_model() {
    local name="$1"
    local subdir="$2"   # diffusion_models | text_encoders | vae | loras
    local repo_path="$3"
    local repo_id="${4:-Comfy-Org/MiniMax-H3}"
    local dest="/ComfyUI/models/${subdir}/${name}"

    if [ -f "$dest" ] && [ -s "$dest" ]; then
        echo "✅ ${subdir}/${name} present ($(du -h "$dest" | awk '{print $1}'))"
        return 0
    fi

    for p in \
        "/runpod-volume/${subdir}/${name}" \
        "/runpod-volume/loras/${name}" \
        "/runpod-volume/models/${name}" \
        "/runpod-volume/ComfyUI/models/${subdir}/${name}"; do
        if [ -f "$p" ] && [ -s "$p" ]; then
            mkdir -p "/ComfyUI/models/${subdir}"
            ln -sfn "$p" "$dest"
            echo "✅ ${subdir}/${name} linked from $p"
            return 0
        fi
    done

    echo "▶ ${subdir}/${name} missing — downloading via hf_xet…"
    fetch_model.sh "$repo_id" "$repo_path" "$dest"
    purge_hf_temp
}

resolve_model \
  "minimax_h3_fl2va_pruned_int8_convrot.safetensors" \
  "diffusion_models" \
  "diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors"

resolve_model \
  "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors" \
  "text_encoders" \
  "text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"

resolve_model \
  "minimax_h3_video_vae_fp16.safetensors" \
  "vae" \
  "vae/minimax_h3_video_vae_fp16.safetensors"

resolve_model \
  "minimax_h3_audio_vae_fp32.safetensors" \
  "vae" \
  "vae/minimax_h3_audio_vae_fp32.safetensors"

resolve_model \
  "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors" \
  "loras" \
  "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors" \
  "lightx2v/Minimax-h3-Turbo"

# R2V baked defaults (flat names under correct Comfy folders)
resolve_model \
  "minimax_h3_ref2va_pruned_int8_convrot.safetensors" \
  "diffusion_models" \
  "diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors"

resolve_model \
  "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors" \
  "loras" \
  "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors" \
  "lightx2v/Minimax-h3-Turbo"

# Realism + style LoRAs are NOT prefetched here.
# Jobs pull them at runtime via handler ensure_lora_on_disk (realism_lora / loras[] + hf_token).
# Optional: if a network volume already has realism, link it for a warm cache hit.
REALISM_HUB="h3-realism-people-t2v-i2v-r2v.safetensors"
REALISM_ALIAS="h3-realism-people-t2v-i2v-r2v(r34l1sm).safetensors"
REALISM_DEST="/ComfyUI/models/loras/${REALISM_HUB}"
REALISM_LINK="/ComfyUI/models/loras/${REALISM_ALIAS}"
mkdir -p /ComfyUI/models/loras
if [ ! -f "$REALISM_DEST" ] || [ ! -s "$REALISM_DEST" ]; then
  for p in \
      "/runpod-volume/loras/${REALISM_HUB}" \
      "/runpod-volume/loras/${REALISM_ALIAS}" \
      "/runpod-volume/models/loras/${REALISM_HUB}"; do
    if [ -f "$p" ] && [ -s "$p" ]; then
      ln -sfn "$p" "$REALISM_DEST"
      echo "✅ realism LoRA linked from volume: $p"
      break
    fi
  done
fi
if [ -f "$REALISM_DEST" ] && [ -s "$REALISM_DEST" ]; then
  ln -sfn "$REALISM_HUB" "$REALISM_LINK"
  echo "✅ realism LoRA available from volume ($(du -h "$REALISM_DEST" | awk '{print $1}'))"
else
  echo "ℹ realism LoRA not on volume — will download on first job with realism_lora=true"
fi

purge_hf_temp

echo "Starting ComfyUI in the background..."
python /ComfyUI/main.py --listen --use-sage-attention &

echo "Waiting for ComfyUI to be ready..."
max_wait=600
wait_count=0
while [ $wait_count -lt $max_wait ]; do
    if curl -s http://127.0.0.1:8188/ > /dev/null 2>&1; then
        echo "ComfyUI is ready!"
        break
    fi
    echo "Waiting for ComfyUI... ($wait_count/$max_wait)"
    sleep 2
    wait_count=$((wait_count + 2))
done

if [ $wait_count -ge $max_wait ]; then
    echo "Error: ComfyUI failed to start within $max_wait seconds"
    exit 1
fi

echo "Starting the handler..."
exec python handler.py
