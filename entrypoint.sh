#!/bin/bash
set -e

echo "=" | tr '=' '=' | head -c 80; echo
echo "H3 Minimax RunPod Serverless - Starting"
echo "=" | tr '=' '=' | head -c 80; echo

# Check CUDA availability
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

# Set environment variables
export H3_MODEL_ROOT="${H3_MODEL_ROOT:-/runpod-volume/h3-models}"
export COMFY_ROOT="${COMFY_ROOT:-/opt/ComfyUI}"
export HF_HOME="${HF_HOME:-/tmp/hf_home}"
export HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-${HF_HOME}/hub}"
export HF_HUB_CACHE="${HF_HUB_CACHE:-$HUGGINGFACE_HUB_CACHE}"
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-0}"
export HF_XET_HIGH_PERFORMANCE="${HF_XET_HIGH_PERFORMANCE:-1}"
export HF_HUB_ENABLE_HF_TRANSFER="${HF_HUB_ENABLE_HF_TRANSFER:-1}"
export HF_HUB_DISABLE_TELEMETRY=1

echo ""
echo "Environment:"
echo "  Model Root: $H3_MODEL_ROOT"
echo "  ComfyUI Root: $COMFY_ROOT"
echo ""

# Sync models from/to RunPod volume
echo "=" | tr '=' '=' | head -c 80; echo
echo "Synchronizing models to RunPod volume..."
echo "=" | tr '=' '=' | head -c 80; echo

if [ -d "$H3_MODEL_ROOT" ]; then
    echo "✅ RunPod volume mounted at $H3_MODEL_ROOT"
else
    echo "⚠️ RunPod volume not found at $H3_MODEL_ROOT, creating directory..."
    mkdir -p "$H3_MODEL_ROOT"
fi

# Run model sync script
python3 /opt/worker/sync_models.py
sync_exit_code=$?

if [ $sync_exit_code -ne 0 ]; then
    echo "⚠️ Model sync completed with warnings (exit code: $sync_exit_code)"
    echo "   Some models may be downloaded on-demand during job execution"
else
    echo "✅ Model sync completed successfully"
fi

# Optional: Sync realism LoRA if available on volume
REALISM_HUB="h3-realism-people-t2v-i2v-r2v.safetensors"
REALISM_ALIAS="h3-realism-people-t2v-i2v-r2v(r34l1sm).safetensors"
REALISM_DEST="$COMFY_ROOT/models/loras/${REALISM_HUB}"
REALISM_LINK="$COMFY_ROOT/models/loras/${REALISM_ALIAS}"

mkdir -p "$COMFY_ROOT/models/loras"

if [ ! -f "$REALISM_DEST" ] || [ ! -s "$REALISM_DEST" ]; then
    for p in \
        "$H3_MODEL_ROOT/loras/${REALISM_HUB}" \
        "$H3_MODEL_ROOT/loras/${REALISM_ALIAS}" \
        "/runpod-volume/loras/${REALISM_HUB}" \
        "/runpod-volume/loras/${REALISM_ALIAS}"; do
        if [ -f "$p" ] && [ -s "$p" ]; then
            ln -sfn "$p" "$REALISM_DEST"
            echo "✅ Realism LoRA linked from volume: $p"
            break
        fi
    done
fi

if [ -f "$REALISM_DEST" ] && [ -s "$REALISM_DEST" ]; then
    ln -sfn "$REALISM_HUB" "$REALISM_LINK"
    echo "✅ Realism LoRA available ($(du -h "$REALISM_DEST" | awk '{print $1}'))"
else
    echo "ℹ️  Realism LoRA not on volume — will download on first job with realism_lora=true"
fi

# Clean up temporary HF cache
echo ""
echo "🧹 Cleaning up temporary caches..."
rm -rf /tmp/hf_home /root/.cache/huggingface /root/.cache/pip 2>/dev/null || true

# Start ComfyUI
echo ""
echo "=" | tr '=' '=' | head -c 80; echo
echo "Starting ComfyUI server..."
echo "=" | tr '=' '=' | head -c 80; echo

cd "$COMFY_ROOT"
python main.py --listen --use-sage-attention &
COMFY_PID=$!

# Wait for ComfyUI to be ready
echo "Waiting for ComfyUI to be ready..."
max_wait=600
wait_count=0

while [ $wait_count -lt $max_wait ]; do
    if curl -s http://127.0.0.1:8188/ > /dev/null 2>&1; then
        echo "✅ ComfyUI is ready!"
        break
    fi
    
    # Check if ComfyUI process is still running
    if ! kill -0 $COMFY_PID 2>/dev/null; then
        echo "❌ ComfyUI process died unexpectedly"
        exit 1
    fi
    
    if [ $((wait_count % 10)) -eq 0 ]; then
        echo "   Waiting for ComfyUI... ($wait_count/$max_wait seconds)"
    fi
    
    sleep 2
    wait_count=$((wait_count + 2))
done

if [ $wait_count -ge $max_wait ]; then
    echo "❌ ComfyUI failed to start within $max_wait seconds"
    exit 1
fi

# Start the RunPod handler
echo ""
echo "=" | tr '=' '=' | head -c 80; echo
echo "Starting RunPod handler..."
echo "=" | tr '=' '=' | head -c 80; echo

cd /opt/worker
exec python handler.py
