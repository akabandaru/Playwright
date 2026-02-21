import os
import asyncio
import replicate
import time
from typing import List, Dict, Any

NEGATIVE_PROMPT = "cartoon, anime, illustration, blurry, text, watermark, oversaturated, bad anatomy"

def build_image_prompt(beat: Dict[str, Any]) -> str:
    """Construct the image generation prompt from beat data."""
    visual = beat.get("visual_description", "")
    camera = beat.get("camera_angle", "medium shot")
    mood = beat.get("mood", "cinematic")
    lighting = beat.get("lighting", "natural")
    
    return f"film still, {visual}, {camera}, {mood} lighting, {lighting}, 35mm photography, cinematic color grading, ultra detailed, sharp focus"

async def generate_single_image(beat: Dict[str, Any], beat_index: int) -> Dict[str, Any]:
    """Generate a single image for a beat using SDXL."""
    prompt = build_image_prompt(beat)
    
    start_time = time.time()
    
    output = await asyncio.to_thread(
        replicate.run,
        "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",
        input={
            "prompt": prompt,
            "negative_prompt": NEGATIVE_PROMPT,
            "width": 1280,
            "height": 720,
            "num_outputs": 1,
            "scheduler": "K_EULER",
            "num_inference_steps": 30,
            "guidance_scale": 7.5,
            "refine": "expert_ensemble_refiner",
            "high_noise_frac": 0.8,
        }
    )
    
    latency = time.time() - start_time
    
    image_url = output[0] if isinstance(output, list) else str(output)
    
    return {
        "beat_number": beat.get("beat_number", beat_index + 1),
        "image_url": image_url,
        "latency": latency,
    }

async def generate_images(beats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Generate images for all beats in parallel."""
    tasks = [
        generate_single_image(beat, idx) 
        for idx, beat in enumerate(beats)
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    processed_results = []
    for idx, result in enumerate(results):
        if isinstance(result, Exception):
            processed_results.append({
                "beat_number": beats[idx].get("beat_number", idx + 1),
                "image_url": None,
                "error": str(result),
            })
        else:
            processed_results.append(result)
    
    return processed_results
