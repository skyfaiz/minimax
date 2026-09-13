#!/usr/bin/env python3
"""
H3 Minimax RunPod Client
Simple Python client for interacting with the H3 Minimax RunPod Serverless endpoint.
"""

import os
import sys
import json
import time
import base64
import requests
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from dataclasses import dataclass


@dataclass
class RunPodConfig:
    """Configuration for RunPod API."""
    api_key: str
    endpoint_id: str
    base_url: str = "https://api.runpod.ai/v2"
    
    @property
    def endpoint_url(self) -> str:
        return f"{self.base_url}/{self.endpoint_id}"
    
    @classmethod
    def from_env(cls) -> "RunPodConfig":
        """Load configuration from environment variables."""
        api_key = os.getenv("RUNPOD_API_KEY")
        endpoint_id = os.getenv("RUNPOD_ENDPOINT_ID")
        
        if not api_key:
            raise ValueError("RUNPOD_API_KEY environment variable not set")
        if not endpoint_id:
            raise ValueError("RUNPOD_ENDPOINT_ID environment variable not set")
        
        return cls(api_key=api_key, endpoint_id=endpoint_id)


class H3MinimaxClient:
    """Client for H3 Minimax video generation on RunPod."""
    
    def __init__(self, config: RunPodConfig):
        """
        Initialize the client.
        
        Args:
            config: RunPod configuration
        """
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json"
        })
    
    def _encode_image(self, image_path: str) -> str:
        """Encode image file to base64."""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    
    def _save_video(self, base64_video: str, output_path: str) -> None:
        """Save base64 video to file."""
        video_data = base64.b64decode(base64_video)
        with open(output_path, "wb") as f:
            f.write(video_data)
    
    def run_sync(
        self,
        prompt: str,
        mode: str = "t2v",
        image_path: Optional[str] = None,
        reference_images: Optional[List[str]] = None,
        duration: float = 5.0,
        aspect_ratio: str = "16:9 (Widescreen)",
        megapixels: float = 0.4,
        fps: float = 24.0,
        turbo_mode: bool = True,
        realism_lora: bool = False,
        seed: Optional[int] = None,
        hf_token: Optional[str] = None,
        lora_url: Optional[str] = None,
        lora_strength: float = 1.0,
        loras: Optional[List[Union[str, Dict[str, Any]]]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Run synchronous video generation (waits for completion).
        
        Args:
            prompt: Text prompt for generation
            mode: Generation mode ("t2v", "i2v", or "r2v")
            image_path: Path to start frame image (for i2v mode)
            reference_images: List of reference image paths (for r2v mode)
            duration: Video duration in seconds
            aspect_ratio: Aspect ratio string
            megapixels: Target megapixels for resolution
            fps: Frames per second
            turbo_mode: Enable turbo mode for faster generation
            realism_lora: Enable realism LoRA
            seed: Random seed for reproducibility
            hf_token: Hugging Face token for private models
            lora_url: URL to custom LoRA
            lora_strength: Strength for custom LoRA
            loras: List of additional LoRAs
            **kwargs: Additional parameters
            
        Returns:
            Response dictionary with video data
        """
        # Build request payload
        input_data = {
            "prompt": prompt,
            "mode": mode,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "megapixels": megapixels,
            "fps": fps,
            "turbo_mode": turbo_mode,
            "realism_lora": realism_lora,
        }
        
        # Add optional parameters
        if seed is not None:
            input_data["seed"] = seed
        if hf_token:
            input_data["hf_token"] = hf_token
        if lora_url:
            input_data["lora_url"] = lora_url
            input_data["lora_strength"] = lora_strength
        if loras:
            input_data["loras"] = loras
        
        # Handle image inputs
        if mode == "i2v" and image_path:
            if image_path.startswith("http"):
                input_data["image_url"] = image_path
            else:
                input_data["image_base64"] = self._encode_image(image_path)
        
        if mode == "r2v" and reference_images:
            encoded_refs = []
            for ref in reference_images:
                if ref.startswith("http"):
                    encoded_refs.append(ref)
                else:
                    encoded_refs.append(self._encode_image(ref))
            input_data["reference_images"] = encoded_refs
        
        # Add any extra kwargs
        input_data.update(kwargs)
        
        # Make request
        url = f"{self.config.endpoint_url}/runsync"
        print(f"🚀 Sending request to {url}...")
        print(f"   Mode: {mode}, Duration: {duration}s, Turbo: {turbo_mode}")
        
        response = self.session.post(url, json={"input": input_data})
        response.raise_for_status()
        
        result = response.json()
        
        if result.get("status") == "COMPLETED":
            print("✅ Video generation completed!")
            return result
        else:
            print(f"⚠️ Unexpected status: {result.get('status')}")
            return result
    
    def run_async(
        self,
        prompt: str,
        mode: str = "t2v",
        **kwargs
    ) -> str:
        """
        Start asynchronous video generation.
        
        Args:
            prompt: Text prompt for generation
            mode: Generation mode ("t2v", "i2v", or "r2v")
            **kwargs: Additional parameters (same as run_sync)
            
        Returns:
            Job ID for polling
        """
        # Build input (reuse sync logic)
        input_data = {"prompt": prompt, "mode": mode}
        input_data.update(kwargs)
        
        url = f"{self.config.endpoint_url}/run"
        print(f"🚀 Starting async job at {url}...")
        
        response = self.session.post(url, json={"input": input_data})
        response.raise_for_status()
        
        result = response.json()
        job_id = result.get("id")
        
        print(f"✅ Job started: {job_id}")
        return job_id
    
    def check_status(self, job_id: str) -> Dict[str, Any]:
        """
        Check the status of an async job.
        
        Args:
            job_id: Job ID from run_async
            
        Returns:
            Status response dictionary
        """
        url = f"{self.config.endpoint_url}/status/{job_id}"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()
    
    def wait_for_completion(
        self,
        job_id: str,
        poll_interval: int = 5,
        timeout: int = 600
    ) -> Dict[str, Any]:
        """
        Wait for an async job to complete.
        
        Args:
            job_id: Job ID from run_async
            poll_interval: Seconds between status checks
            timeout: Maximum seconds to wait
            
        Returns:
            Final result dictionary
        """
        print(f"⏳ Waiting for job {job_id} to complete...")
        
        start_time = time.time()
        
        while True:
            elapsed = time.time() - start_time
            
            if elapsed > timeout:
                raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")
            
            result = self.check_status(job_id)
            status = result.get("status")
            
            if status == "COMPLETED":
                print(f"✅ Job completed in {elapsed:.1f}s")
                return result
            elif status == "FAILED":
                error = result.get("error", "Unknown error")
                raise RuntimeError(f"Job failed: {error}")
            elif status in ["IN_QUEUE", "IN_PROGRESS"]:
                print(f"   Status: {status} ({elapsed:.0f}s elapsed)")
                time.sleep(poll_interval)
            else:
                print(f"   Unknown status: {status}")
                time.sleep(poll_interval)
    
    def generate_video(
        self,
        prompt: str,
        output_path: str,
        mode: str = "t2v",
        async_mode: bool = False,
        **kwargs
    ) -> str:
        """
        Generate a video and save it to file.
        
        Args:
            prompt: Text prompt for generation
            output_path: Path to save output video
            mode: Generation mode ("t2v", "i2v", or "r2v")
            async_mode: Use async API (default: sync)
            **kwargs: Additional parameters
            
        Returns:
            Path to saved video file
        """
        if async_mode:
            job_id = self.run_async(prompt, mode=mode, **kwargs)
            result = self.wait_for_completion(job_id)
        else:
            result = self.run_sync(prompt, mode=mode, **kwargs)
        
        # Extract video from result
        if "output" in result:
            video_b64 = result["output"].get("video")
        elif "video" in result:
            video_b64 = result["video"]
        else:
            raise ValueError("No video found in response")
        
        # Save video
        self._save_video(video_b64, output_path)
        print(f"💾 Video saved to: {output_path}")
        
        return output_path


def main():
    """Example usage of the client."""
    import argparse
    
    parser = argparse.ArgumentParser(description="H3 Minimax RunPod Client")
    parser.add_argument("--prompt", required=True, help="Text prompt for generation")
    parser.add_argument("--output", default="output.mp4", help="Output video path")
    parser.add_argument("--mode", default="t2v", choices=["t2v", "i2v", "r2v"], help="Generation mode")
    parser.add_argument("--image", help="Start frame image (for i2v)")
    parser.add_argument("--references", nargs="+", help="Reference images (for r2v)")
    parser.add_argument("--duration", type=float, default=5.0, help="Video duration in seconds")
    parser.add_argument("--aspect-ratio", default="16:9 (Widescreen)", help="Aspect ratio")
    parser.add_argument("--no-turbo", action="store_true", help="Disable turbo mode")
    parser.add_argument("--realism", action="store_true", help="Enable realism LoRA")
    parser.add_argument("--seed", type=int, help="Random seed")
    parser.add_argument("--async", dest="async_mode", action="store_true", help="Use async API")
    
    args = parser.parse_args()
    
    try:
        # Load config from environment
        config = RunPodConfig.from_env()
        client = H3MinimaxClient(config)
        
        # Generate video
        client.generate_video(
            prompt=args.prompt,
            output_path=args.output,
            mode=args.mode,
            image_path=args.image,
            reference_images=args.references,
            duration=args.duration,
            aspect_ratio=args.aspect_ratio,
            turbo_mode=not args.no_turbo,
            realism_lora=args.realism,
            seed=args.seed,
            async_mode=args.async_mode
        )
        
        print("\n✅ Done!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
