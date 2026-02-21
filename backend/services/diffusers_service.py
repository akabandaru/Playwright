import asyncio
import base64
import io
import os
import time
from typing import Any, Dict, List

import torch
from diffusers import DPMSolverMultistepScheduler, StableDiffusionXLPipeline


NEGATIVE_PROMPT = (
    "cartoon, anime, illustration, blurry, text, watermark, "
    "oversaturated, bad anatomy, extra fingers, deformed"
)

STYLE_PREFIX = (
    "photoreal cinematic still, 35mm film look, natural skin texture, soft film grain, "
    "high dynamic range, moody practical lighting, shallow depth of field, professional color grading"
)

SHOT = {
    "ECU": "extreme close-up, only eyes/lips detail, face fills frame, very shallow depth of field, 85mm lens",
    "CU": "close-up portrait, head and shoulders, face dominates frame, shallow depth of field, 85mm lens",
    "MS": "medium shot, waist-up, subject centered, 50mm lens, natural perspective",
    "FS": "full body shot, full body visible, subject clearly framed, 35mm lens",
    "LS": "wide establishing shot, subject small in frame, environment dominant, 24mm lens",
}


_pipeline: StableDiffusionXLPipeline | None = None
_pipeline_device: str | None = None
_pipeline_init_lock = asyncio.Lock()
_generation_lock = asyncio.Lock()


def _is_single_file_checkpoint(model_ref: str) -> bool:
    lower = model_ref.lower()
    return lower.endswith(".safetensors") or lower.endswith(".ckpt")


def _build_pipeline() -> tuple[StableDiffusionXLPipeline, str]:
    model_ref = os.getenv("SD_MODEL_PATH", "stabilityai/stable-diffusion-xl-base-1.0")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32

    if _is_single_file_checkpoint(model_ref):
        pipe = StableDiffusionXLPipeline.from_single_file(
            model_ref,
            torch_dtype=dtype,
            use_safetensors=model_ref.lower().endswith(".safetensors"),
        )
    else:
        if device == "cuda":
            try:
                pipe = StableDiffusionXLPipeline.from_pretrained(
                    model_ref,
                    torch_dtype=dtype,
                    variant="fp16",
                    use_safetensors=True,
                )
            except Exception:
                pipe = StableDiffusionXLPipeline.from_pretrained(
                    model_ref,
                    torch_dtype=dtype,
                )
        else:
            pipe = StableDiffusionXLPipeline.from_pretrained(
                model_ref,
                torch_dtype=dtype,
            )

    pipe.scheduler = DPMSolverMultistepScheduler.from_config(
        pipe.scheduler.config,
        use_karras_sigmas=True,
    )
    pipe.to(device)

    if device == "cuda":
        pipe.enable_attention_slicing()
        pipe.enable_vae_slicing()
        try:
            pipe.enable_xformers_memory_efficient_attention()
        except Exception:
            pass

    return pipe, device


async def _get_pipeline() -> tuple[StableDiffusionXLPipeline, str]:
    global _pipeline
    global _pipeline_device

    if _pipeline is not None and _pipeline_device is not None:
        return _pipeline, _pipeline_device

    async with _pipeline_init_lock:
        if _pipeline is None or _pipeline_device is None:
            _pipeline, _pipeline_device = await asyncio.to_thread(_build_pipeline)

    return _pipeline, _pipeline_device


def _resolve_shot(camera_angle: str) -> str:
    angle = (camera_angle or "").lower()
    if "extreme close" in angle or "ecu" in angle:
        return "ECU"
    if "close" in angle or "cu" in angle:
        return "CU"
    if "full" in angle or "fs" in angle:
        return "FS"
    if "long" in angle or "wide" in angle or "ls" in angle:
        return "LS"
    return "MS"


def build_image_prompt(beat: Dict[str, Any]) -> str:
    visual = beat.get("visual_description", "")
    mood = beat.get("mood", "cinematic")
    lighting = beat.get("lighting", "natural")
    shot_type = _resolve_shot(beat.get("camera_angle", ""))

    return f"{STYLE_PREFIX}, {visual}, {mood} mood, {lighting} lighting, {SHOT[shot_type]}"


async def _txt2img(prompt: str) -> str:
    width = int(os.getenv("SD_WIDTH", "1024"))
    height = int(os.getenv("SD_HEIGHT", "576"))
    steps = int(os.getenv("SD_STEPS", "22"))
    cfg_scale = float(os.getenv("SD_CFG_SCALE", "6.5"))

    pipe, _ = await _get_pipeline()

    def _run_generation() -> str:
        result = pipe(
            prompt=prompt,
            negative_prompt=NEGATIVE_PROMPT,
            width=width,
            height=height,
            num_inference_steps=steps,
            guidance_scale=cfg_scale,
        )
        image = result.images[0]
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{encoded}"

    async with _generation_lock:
        return await asyncio.to_thread(_run_generation)


async def generate_single_image(beat: Dict[str, Any], beat_index: int) -> Dict[str, Any]:
    prompt = build_image_prompt(beat)
    start_time = time.time()

    image_data_url = await _txt2img(prompt)
    latency = time.time() - start_time

    return {
        "beat_number": beat.get("beat_number", beat_index + 1),
        "image_url": image_data_url,
        "latency": latency,
    }


async def generate_images(beats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    processed_results = []
    for idx, beat in enumerate(beats):
        try:
            result = await generate_single_image(beat, idx)
            processed_results.append(result)
        except Exception as exc:
            processed_results.append(
                {
                    "beat_number": beats[idx].get("beat_number", idx + 1),
                    "image_url": None,
                    "error": str(exc),
                }
            )

    return processed_results
