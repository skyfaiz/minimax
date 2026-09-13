# 🚀 Quick Start Guide

Get up and running with H3 Minimax volume-based deployment in minutes!

## TL;DR

```bash
# 1. Build and push image
docker build -f Dockerfile.new -t yourname/h3-minimax-volume .
docker push yourname/h3-minimax-volume

# 2. Create 100GB RunPod volume at /runpod-volume

# 3. Create endpoint with your image + volume

# 4. Use the client
export RUNPOD_API_KEY="your_key"
export RUNPOD_ENDPOINT_ID="your_endpoint"
python client.py --prompt "Your prompt here" --output video.mp4
```

## 📦 What You Need

1. **RunPod Account** → [Sign up here](https://runpod.io?ref=5cr29bpt)
2. **Docker** → For building the image
3. **100GB Network Volume** → Create in RunPod Console
4. **GPU Endpoint** → 48GB+ VRAM (A6000, L40, H100)

## 🏗️ Build & Deploy (5 minutes)

### Step 1: Build Image

```bash
# Clone or navigate to repo
cd H3-Minimax-Runpod-Serverless-main

# Build (no HF token needed!)
docker build -f Dockerfile.new -t h3-minimax-volume .

# Push to your registry
docker tag h3-minimax-volume yourname/h3-minimax-volume
docker push yourname/h3-minimax-volume
```

### Step 2: Create Volume

RunPod Console → Storage → Network Volumes → New Volume
- **Size**: 100 GB
- **Name**: h3-models
- **Region**: Same as your GPUs

### Step 3: Create Endpoint

RunPod Console → Serverless → New Endpoint
- **Image**: `yourname/h3-minimax-volume`
- **Container Disk**: 20 GB
- **GPU**: A6000 or better (48GB+ VRAM)
- **Volume**: Attach your volume at `/runpod-volume`
- **Env**: `HF_TOKEN=your_hf_token` (optional)

## 🎬 Generate Your First Video (3 methods)

### Method 1: Command Line (Simplest)

```bash
# Install client
pip install requests

# Set credentials
export RUNPOD_API_KEY="your_api_key"
export RUNPOD_ENDPOINT_ID="your_endpoint_id"

# Generate!
python client.py \
  --prompt "Cinematic sunset over mountains, film grain" \
  --output my_video.mp4 \
  --duration 5
```

### Method 2: GUI (Easiest)

```bash
# Install and run
pip install requests
python gui.py

# In GUI:
# 1. Enter API Key and Endpoint ID
# 2. Click "Save Config"
# 3. Enter your prompt
# 4. Click "Generate Video"
```

### Method 3: Direct API (Most Flexible)

```bash
curl -X POST "https://api.runpod.ai/v2/YOUR_ENDPOINT/runsync" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "prompt": "Your prompt here",
      "duration": 5,
      "turbo_mode": true
    }
  }'
```

## ⚡ Key Differences from Original

| Feature | Original (Baked) | New (Volume) |
|---------|------------------|--------------|
| Image size | 60-80 GB | 5-10 GB |
| Build time | 30-60 min | 5-10 min |
| First startup | 2 min | 15-20 min* |
| Next startups | 2 min | 2 min |
| Model updates | Rebuild | Just delete |

*One-time model download to volume

## 🎯 Common Use Cases

### Text-to-Video (T2V)

```bash
python client.py \
  --prompt "Epic dragon flying over medieval castle" \
  --duration 5 \
  --aspect-ratio "16:9 (Widescreen)" \
  --output dragon.mp4
```

### Image-to-Video (I2V)

```bash
python client.py \
  --mode i2v \
  --image start_frame.png \
  --prompt "Camera slowly zooms in, dramatic lighting" \
  --output zoom.mp4
```

### Reference-to-Video (R2V)

```bash
python client.py \
  --mode r2v \
  --references person1.jpg person2.jpg \
  --prompt "The people walk through a busy market" \
  --realism \
  --output market.mp4
```

## 🔧 Quick Settings Guide

### For Speed (Turbo Mode)
```bash
--duration 3 --no-turbo false  # Default, 8 steps
```

### For Quality (Normal Mode)
```bash
--duration 5 --no-turbo  # 20 steps, slower
```

### For Realism (People)
```bash
--realism  # Adds realism LoRA
```

### For Consistency
```bash
--seed 42  # Same seed = same result
```

## 📊 First Run Timeline

1. **Send request** → Instant
2. **Worker starts** → 30-60 sec
3. **Models download** → 10-20 min (one-time!)
4. **ComfyUI loads** → 1-2 min
5. **Video generates** → 2-5 min
6. **Total first run** → ~15-30 min

**After first run**: 2-5 min per video! 🚀

## 💡 Pro Tips

1. **Pre-warm your endpoint**: Send a test request before production to download models
2. **Use turbo mode**: 8 steps vs 20 = 3x faster
3. **Share volumes**: Multiple endpoints can use the same model volume
4. **Monitor costs**: Scale to zero when idle
5. **Save configs**: GUI saves your API credentials

## 🐛 Quick Troubleshooting

**"Volume not found"**
→ Check volume is mounted at `/runpod-volume`

**"Model download failed"**
→ Add `HF_TOKEN` environment variable

**"Out of memory"**
→ Use GPU with 48GB+ VRAM

**"Timeout"**
→ Increase execution timeout to 600s

**"Slow first run"**
→ Normal! Models are 50GB, downloads take 15-20 min

## 📚 Learn More

- **Full Documentation**: See `README_VOLUME.md`
- **Deployment Guide**: See `DEPLOYMENT_GUIDE.md`
- **Original README**: See `README.md`
- **API Reference**: See example_request*.json files

## 🎉 You're Ready!

That's it! You now have a production-ready H3 Minimax endpoint with:
- ✅ Volume-based model storage
- ✅ Fast builds and deployments
- ✅ Easy-to-use client tools
- ✅ Modern GUI interface
- ✅ Cost-efficient scaling

Start generating amazing videos! 🎬

---

**Need help?** Check `DEPLOYMENT_GUIDE.md` for detailed troubleshooting.
