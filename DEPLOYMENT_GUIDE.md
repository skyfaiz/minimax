# H3 Minimax Volume-Based Deployment Guide

Complete step-by-step guide for deploying H3 Minimax with RunPod volumes.

## 📋 Prerequisites Checklist

- [ ] Docker installed locally (for building)
- [ ] RunPod account ([Sign up](https://runpod.io?ref=5cr29bpt))
- [ ] RunPod API key
- [ ] Hugging Face account and token
- [ ] Docker Hub account (or other registry)

## 🔧 Step 1: Prepare Your Files

### Replace Original Files

The new volume-based setup uses these updated files:

```bash
# Backup originals (optional)
cp Dockerfile Dockerfile.original
cp entrypoint.sh entrypoint.sh.original

# Use new files
mv Dockerfile.new Dockerfile
mv entrypoint.sh.new entrypoint.sh
```

Or keep both and specify the Dockerfile during build:
```bash
docker build -f Dockerfile.new -t h3-minimax-volume .
```

### Verify File Permissions

```bash
chmod +x entrypoint.sh
chmod +x sync_models.py
chmod +x scripts/fetch_model.sh
```

## 🏗️ Step 2: Build Docker Image

### Option A: Local Build

```bash
# Build the image (no HF_TOKEN needed at build time!)
docker build -f Dockerfile.new -t h3-minimax-volume:latest .

# Test locally (optional, requires GPU)
docker run --gpus all -p 8188:8188 \
  -v $(pwd)/test-volume:/runpod-volume \
  -e HF_TOKEN=your_hf_token \
  h3-minimax-volume:latest

# Tag for registry
docker tag h3-minimax-volume:latest YOUR_USERNAME/h3-minimax-volume:latest

# Push to Docker Hub
docker login
docker push YOUR_USERNAME/h3-minimax-volume:latest
```

### Option B: RunPod Hub Build

1. Push your code to GitHub
2. Go to RunPod Console → **Serverless** → **Quick Deploy**
3. Select **GitHub** as source
4. Connect your repository
5. Specify `Dockerfile.new` as the Dockerfile path
6. RunPod will build and host the image for you

**Advantages of RunPod Hub:**
- No need to push to Docker Hub
- Faster deployment
- Automatic rebuilds on git push

## 💾 Step 3: Create Network Volume

### Create Volume

1. Go to [RunPod Console](https://www.runpod.io/console/user/storage)
2. Click **Storage** → **Network Volumes**
3. Click **+ New Network Volume**
4. Configure:
   - **Name**: `h3-models` (or your choice)
   - **Size**: **100 GB minimum** (150 GB recommended)
   - **Region**: Choose based on GPU availability
   - **Type**: Network Volume (not Pod Volume)
5. Click **Create**
6. **Note the Volume ID** - you'll need this

### Volume Pricing

Network volumes cost approximately:
- $0.10/GB/month
- 100 GB = ~$10/month
- Shared across all endpoints in the region

## 🚀 Step 4: Create Serverless Endpoint

### Basic Configuration

1. Go to RunPod Console → **Serverless**
2. Click **+ New Endpoint**
3. **Endpoint Name**: `h3-minimax-volume`

### Container Configuration

- **Container Image**: `YOUR_USERNAME/h3-minimax-volume:latest`
- **Container Disk**: **20 GB** (much smaller than before!)
- **Container Registry Credentials**: Add if using private registry

### GPU Configuration

- **GPU Type**: Select GPUs with **48GB+ VRAM**
  - ✅ RTX A6000 (48GB)
  - ✅ L40 (48GB)
  - ✅ L40S (48GB)
  - ✅ A100 (40GB/80GB)
  - ✅ H100 (80GB)
- **Max Workers**: Start with 1-3 for testing
- **Idle Timeout**: 5 seconds (default)
- **Execution Timeout**: 600 seconds (10 min for long videos)

### Volume Configuration

**IMPORTANT**: Attach your network volume

- **Network Volume**: Select your `h3-models` volume
- **Mount Path**: `/runpod-volume` (must be exactly this!)

### Environment Variables

Add these environment variables:

| Key | Value | Required |
|-----|-------|----------|
| `HF_TOKEN` | Your Hugging Face token | Recommended |
| `H3_MODEL_ROOT` | `/runpod-volume/h3-models` | Optional (default) |

**Note**: HF_TOKEN is optional but recommended for:
- Faster downloads
- Access to private models
- Higher rate limits

### Advanced Settings

- **Active Workers**: 0 (scale from zero)
- **Max Workers**: 3-5 (adjust based on demand)
- **GPUs/Worker**: 1
- **Flashboot**: Enable for faster cold starts
- **Allow Public Access**: Yes (if you want public API)

### Deploy

1. Review all settings
2. Click **Deploy**
3. Wait for endpoint to be created
4. **Copy the Endpoint ID** - you'll need this for API calls

## ⏱️ Step 5: First Run & Model Download

### Monitor First Startup

The first worker will download models to the volume:

1. Go to your endpoint page
2. Click **Logs** tab
3. Send a test request (see below)
4. Watch the logs for model download progress

Expected logs:
```
Starting model synchronization to RunPod volume...
[1/7] Processing minimax_h3_audio_vae_fp32.safetensors...
Downloading Comfy-Org/MiniMax-H3/vae/minimax_h3_audio_vae_fp32.safetensors...
✅ Downloaded minimax_h3_audio_vae_fp32.safetensors (XXX MB)
...
Model synchronization complete: 7/7 successful
```

### Test Request

Send a simple test request:

```bash
export RUNPOD_API_KEY="your_api_key"
export ENDPOINT_ID="your_endpoint_id"

curl -X POST "https://api.runpod.ai/v2/${ENDPOINT_ID}/runsync" \
  -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "prompt": "Test video: a red ball bouncing",
      "duration": 3,
      "turbo_mode": true
    }
  }'
```

### First Run Timeline

- **Model download**: 10-20 minutes (one-time)
- **ComfyUI startup**: 1-2 minutes
- **Video generation**: 2-5 minutes (depends on settings)
- **Total first run**: ~15-30 minutes

### Subsequent Runs

After models are cached:
- **Cold start**: 30-60 seconds (ComfyUI startup)
- **Warm worker**: Instant
- **Video generation**: 2-5 minutes

## 🧪 Step 6: Test with Client Tools

### Setup Python Client

```bash
# Install dependencies
pip install -r requirements_client.txt

# Set environment variables
export RUNPOD_API_KEY="your_api_key"
export RUNPOD_ENDPOINT_ID="your_endpoint_id"

# Test with CLI
python client.py \
  --prompt "Cinematic shot of a sunset over mountains" \
  --output test.mp4 \
  --duration 5
```

### Setup GUI

```bash
# Run GUI
python gui.py

# Configure in GUI:
# 1. Enter API Key
# 2. Enter Endpoint ID
# 3. Click "Save Config"
# 4. Enter prompt and generate!
```

## 📊 Step 7: Verify & Monitor

### Check Volume Usage

```bash
# Via RunPod Console
# Storage → Network Volumes → Your Volume → Usage

# Expected usage after first run: ~50-60 GB
```

### Monitor Endpoint Metrics

In RunPod Console → Serverless → Your Endpoint:

- **Active Workers**: Should scale based on demand
- **Queue Length**: Monitor for bottlenecks
- **Execution Time**: Average ~3-5 min per video
- **Success Rate**: Should be >95%

### Check Logs

Look for these success indicators:
- ✅ CUDA is available and working
- ✅ RunPod volume mounted
- ✅ Model sync completed successfully
- ✅ ComfyUI is ready
- ✅ Starting RunPod handler

## 🔧 Troubleshooting

### Issue: Models Not Downloading

**Symptoms**: Worker fails with "model not found" errors

**Solutions**:
1. Check HF_TOKEN is set correctly
2. Verify volume is mounted at `/runpod-volume`
3. Check volume has enough space (100GB+)
4. Review worker logs for download errors

### Issue: Slow First Startup

**Symptoms**: First job takes >30 minutes

**Solutions**:
- This is normal! Models are ~50GB
- Check network speed in worker logs
- Consider pre-warming: start a worker and let it download before production use

### Issue: Volume Not Mounted

**Symptoms**: Logs show "RunPod volume not found"

**Solutions**:
1. Verify volume is attached in endpoint settings
2. Check mount path is exactly `/runpod-volume`
3. Ensure volume is in the same region as workers

### Issue: Out of Memory

**Symptoms**: CUDA out of memory errors

**Solutions**:
1. Use GPUs with 48GB+ VRAM
2. Reduce `megapixels` setting
3. Disable realism LoRA if not needed
4. Use turbo mode for faster/lighter generation

### Issue: Timeout Errors

**Symptoms**: Jobs timeout before completion

**Solutions**:
1. Increase execution timeout in endpoint settings (600s+)
2. Reduce video duration
3. Use turbo mode
4. Check GPU availability

## 🎯 Production Checklist

Before going to production:

- [ ] Models fully downloaded to volume
- [ ] Test request successful
- [ ] Client tools working
- [ ] Monitoring configured
- [ ] Scaling settings optimized
- [ ] Timeouts configured appropriately
- [ ] Backup volume (optional)
- [ ] Cost monitoring enabled
- [ ] Error handling tested

## 💰 Cost Estimation

### Per Video (5 seconds, turbo mode)

- **Compute**: ~$0.05-0.15 (2-3 min on A6000)
- **Storage**: Negligible (volume is monthly)
- **Network**: Minimal

### Monthly Costs

- **Volume**: ~$10/month (100GB)
- **Compute**: Variable based on usage
- **Idle workers**: $0 (scale to zero)

### Cost Optimization Tips

1. Use turbo mode (8 steps vs 20)
2. Scale to zero when idle
3. Share volume across endpoints
4. Use spot instances if available
5. Monitor and optimize worker count

## 🔄 Updating

### Update Docker Image

```bash
# Make changes to code
# Rebuild image
docker build -f Dockerfile.new -t h3-minimax-volume:v2 .
docker push YOUR_USERNAME/h3-minimax-volume:v2

# Update endpoint
# RunPod Console → Endpoint → Settings → Container Image
# Change to new tag → Save
```

### Update Models

```bash
# SSH into a pod with volume attached
# Delete old models
rm -rf /runpod-volume/h3-models/*

# Restart workers - they'll download fresh models
```

## 📚 Additional Resources

- [RunPod Serverless Docs](https://docs.runpod.io/serverless/overview)
- [Original H3 Minimax Repo](https://github.com/Akshat-Gupta04/H3-Minimax-Runpod-Serverless)
- [MiniMax H3 Documentation](https://www.minimax.io/blog/minimax-h3)
- [ComfyUI Documentation](https://github.com/comfyanonymous/ComfyUI)

## 🆘 Support

If you encounter issues:

1. Check worker logs in RunPod Console
2. Review this troubleshooting guide
3. Test with client tools for detailed errors
4. Check RunPod status page for outages
5. Join RunPod Discord for community support

---

**Ready to deploy?** Follow the steps above and you'll have a production-ready H3 Minimax endpoint with volume-based model storage! 🚀
