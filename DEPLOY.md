# Deploy MiniMax H3 on RunPod Serverless (T2V / I2V / R2V)

**Deploy once. Use anytime. You’re charged for execution time — not for the image build.**

A step-by-step guide to deploy **[H3 Minimax RunPod Serverless](https://github.com/Akshat-Gupta04/H3-Minimax-Runpod-Serverless)** from GitHub — no local Docker required.

**Worker repo:** https://github.com/Akshat-Gupta04/H3-Minimax-Runpod-Serverless

---

## Before you start

You need:

1. A **GitHub** account
2. A **RunPod** account
3. A **Hugging Face** token (`hf_...`) for model bake / private LoRAs

### Create your RunPod account (referral credit)

New to RunPod? Register with this link and get a **one-time credit from $5–$500**:

**[Register on RunPod →](https://runpod.io?ref=5cr29bpt)**

Use that credit to build and run this MiniMax H3 endpoint.

---

## Step 1 — Login and connect GitHub

1. Open **[RunPod](https://runpod.io?ref=5cr29bpt)** and log in (or create an account with the link above).
2. Connect your **GitHub** account from RunPod (Account / Integrations / GitHub — authorize access).
3. **Fork** this repository on GitHub (required for “Deploy with GitHub”):

   https://github.com/Akshat-Gupta04/H3-Minimax-Runpod-Serverless

   Click **Fork** so it appears under your GitHub user.

---

## Step 2 — Open Serverless → New Endpoint

1. In the RunPod console, go to **Serverless**.
2. Click **New Endpoint**.

---

## Step 3 — Deploy with GitHub repository

1. Choose **Deploy with GitHub repository**.
2. Select **your fork** of `H3-Minimax-Runpod-Serverless`  
   (make sure you already forked it in Step 1).
3. Select the **`main`** branch.

---

## Step 4 — Click Next

Leave the default build / repo options unless you know you need to change them.

Click **Next**.

---

## Step 5 — Choose a 32GB+ GPU

1. Pick a GPU with **32 GB VRAM or more** (48 GB+ is more comfortable for H3).
2. Set a large enough **container disk** (this image bakes large MiniMax weights — **100–200 GB** disk is safer for the first build).
3. Keep **1× GPU** unless you know you need more.

---

## Step 6 — Advanced settings → add Hugging Face token

1. Open **Advanced Settings**.
2. Add your Hugging Face auth token as an environment / secret variable:

| Key | Value |
| --- | --- |
| `HF_TOKEN` | `hf_xxxxxxxxxxxxxxxx` |

Optional aliases some builds also accept:

| Key | Value |
| --- | --- |
| `HUGGING_FACE_HUB_TOKEN` | same `hf_...` token |

This token is used when the image **builds** (downloads base MiniMax models + turbo LoRAs from Hugging Face).

Do **not** paste your token into the public GitHub repo.

Create a token here: https://huggingface.co/settings/tokens

---

## Step 7 — Deploy

Click **Deploy**.

RunPod will:

1. Pull your forked GitHub repo
2. Build the Docker image
3. Bake MiniMax H3 weights + turbo LoRAs
4. Create the serverless endpoint

---

## Step 8 — Watch build logs (one-time wait)

1. Open the endpoint → **Build / Logs**.
2. Wait for the image build to finish.

**Expect about 40–45 minutes the first time** (large Hub downloads).

Later rebuilds may be faster if layers are cached.

When the endpoint shows **Ready** / workers available, continue to Step 9.

---

## Step 9 — Send a request (image in base64)

1. Open your endpoint.
2. Go to **Requests** (or use the API / playground).
3. Paste a JSON body like the examples below.
4. Click **Run**.

### Convert an image to base64

```bash
# macOS / Linux
base64 -i your_image.png | tr -d '\n' > image.b64.txt
```

Paste the string into `image_base64` (with or without a `data:image/png;base64,` prefix).

---

## Example input — Image-to-Video (base64)

```json
{
  "input": {
    "mode": "i2v",
    "image_base64": "iVBORw0KGgoAAAANSUhEUgAA...PASTE_FULL_BASE64_HERE...",
    "prompt": "Editorial cinematic video. Keep the subject from image 1. Slow push-in, natural motion, film grain. No text, no watermark.",
    "duration": 5,
    "fps": 24,
    "megapixels": 0.4,
    "turbo_mode": true,
    "realism_lora": true,
    "seed": 42
  }
}
```

### Same job with an image URL

```json
{
  "input": {
    "mode": "i2v",
    "image_url": "https://raw.githubusercontent.com/Comfy-Org/workflow_templates/refs/heads/main/input/transparent_rgb_gaming_mouse.png",
    "prompt": "Editorial tech product film. Keep the subject from image 1 in a dark studio with blue and orange rim lighting. Slow orbit. No text, no watermark.",
    "duration": 5,
    "fps": 24,
    "megapixels": 0.4,
    "turbo_mode": true,
    "realism_lora": true,
    "seed": 42
  }
}
```

---

## Example input — Text-to-Video

```json
{
  "input": {
    "mode": "t2v",
    "prompt": "Cinematic rooftop chase at dusk, shallow depth of field, film grain, no text, no watermark.",
    "duration": 5,
    "fps": 24,
    "aspect_ratio": "16:9 (Widescreen)",
    "megapixels": 0.4,
    "turbo_mode": true,
    "realism_lora": true,
    "seed": 42
  }
}
```

---

## Example input — Reference-to-Video (2 refs)

```json
{
  "input": {
    "mode": "r2v",
    "prompt": "The people from the references walk through a sunlit market.",
    "reference_images": [
      "https://example.com/ref1.jpg",
      "https://example.com/ref2.jpg"
    ],
    "duration": 5,
    "megapixels": 0.8,
    "turbo_mode": true,
    "realism_lora": true
  }
}
```

You can also pass refs as base64 strings inside `reference_images`.

---

## Example input — Hugging Face LoRA by download URL

```json
{
  "input": {
    "mode": "i2v",
    "image_base64": "iVBORw0KGgoAAAANSUhEUgAA...PASTE_FULL_BASE64_HERE...",
    "prompt": "Keep the subject from image 1. Apply the style LoRA strongly. No text, no watermark.",
    "duration": 5,
    "fps": 24,
    "megapixels": 0.4,
    "turbo_mode": true,
    "realism_lora": true,
    "hf_token": "hf_YOUR_TOKEN_HERE",
    "lora_url": "https://huggingface.co/ORG/REPO/resolve/main/your_lora.safetensors",
    "lora_strength": 0.8,
    "seed": 42
  }
}
```

`hf_token` in the job is for **private** Hub LoRAs. Public files often work without it.

---

## Example output

On success (shape may vary slightly by RunPod wrapper):

```json
{
  "delayTime": 1200,
  "executionTime": 95000,
  "id": "sync-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "status": "COMPLETED",
  "output": {
    "video": "AAAAHGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAAAIZnJlZQAA...base64_mp4...",
    "mode": "i2v",
    "turbo_mode": true,
    "length": 124,
    "fps": 24,
    "duration_requested": 5
  }
}
```

### Save the video from base64

```bash
# If you copied output.video into video.b64.txt
base64 -d -i video.b64.txt -o output.mp4
```

Python:

```python
import base64
import json

data = json.load(open("response.json"))
video_b64 = data["output"]["video"]
open("output.mp4", "wb").write(base64.b64decode(video_b64))
```

---

## API call (optional — outside the UI)

```bash
export RUNPOD_API_KEY=your_runpod_key
export ENDPOINT_ID=your_endpoint_id

curl -X POST "https://api.runpod.ai/v2/$ENDPOINT_ID/runsync" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d @request.json
```

---

## Tips

- First build ≈ **40–45 minutes** — normal.
- First job on a cold worker may also download **realism / style LoRAs**; later jobs on the same worker are faster.
- Prefer **32GB+** GPU; **48GB+** if jobs OOM.
- Keep `HF_TOKEN` only in RunPod secrets / Advanced settings — never commit it.
- Official aspect ratios include: `16:9 (Widescreen)`, `9:16 (Portrait Widescreen)`, `1:1 (Square)`, and others listed in the main README.

---

## Links

| Resource | URL |
| --- | --- |
| Worker repo | https://github.com/Akshat-Gupta04/H3-Minimax-Runpod-Serverless |
| RunPod signup (credit $5–$500) | https://runpod.io?ref=5cr29bpt |
| Hugging Face tokens | https://huggingface.co/settings/tokens |
| MiniMax H3 | https://www.minimax.io/blog/minimax-h3 |

---

If this helped, fork the repo, deploy once, and share your outputs. Questions / issues: open a GitHub issue on the worker repo.
