# MiniMax H3 Text-to-Video (ComfyUI) for RunPod Serverless with Volume Storage
# Using PyTorch 2.5.1 for comfy_kitchen compatibility
FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    H3_MODEL_ROOT=/runpod-volume/h3-models \
    COMFY_ROOT=/opt/ComfyUI

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gcc \
    git \
    libsndfile1 \
    wget \
    curl \
    aria2 \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN pip install --upgrade pip && \
    pip install packaging psutil ninja && \
    pip install --upgrade accelerate && \
    pip install "https://github.com/Dao-AILab/flash-attention/releases/download/v2.7.2.post1/flash_attn-2.7.2.post1%2Bcu12torch2.5cxx11abiFALSE-cp311-cp311-linux_x86_64.whl" && \
    pip install -U "huggingface_hub[hf_transfer]" hf_xet hf_transfer && \
    pip install runpod websocket-client Pillow

# Hugging Face environment variables - use volume for cache to avoid disk space issues
ENV HF_HOME=/runpod-volume/hf_cache \
    HUGGINGFACE_HUB_CACHE=/runpod-volume/hf_cache/hub \
    HF_HUB_CACHE=/runpod-volume/hf_cache/hub \
    HF_HUB_DISABLE_XET=0 \
    HF_XET_HIGH_PERFORMANCE=1 \
    HF_HUB_ENABLE_HF_TRANSFER=1 \
    HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /opt

# Clone and setup ComfyUI
RUN git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git && \
    cd /opt/ComfyUI && \
    pip install -r requirements.txt && \
    rm -rf /opt/ComfyUI/.git

# Install ComfyUI custom nodes
RUN cd /opt/ComfyUI/custom_nodes && \
    git clone --depth 1 https://github.com/Comfy-Org/ComfyUI-Manager.git && \
    cd ComfyUI-Manager && pip install -r requirements.txt && \
    rm -rf .git && \
    cd /opt/ComfyUI/custom_nodes && \
    git clone --depth 1 https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git && \
    (cd ComfyUI-VideoHelperSuite && pip install -r requirements.txt || true) && \
    rm -rf ComfyUI-VideoHelperSuite/.git && \
    git clone --depth 1 https://github.com/kijai/ComfyUI-KJNodes.git && \
    (cd ComfyUI-KJNodes && pip install -r requirements.txt || true) && \
    rm -rf ComfyUI-KJNodes/.git && \
    git clone --depth 1 https://github.com/rgthree/rgthree-comfy.git && \
    rm -rf rgthree-comfy/.git

# Create model directories (will be linked to volume)
RUN mkdir -p \
    /opt/ComfyUI/models/diffusion_models \
    /opt/ComfyUI/models/text_encoders \
    /opt/ComfyUI/models/vae \
    /opt/ComfyUI/models/loras \
    /opt/ComfyUI/input \
    /opt/ComfyUI/output

# Setup worker directory
WORKDIR /opt/worker
COPY handler.py sync_models.py entrypoint.sh ./
COPY scripts/fetch_model.sh /usr/local/bin/fetch_model.sh
COPY extra_model_paths.yaml /opt/ComfyUI/extra_model_paths.yaml
COPY workflow /opt/worker/workflow

RUN chmod +x /opt/worker/entrypoint.sh /usr/local/bin/fetch_model.sh

# Clean up temporary files
RUN rm -rf /tmp/hf_home /root/.cache/huggingface /root/.cache/pip /var/tmp/* && \
    find /opt -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true

CMD ["bash", "/opt/worker/entrypoint.sh"]
