# H3 Minimax RunPod Serverless

Deploy **[MiniMax H3](https://www.minimax.io/blog/minimax-h3)** video generation on **[RunPod Serverless](https://runpod.io?ref=5cr29bpt)** — text-to-video (T2V), image-to-video (I2V), and reference-to-video (R2V) with optional turbo, realism, and any Hugging Face LoRA via a download URL.

This repo is a ready-to-build ComfyUI worker: bake the base models once, push an image, create a serverless endpoint, and call it with JSON.

**Full RunPod GitHub deploy walkthrough:** see **[DEPLOY.md](./DEPLOY.md)**.

---

## Get RunPod credit

Need a RunPod account to deploy this worker?

**[Register on RunPod now](https://runpod.io?ref=5cr29bpt)** and get a **one-time credit from $5–$500**.

Use that credit toward GPUs for building, testing, and running this MiniMax H3 serverless endpoint.

---

## What you get

| Mode | Input | Output |
| --- | --- | --- |
| **T2V** | Text prompt | MP4 (base64) |
| **I2V** | Start frame + prompt | MP4 |
| **R2V** | 1–4 reference images + prompt | MP4 with native synced audio |

Extras:

- **Turbo** (default on) — fewer steps via baked LightX2V turbo LoRAs  
- **Realism People LoRA** — optional; downloaded at job time from Hugging Face  
- **Any Hub LoRA** — paste a Hugging Face file URL + `hf_token`  
- **Power Lora Loader** — turbo + realism + style LoRAs in one stack  

---

## Requirements

- Docker (local build) or RunPod Hub build  
- Hugging Face account + token (for model bake and private LoRAs)  
- [RunPod account](https://runpod.io?ref=5cr29bpt) (register now — one-time credit **$5–$500**)  
- GPU workers with **≥ 48 GB VRAM** and large container disk (weights are multi‑GB)

---

## Quick start (article path)

### 1. Clone

```bash
git clone https://github.com/Akshat-Gupta04/H3-Minimax-Runpod-Serverless.git
cd H3-Minimax-Runpod-Serverless
```

### 2. Build the worker image

Pass your Hub token only as a build arg (never commit it):

```bash
export HF_TOKEN=hf_xxxxxxxx

docker build \
  --build-arg HF_TOKEN="$HF_TOKEN" \
  -t h3-minimax-runpod-serverless .
```

What gets **baked** into the image:

- MiniMax H3 diffusion (T2V/I2V + R2V), text encoder, VAEs  
- T2V/I2V turbo LoRA (8-step)  
- R2V turbo LoRA (4-step)  

What is **not** baked (downloaded when a job needs them):

- Realism People LoRA  
- Style / community LoRAs (via `lora_url` / `loras`)

First build can take a long time (large Hub downloads). Prefer a machine with good bandwidth.

### 3. Push to a registry RunPod can pull

Example (Docker Hub):

```bash
docker tag h3-minimax-runpod-serverless YOUR_DOCKERHUB_USER/h3-minimax-runpod-serverless:latest
docker push YOUR_DOCKERHUB_USER/h3-minimax-runpod-serverless:latest
```

Or build/push via **RunPod Hub** from this GitHub repo.

### 4. Create a RunPod Serverless endpoint

New to RunPod? **[Sign up here](https://runpod.io?ref=5cr29bpt)** for a one-time credit (**$5–$500**).

1. RunPod Console → **Serverless** → **New Endpoint**  
2. Select your image  
3. GPU: **48GB+** (e.g. A6000 / L40 / H100 class depending on availability)  
4. Increase **container disk** so baked models fit  
5. Optional: attach a network volume under `/runpod-volume` for warm LoRA cache  
6. Deploy and copy the **Endpoint ID**

You do **not** need to put your Hugging Face token in the endpoint env for public Hub LoRAs. For private LoRAs, pass `hf_token` **per job** (recommended) so tokens are not shared across all workers.

### 5. Call the API

**Sync** (wait for the video):

```bash
curl -X POST "https://api.runpod.ai/v2/ENDPOINT_ID/runsync" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d @example_request.json
```

**Async**:

```bash
curl -X POST "https://api.runpod.ai/v2/ENDPOINT_ID/run" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d @example_request_i2v.json
```

Poll `https://api.runpod.ai/v2/ENDPOINT_ID/status/JOB_ID` until `COMPLETED`. The result includes `"video": "<base64 mp4>"`.

---

## Request examples

### Text-to-video (T2V)

```json
{
  "input": {
    "prompt": "Cinematic rooftop chase at dusk, film grain, no text.",
    "duration": 5,
    "aspect_ratio": "16:9 (Widescreen)",
    "megapixels": 0.4,
    "turbo_mode": true,
    "seed": 42
  }
}
```

See `example_request.json`.

### Image-to-video (I2V)

```json
{
  "input": {
    "mode": "i2v",
    "image_url": "https://example.com/frame.png",
    "prompt": "Editorial product film. Keep the subject from image 1. Slow push-in.",
    "duration": 5,
    "turbo_mode": true
  }
}
```

See `example_request_i2v.json`.

### Reference-to-video (R2V)

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

See `example_request_r2v.json`.

### Add any Hugging Face LoRA (simple)

Paste the Hub **resolve** download link + token:

```json
{
  "input": {
    "mode": "i2v",
    "image_url": "https://example.com/frame.png",
    "prompt": "…",
    "turbo_mode": true,
    "realism_lora": true,
    "hf_token": "hf_...",
    "lora_url": "https://huggingface.co/lightx2v/Minimax-h3-Turbo/resolve/main/minimax_h3_ref2v_turbo_4step_v0.1_bf16.safetensors",
    "lora_strength": 0.8
  }
}
```

Multiple LoRAs:

```json
"hf_token": "hf_...",
"loras": [
  "https://huggingface.co/org/repo/resolve/main/style.safetensors",
  {"url": "https://huggingface.co/org/other/resolve/main/file.safetensors", "strength": 1.0}
]
```

See `example_request_hf_loras.json`.

LoRAs download once per worker and stay cached until that worker dies.

---

## Modes & behavior

| Mode | How selected | Workflow |
| --- | --- | --- |
| **T2V** | default / `mode: "t2v"` / no image | `workflow/minimax_h3_t2v_api.json` |
| **I2V** | `mode: "i2v"` or start-frame fields | `workflow/minimax_h3_i2v_api.json` |
| **R2V** | `mode: "r2v"` or `reference_images` | `workflow/minimax_h3_r2v_{1–4}ref_api.json` |

### Turbo

| Mode | Turbo on | Turbo off |
| --- | --- | --- |
| T2V / I2V | fl2v turbo LoRA, **8 steps** | strength `0`, **20 steps** |
| R2V | ref2v turbo LoRA, **8 steps** (override with `turbo_steps`) | strength `0`, **20 steps** |

### Power Lora stack

All modes use **Power Lora Loader (rgthree)**:

1. **Slot 1** — turbo (baked)  
2. **Slot 2** — realism (runtime if `realism_lora: true`)  
3. **Slot 3+** — extras from `lora_url` / `loras`

Disable realism with `"realism_lora": false`.

---

## Input API (common fields)

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `prompt` / `text` | string | cinematic default | Generation prompt |
| `mode` | string | auto | `t2v` / `i2v` / `r2v` |
| `image_url` / `image_base64` | string | — | I2V start frame |
| `reference_images` | list | — | R2V: 1–4 refs (url / base64 / path) |
| `turbo_mode` | bool | `true` | Enable turbo LoRA |
| `realism_lora` | bool | `true` | Enable realism LoRA (runtime download) |
| `hf_token` | string | — | Hub token for private LoRA downloads |
| `lora_url` / `lora_urls` | string / list | — | Hugging Face download link(s) |
| `lora_strength` | float | `1.0` | Strength for single `lora_url` |
| `loras` | list | — | Extra LoRAs (URLs or `{url,strength}`) |
| `duration` | float | `5` | Seconds |
| `fps` | float | `24` | Output FPS |
| `aspect_ratio` | string | `16:9 (Widescreen)` | See list below |
| `megapixels` | float | T2V/I2V `0.4` / R2V `0.8` | Target resolution scale |
| `width` + `height` | int | — | Explicit size (multiples of 32) |
| `seed` | int | sample | Noise seed |

**Official `aspect_ratio` values** (must match Comfy ResolutionSelector):

- `1:1 (Square)`
- `2:3 (Portrait Photo)`
- `3:2 (Photo)`
- `3:4 (Portrait Standard)`
- `4:3 (Standard)`
- `9:16 (Portrait Widescreen)`
- `16:9 (Widescreen)`
- `21:9 (Ultrawide)`

Short aliases like `9:16` are normalized by the worker.

---

## Response

```json
{
  "video": "<BASE64_MP4>",
  "mode": "i2v",
  "turbo_mode": true,
  "length": 124,
  "fps": 24,
  "duration_requested": 5
}
```

Decode base64 to an `.mp4` file in your app or article demo.

---

## Bake policy

| Asset | In Docker image? |
| --- | --- |
| Base diffusion / text encoders / VAE | Yes |
| T2V/I2V turbo (`lightx2v` fl2v) | Yes |
| R2V turbo (`lightx2v` ref2v) | Yes |
| Realism People | No — job-time download |
| Style / template LoRAs | No — via `lora_url` + optional `hf_token` |

---

## Repo layout

| Path | Role |
| --- | --- |
| `handler.py` | RunPod serverless handler |
| `Dockerfile` | ComfyUI + custom nodes + model bake |
| `entrypoint.sh` | Start ComfyUI, then handler |
| `scripts/fetch_model.sh` | Hub download helper (hf_xet) |
| `workflow/` | T2V / I2V / R2V API graphs |
| `example_request*.json` | Sample payloads |
| `extra_model_paths.yaml` | Network-volume model roots |

---

## Tips for production / articles

1. **Cold start** — first job on a new worker may download realism/style LoRAs; later jobs on the same worker are faster.  
2. **Disk** — give the endpoint enough container disk for baked weights + runtime LoRAs.  
3. **Tokens** — use job-level `hf_token` for private LoRAs; rotate any token that was ever committed elsewhere.  
4. **Timeouts** — long videos need generous job / handler timeouts on the endpoint.  
5. **GPU** — 48GB+ recommended for the pruned int8 H3 stacks in this image.

---

## Credits

- [MiniMax H3](https://www.minimax.io/blog/minimax-h3)  
- [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3)  
- [lightx2v/Minimax-h3-Turbo](https://huggingface.co/lightx2v/Minimax-h3-Turbo)  
- [fal/MiniMax-H3-Realism-People-LoRA](https://huggingface.co/fal/MiniMax-H3-Realism-People-LoRA)  
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI)  
- [RunPod Serverless](https://docs.runpod.io/serverless/overview)  
- [Sign up for RunPod](https://runpod.io?ref=5cr29bpt) (one-time credit $5–$500)

## License

Use at your own risk. Respect MiniMax, Hugging Face, and third-party model licenses when redistributing weights or generating content.
