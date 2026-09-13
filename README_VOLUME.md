# H3 Minimax RunPod Serverless - Volume-Based Deployment

This is an updated version of the H3 Minimax RunPod Serverless deployment that uses **RunPod volumes** for model storage instead of baking models into the Docker image. This approach offers several advantages:

- **Faster builds**: No need to download 50+ GB of models during image build
- **Smaller images**: Docker images are much smaller and faster to push/pull
- **Shared models**: Multiple endpoints can share the same model volume
- **Easy updates**: Update models without rebuilding the entire image
- **Cost efficient**: Models are downloaded once to the volume and reused

## 🚀 Quick Start

### 1. Prerequisites

- Docker (for building the image)
- RunPod account with API key ([Sign up here](https://runpod.io?ref=5cr29bpt))
- Hugging Face account with token (for model downloads)
- RunPod Network Volume (at least 100GB for all models)

### 2. Create a RunPod Network Volume

1. Go to RunPod Console → **Storage** → **Network Volumes**
2. Click **+ New Network Volume**
3. Name it (e.g., `h3-models`)
4. Size: **100 GB minimum** (models are ~50-60 GB total)
5. Select your preferred region
6. Create the volume

### 3. Build the Docker Image

The new Dockerfile is based on PyTorch 2.6.0 with CUDA 12.4:

```bash
# Build the image (no HF_TOKEN needed at build time!)
docker build -f Dockerfile.new -t h3-minimax-volume:latest .

# Tag for your registry
docker tag h3-minimax-volume:latest YOUR_DOCKERHUB_USER/h3-minimax-volume:latest

# Push to registry
docker push YOUR_DOCKERHUB_USER/h3-minimax-volume:latest
```

Or use RunPod's built-in GitHub integration to build directly from your repo.

### 4. Create RunPod Serverless Endpoint

1. Go to RunPod Console → **Serverless** → **New Endpoint**
2. **Container Image**: Use your pushed image
3. **Container Disk**: 20 GB (much smaller than before!)
4. **GPU**: Select 48GB+ VRAM (A6000, L40, H100, etc.)
5. **Network Volume**: Attach your volume at `/runpod-volume`
6. **Environment Variables** (optional):
   - `HF_TOKEN`: Your Hugging Face token (for private models/LoRAs)
   - `H3_MODEL_ROOT`: Custom model path (default: `/runpod-volume/h3-models`)
7. **Workers**: Configure min/max workers and scaling
8. Deploy!

### 5. First Run - Model Download

On the first worker startup, models will be automatically downloaded to your RunPod volume:

- The `sync_models.py` script runs during container startup
- Models are downloaded to `/runpod-volume/h3-models/`
- Symlinks are created in ComfyUI directories
- Subsequent workers will use the cached models (instant startup!)

**Expected download time**: 10-20 minutes depending on network speed (one-time only)

Models downloaded:
- MiniMax H3 VAEs (audio + video)
- MiniMax H3 diffusion models (fl2va + ref2va)
- Qwen3-VL text encoder
- Turbo LoRAs (fl2v + ref2v)

## 📦 What's Included

### New Files

- **`Dockerfile.new`**: Updated Dockerfile using PyTorch base image
- **`sync_models.py`**: Python script to sync models to volume
- **`entrypoint.sh.new`**: Updated entrypoint with model sync
- **`client.py`**: Python client for API interaction
- **`gui.py`**: Modern GUI application for easy video generation

### File Structure

```
H3-Minimax-Runpod-Serverless/
├── Dockerfile.new          # New volume-based Dockerfile
├── entrypoint.sh.new       # Updated entrypoint
├── sync_models.py          # Model synchronization script
├── handler.py              # RunPod serverless handler (unchanged)
├── client.py               # Python API client
├── gui.py                  # GUI application
├── requirements_client.txt # Client dependencies
├── workflow/               # ComfyUI workflows
└── scripts/                # Helper scripts
```

## 🖥️ Using the Client Tools

### Python Client (client.py)

Install dependencies:

```bash
pip install requests
```

Set environment variables:

```bash
export RUNPOD_API_KEY="your_api_key_here"
export RUNPOD_ENDPOINT_ID="your_endpoint_id_here"
```

Generate a video:

```bash
# Text-to-Video
python client.py \
  --prompt "Cinematic rooftop chase at dusk, film grain" \
  --output my_video.mp4 \
  --duration 5 \
  --aspect-ratio "16:9 (Widescreen)"

# Image-to-Video
python client.py \
  --prompt "Camera slowly zooms in on the subject" \
  --mode i2v \
  --image start_frame.png \
  --output i2v_video.mp4

# Reference-to-Video
python client.py \
  --prompt "The person walks through a sunlit market" \
  --mode r2v \
  --references ref1.jpg ref2.jpg \
  --realism \
  --output r2v_video.mp4
```

### GUI Application (gui.py)

Install dependencies:

```bash
pip install requests
```

Run the GUI:

```bash
python gui.py
```

Features:
- 🎨 Modern, user-friendly interface
- 🔧 Save/load API configuration
- 📝 Easy prompt editing
- 🖼️ Image/reference file browser
- ⚙️ All generation options (turbo, realism, aspect ratio, etc.)
- 📊 Real-time progress and logging
- 💾 Auto-save configuration

## 🔧 Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `H3_MODEL_ROOT` | `/runpod-volume/h3-models` | Root directory for models on volume |
| `COMFY_ROOT` | `/opt/ComfyUI` | ComfyUI installation directory |
| `HF_TOKEN` | - | Hugging Face token for private models |
| `HF_HUB_ENABLE_HF_TRANSFER` | `1` | Enable fast HF transfers |

### Volume Structure

After first run, your volume will have this structure:

```
/runpod-volume/
└── h3-models/
    ├── diffusion_models/
    │   ├── minimax_h3_fl2va_pruned_int8_convrot.safetensors
    │   └── minimax_h3_ref2va_pruned_int8_convrot.safetensors
    ├── text_encoders/
    │   └── qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors
    ├── vae/
    │   ├── minimax_h3_audio_vae_fp32.safetensors
    │   └── minimax_h3_video_vae_fp16.safetensors
    └── loras/
        ├── minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors
        ├── minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors
        └── h3-realism-people-t2v-i2v-r2v.safetensors (optional)
```

## 🎬 API Usage

The API remains the same as the original version. See the main README.md for full API documentation.

### Example Request (Text-to-Video)

```bash
curl -X POST "https://api.runpod.ai/v2/YOUR_ENDPOINT_ID/runsync" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "prompt": "Cinematic rooftop chase at dusk, film grain, no text",
      "duration": 5,
      "aspect_ratio": "16:9 (Widescreen)",
      "turbo_mode": true,
      "seed": 42
    }
  }'
```

## 💡 Tips & Best Practices

### For Production

1. **Pre-warm the volume**: Run a test worker to download all models before scaling up
2. **Monitor disk usage**: Keep an eye on volume usage as LoRAs accumulate
3. **Use network volumes in the same region**: Minimize latency between workers and storage
4. **Set appropriate timeouts**: First job on a new worker may take longer

### Cost Optimization

1. **Share volumes**: Multiple endpoints can use the same model volume
2. **Smaller images**: Faster deployment and lower bandwidth costs
3. **Efficient scaling**: Workers start faster with pre-cached models
4. **Container disk**: Only 20GB needed vs 100GB+ for baked images

### Troubleshooting

**Models not downloading?**
- Check HF_TOKEN is set if using private repos
- Verify volume is mounted at `/runpod-volume`
- Check worker logs for download errors

**Slow first startup?**
- Normal! Models are ~50GB and take 10-20 minutes to download
- Subsequent workers will be instant using cached models

**Out of disk space?**
- Increase network volume size
- Clean up old LoRAs in `/runpod-volume/h3-models/loras/`

## 🔄 Updating Models

To update models without rebuilding the image:

1. SSH into a RunPod pod with the volume attached
2. Delete the old model files from `/runpod-volume/h3-models/`
3. Restart workers - they'll download the latest versions

Or modify `sync_models.py` to force re-download.

## 📊 Comparison: Baked vs Volume

| Aspect | Baked (Original) | Volume (New) |
|--------|------------------|--------------|
| Image size | 60-80 GB | 5-10 GB |
| Build time | 30-60 min | 5-10 min |
| First startup | Fast | 10-20 min (one-time) |
| Subsequent startups | Fast | Fast |
| Model updates | Rebuild image | Delete & restart |
| Multi-endpoint sharing | No | Yes |
| Storage cost | Per image | Per volume |

## 🙏 Credits

- Original repo: [H3-Minimax-Runpod-Serverless](https://github.com/Akshat-Gupta04/H3-Minimax-Runpod-Serverless)
- [MiniMax H3](https://www.minimax.io/blog/minimax-h3)
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
- [RunPod](https://runpod.io?ref=5cr29bpt)

## 📄 License

Use at your own risk. Respect MiniMax, Hugging Face, and third-party model licenses.
