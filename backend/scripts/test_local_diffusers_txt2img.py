import os
from pathlib import Path

import torch
from diffusers import DPMSolverMultistepScheduler, StableDiffusionXLPipeline


OUTPUT_FILE = Path(__file__).resolve().parent / "frame.png"
MODEL_REF = os.getenv("SD_MODEL_PATH", "stabilityai/stable-diffusion-xl-base-1.0")

STYLE_PREFIX = (
    "photoreal cinematic still, 35mm film look, natural skin texture, soft film grain, "
    "high dynamic range, moody practical lighting, shallow depth of field, professional color grading"
)

SHOT = {
    "ECU": "extreme close-up, 85mm lens, only eyes/lips detail, very shallow depth of field",
    "CU": "close-up portrait, head and shoulders, 85mm lens",
    "MS": "medium shot, waist-up, 50mm lens",
    "FS": "full body shot, 35mm lens",
    "LS": "wide establishing shot, subject small in frame, 24mm lens",
}


def build_shot_prompt(beat_text: str, shot_type: str) -> str:
    shot_key = shot_type.upper()
    if shot_key not in SHOT:
        raise ValueError(f"Unsupported shot_type '{shot_type}'. Use one of: {', '.join(SHOT)}")
    return f"{STYLE_PREFIX}, {beat_text}, {SHOT[shot_key]}"


def is_single_file_checkpoint(model_ref: str) -> bool:
    lower = model_ref.lower()
    return lower.endswith(".safetensors") or lower.endswith(".ckpt")


def load_pipeline() -> tuple[StableDiffusionXLPipeline, str]:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32

    if is_single_file_checkpoint(MODEL_REF):
        pipe = StableDiffusionXLPipeline.from_single_file(
            MODEL_REF,
            torch_dtype=dtype,
            use_safetensors=MODEL_REF.lower().endswith(".safetensors"),
        )
    else:
        if device == "cuda":
            try:
                pipe = StableDiffusionXLPipeline.from_pretrained(
                    MODEL_REF,
                    torch_dtype=dtype,
                    variant="fp16",
                    use_safetensors=True,
                )
            except Exception:
                pipe = StableDiffusionXLPipeline.from_pretrained(MODEL_REF, torch_dtype=dtype)
        else:
            pipe = StableDiffusionXLPipeline.from_pretrained(MODEL_REF, torch_dtype=dtype)

    pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, use_karras_sigmas=True)
    pipe.to(device)

    if device == "cuda":
        pipe.enable_attention_slicing()
        pipe.enable_vae_slicing()
        try:
            pipe.enable_xformers_memory_efficient_attention()
        except Exception:
            pass

    return pipe, device


def main() -> None:
    pipe, device = load_pipeline()
    print(f"Using model: {MODEL_REF}")
    print(f"Using device: {device}")

    prompt = build_shot_prompt(
        "interior diner at night, neon reflections on wet window, a woman grips a coffee cup during a tense conversation",
        "CU",
    )

    result = pipe(
        prompt=prompt,
        negative_prompt="cartoon, anime, illustration, blurry, text, watermark, oversaturated, bad anatomy",
        width=1024,
        height=576,
        num_inference_steps=22,
        guidance_scale=6.5,
    )

    image = result.images[0]
    image.save(OUTPUT_FILE)
    print(f"Saved image to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
