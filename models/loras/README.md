# ComfyUI LoRAs

Weights are **not** stored in git.

| File | When | Notes |
| --- | --- | --- |
| `minimax_h3_fl2v_turbo_8step_…` | Docker bake | T2V/I2V turbo |
| `minimax_h3_ref2v_turbo_4step_…` | Docker bake | R2V turbo |
| Realism People | Job runtime | `fal/MiniMax-H3-Realism-People-LoRA` when `realism_lora: true` |
| Style / template LoRAs | Job runtime | Pass via `loras` + optional `hf_token` |

```bash
docker build --build-arg HF_TOKEN=hf_xxx -t minimax_h3_t2v .
# Build token is for base models + turbo only — not used for job LoRA downloads
```

Example (paste Hub download link + token):

```json
"hf_token": "hf_...",
"lora_url": "https://huggingface.co/here4code/my-loras/resolve/main/iggon_h3_doggy.safetensors",
"lora_strength": 0.8
```
