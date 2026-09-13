#!/usr/bin/env python3
"""
Model synchronization script for H3 Minimax RunPod Serverless.
Downloads models to RunPod volume on first run and creates symlinks in ComfyUI directories.
"""

import os
import sys
import subprocess
import logging
from pathlib import Path
from typing import Dict, List, Tuple

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment variables
MODEL_ROOT = os.getenv("H3_MODEL_ROOT", "/runpod-volume/h3-models")
COMFY_ROOT = os.getenv("COMFY_ROOT", "/opt/ComfyUI")
HF_TOKEN = os.getenv("HF_TOKEN", os.getenv("HUGGING_FACE_HUB_TOKEN", ""))

# Model definitions: (repo_id, repo_path, local_subdir, filename)
MODELS_TO_SYNC: List[Tuple[str, str, str, str]] = [
    # VAE models
    (
        "Comfy-Org/MiniMax-H3",
        "vae/minimax_h3_audio_vae_fp32.safetensors",
        "vae",
        "minimax_h3_audio_vae_fp32.safetensors"
    ),
    (
        "Comfy-Org/MiniMax-H3",
        "vae/minimax_h3_video_vae_fp16.safetensors",
        "vae",
        "minimax_h3_video_vae_fp16.safetensors"
    ),
    # Diffusion models
    (
        "Comfy-Org/MiniMax-H3",
        "diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors",
        "diffusion_models",
        "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
    ),
    (
        "Comfy-Org/MiniMax-H3",
        "diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors",
        "diffusion_models",
        "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
    ),
    # Text encoder
    (
        "Comfy-Org/MiniMax-H3",
        "text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
        "text_encoders",
        "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
    ),
    # Turbo LoRAs
    (
        "lightx2v/Minimax-h3-Turbo",
        "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
        "loras",
        "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"
    ),
    (
        "lightx2v/Minimax-h3-Turbo",
        "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors",
        "loras",
        "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"
    ),
]


def get_file_size_mb(filepath: Path) -> float:
    """Get file size in MB."""
    if filepath.exists():
        return filepath.stat().st_size / (1024 * 1024)
    return 0.0


def download_model(repo_id: str, repo_path: str, dest_path: Path) -> bool:
    """
    Download a model file from Hugging Face using fetch_model.sh script.
    
    Args:
        repo_id: Hugging Face repository ID
        repo_path: Path within the repository
        dest_path: Destination file path
        
    Returns:
        True if successful, False otherwise
    """
    logger.info(f"Downloading {repo_id}/{repo_path}...")
    
    # Create parent directory
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Use fetch_model.sh if available, otherwise use huggingface_hub
    fetch_script = "/usr/local/bin/fetch_model.sh"
    
    if os.path.exists(fetch_script):
        try:
            cmd = [fetch_script, repo_id, repo_path, str(dest_path)]
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True
            )
            logger.info(f"✅ Downloaded {dest_path.name} ({get_file_size_mb(dest_path):.1f} MB)")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Failed to download {repo_path}: {e.stderr}")
            return False
    else:
        # Fallback to huggingface_hub
        try:
            from huggingface_hub import hf_hub_download
            
            downloaded_path = hf_hub_download(
                repo_id=repo_id,
                filename=repo_path,
                token=HF_TOKEN if HF_TOKEN else None,
                local_dir=dest_path.parent,
                local_dir_use_symlinks=False
            )
            
            # Move to correct location if needed
            if downloaded_path != str(dest_path):
                import shutil
                shutil.move(downloaded_path, dest_path)
            
            logger.info(f"✅ Downloaded {dest_path.name} ({get_file_size_mb(dest_path):.1f} MB)")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to download {repo_path}: {e}")
            return False


def create_symlink(source: Path, target: Path) -> bool:
    """
    Create a symlink from target to source.
    
    Args:
        source: Source file (in volume)
        target: Target symlink location (in ComfyUI)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Create parent directory
        target.parent.mkdir(parents=True, exist_ok=True)
        
        # Remove existing symlink or file
        if target.exists() or target.is_symlink():
            target.unlink()
        
        # Create symlink
        target.symlink_to(source)
        logger.info(f"🔗 Linked {target} -> {source}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to create symlink {target} -> {source}: {e}")
        return False


def sync_models() -> bool:
    """
    Synchronize all models to RunPod volume and create symlinks.
    
    Returns:
        True if all models synced successfully, False otherwise
    """
    logger.info("=" * 80)
    logger.info("Starting model synchronization to RunPod volume")
    logger.info(f"Model root: {MODEL_ROOT}")
    logger.info(f"ComfyUI root: {COMFY_ROOT}")
    logger.info("=" * 80)
    
    # Create model root directory
    model_root = Path(MODEL_ROOT)
    model_root.mkdir(parents=True, exist_ok=True)
    
    comfy_root = Path(COMFY_ROOT)
    
    success_count = 0
    total_count = len(MODELS_TO_SYNC)
    
    for repo_id, repo_path, subdir, filename in MODELS_TO_SYNC:
        logger.info(f"\n[{success_count + 1}/{total_count}] Processing {filename}...")
        
        # Paths
        volume_path = model_root / subdir / filename
        comfy_path = comfy_root / "models" / subdir / filename
        
        # Check if model exists in volume
        if volume_path.exists() and volume_path.stat().st_size > 0:
            logger.info(f"✅ Model exists in volume ({get_file_size_mb(volume_path):.1f} MB)")
        else:
            # Download to volume
            if not download_model(repo_id, repo_path, volume_path):
                logger.warning(f"⚠️ Failed to download {filename}, will retry on next sync")
                continue
        
        # Create symlink in ComfyUI
        if create_symlink(volume_path, comfy_path):
            success_count += 1
        else:
            logger.warning(f"⚠️ Failed to create symlink for {filename}")
    
    # Clean up temporary HF cache
    logger.info("\n🧹 Cleaning up temporary Hugging Face cache...")
    subprocess.run(
        ["rm", "-rf", "/tmp/hf_home", "/root/.cache/huggingface"],
        capture_output=True
    )
    
    logger.info("=" * 80)
    logger.info(f"Model synchronization complete: {success_count}/{total_count} successful")
    logger.info("=" * 80)
    
    return success_count == total_count


def verify_models() -> Dict[str, bool]:
    """
    Verify that all required models are accessible in ComfyUI.
    
    Returns:
        Dictionary mapping model names to availability status
    """
    comfy_root = Path(COMFY_ROOT)
    status = {}
    
    for _, _, subdir, filename in MODELS_TO_SYNC:
        comfy_path = comfy_root / "models" / subdir / filename
        is_available = comfy_path.exists() and (
            comfy_path.is_symlink() or comfy_path.stat().st_size > 0
        )
        status[filename] = is_available
    
    return status


if __name__ == "__main__":
    try:
        # Sync models
        success = sync_models()
        
        # Verify models
        logger.info("\n📋 Verifying model availability...")
        status = verify_models()
        
        available = sum(1 for v in status.values() if v)
        total = len(status)
        
        logger.info(f"\nModel availability: {available}/{total}")
        for name, is_available in status.items():
            status_icon = "✅" if is_available else "❌"
            logger.info(f"  {status_icon} {name}")
        
        if not success:
            logger.warning("\n⚠️ Some models failed to sync. They will be downloaded on-demand.")
            sys.exit(0)  # Don't fail the container, allow runtime download
        
        logger.info("\n✅ All models synced successfully!")
        sys.exit(0)
        
    except Exception as e:
        logger.error(f"\n❌ Fatal error during model sync: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
