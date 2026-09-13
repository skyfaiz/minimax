# MiniMax H3 Text-to-Video (ComfyUI) for RunPod Serverless
FROM wlsdml1114/engui_genai-base_blackwell:1.1 AS runtime

# HF_TOKEN: required at build for Hub model + turbo LoRA bakes.
# Do NOT hardcode tokens. Pass: docker build --build-arg HF_TOKEN=hf_xxx ...
# Style + realism LoRAs are runtime-only via job lora_url / loras + hf_token.
ARG HF_TOKEN
ENV HF_TOKEN=${HF_TOKEN}
ENV HUGGING_FACE_HUB_TOKEN=${HF_TOKEN}
ENV BFL_READ_TOKEN=${HF_TOKEN}

RUN apt-get update && apt-get install -y wget curl aria2 \
    && rm -rf /var/lib/apt/lists/*

# hf_xet = parallel chunked Hub downloads (required for large MiniMax / Qwen weights)
RUN pip install -U --no-cache-dir "huggingface_hub[hf_xet]" hf_xet hf_transfer
RUN pip install --no-cache-dir runpod websocket-client Pillow

ENV HF_HUB_DISABLE_XET=0
ENV HF_XET_HIGH_PERFORMANCE=1
ENV HF_HUB_ENABLE_HF_TRANSFER=0
ENV HF_HUB_DISABLE_TELEMETRY=1
# Scratch cache only — fetch_model.sh purges after every file so layers aren't 2× size
ENV HF_HOME=/tmp/hf_home
ENV HUGGINGFACE_HUB_CACHE=/tmp/hf_home/hub
ENV HF_HUB_CACHE=/tmp/hf_home/hub

WORKDIR /

# Latest ComfyUI required for MiniMaxH3ImageToVideo + ResolutionSelector
RUN git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git && \
    cd /ComfyUI && \
    pip install --no-cache-dir -r requirements.txt && \
    rm -rf /ComfyUI/.git

RUN cd /ComfyUI/custom_nodes && \
    git clone --depth 1 https://github.com/Comfy-Org/ComfyUI-Manager.git && \
    cd ComfyUI-Manager && pip install --no-cache-dir -r requirements.txt && \
    rm -rf /ComfyUI/custom_nodes/ComfyUI-Manager/.git

# R2V output (VHS_VideoCombine) + PathchSageAttentionKJ used by reference workflows
RUN cd /ComfyUI/custom_nodes && \
    git clone --depth 1 https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git && \
    (cd ComfyUI-VideoHelperSuite && pip install --no-cache-dir -r requirements.txt || true) && \
    rm -rf /ComfyUI/custom_nodes/ComfyUI-VideoHelperSuite/.git && \
    git clone --depth 1 https://github.com/kijai/ComfyUI-KJNodes.git && \
    (cd ComfyUI-KJNodes && pip install --no-cache-dir -r requirements.txt || true) && \
    rm -rf /ComfyUI/custom_nodes/ComfyUI-KJNodes/.git && \
    git clone --depth 1 https://github.com/rgthree/rgthree-comfy.git && \
    rm -rf /ComfyUI/custom_nodes/rgthree-comfy/.git

RUN mkdir -p \
    /ComfyUI/models/diffusion_models \
    /ComfyUI/models/text_encoders \
    /ComfyUI/models/vae \
    /ComfyUI/models/loras \
    /ComfyUI/input \
    /ComfyUI/output

COPY scripts/fetch_model.sh /usr/local/bin/fetch_model.sh
RUN chmod +x /usr/local/bin/fetch_model.sh

COPY extra_model_paths.yaml /ComfyUI/extra_model_paths.yaml

# Bake one weight per layer; each fetch_model.sh call purges /tmp/hf_home
RUN fetch_model.sh \
      Comfy-Org/MiniMax-H3 \
      vae/minimax_h3_audio_vae_fp32.safetensors \
      /ComfyUI/models/vae/minimax_h3_audio_vae_fp32.safetensors

RUN fetch_model.sh \
      Comfy-Org/MiniMax-H3 \
      vae/minimax_h3_video_vae_fp16.safetensors \
      /ComfyUI/models/vae/minimax_h3_video_vae_fp16.safetensors

RUN fetch_model.sh \
      Comfy-Org/MiniMax-H3 \
      diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors \
      /ComfyUI/models/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors

# Turbo / Lightning 8-step LoRA — T2V/I2V (toggle via turbo_mode)
RUN fetch_model.sh \
      lightx2v/Minimax-h3-Turbo \
      minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors \
      /ComfyUI/models/loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors \
    || echo "⚠ fl2v turbo LoRA bake skipped — volume/runtime fallback"

# R2V UNET (ref2va) — pruned int8, same family as fl2va bake
RUN fetch_model.sh \
      Comfy-Org/MiniMax-H3 \
      diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors \
      /ComfyUI/models/diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors \
    || echo "⚠ R2V UNET bake skipped — volume/runtime fallback"

# R2V turbo / Lightning 4-step LoRA
RUN fetch_model.sh \
      lightx2v/Minimax-h3-Turbo \
      minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors \
      /ComfyUI/models/loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors \
    || echo "⚠ R2V turbo LoRA bake skipped — volume/runtime fallback"

# Realism People + style/template LoRAs are NOT baked.
# Jobs request them via realism_lora / loras[] + optional hf_token (runtime Hub download).

# Qwen3-VL-32B — shared by T2V/I2V/R2V; Hub build may time out → entrypoint fallback
RUN fetch_model.sh \
      Comfy-Org/MiniMax-H3 \
      text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors \
      /ComfyUI/models/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors \
    || echo "⚠ text encoder bake skipped — volume/runtime fallback"

# Final scrub — keep baked /ComfyUI/models only
RUN rm -rf /tmp/hf_home /root/.cache/huggingface /root/.cache/pip /var/tmp/* \
    && find /ComfyUI -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true

COPY . .
RUN chmod +x /entrypoint.sh \
    && cp -f scripts/fetch_model.sh /usr/local/bin/fetch_model.sh \
    && chmod +x /usr/local/bin/fetch_model.sh

CMD ["/entrypoint.sh"]
