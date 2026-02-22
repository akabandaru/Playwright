import os
import json
import time
import uuid
import asyncio
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from services.scene_decomposer import decompose_scene
from services.elevenlabs_service import generate_voices_and_sfx
from services.video_service import render_video
from services.figma_service import (
    create_figma_storyboard,
    update_beat_in_figma,
    register_plugin_mapping,
    get_node_mapping,
    get_plugin_payload,
    get_all_mappings,
    remove_storyboard_mapping,
)
from services.image_provider_models import ImageProviderBeatPayload
from services.image_provider_service import (
    generate_beat_image,
    save_generated_image,
)
from services.databricks_service import (
    end_run,
    log_metric,
    log_inference,
)

app = FastAPI(
    title="PLAYWRIGHT API",
    description="From script to screen in seconds",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        # Figma plugin sandbox runs with a null origin — must be allowed for
        # code.js fetch() calls to reach the backend.
        "null",
    ],
    allow_origin_regex=r"https://.*\.figma\.com",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_DIR = Path(__file__).parent / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)
IMAGES_DIR = OUTPUT_DIR / "images"
IMAGES_DIR.mkdir(exist_ok=True)
VIDEOS_DIR = OUTPUT_DIR / "videos"
VIDEOS_DIR.mkdir(exist_ok=True)
AUDIO_DIR = Path(__file__).parent / "temp"
AUDIO_DIR.mkdir(exist_ok=True)


class ScriptRequest(BaseModel):
    script: str
    genre_preset: Optional[str] = "none"
    style_mode: Optional[str] = "photoreal"


class Beat(BaseModel):
    beat_number: int
    visual_description: str
    camera_angle: str
    mood: str
    lighting: str
    characters_present: List[str] = []
    narrator_line: str
    music_recommendation: Optional[str] = None
    music_style: Optional[str] = None
    imageUrl: Optional[str] = None
    image_url: Optional[str] = None


class FigmaExportRequest(BaseModel):
    beats: List[Beat]
    storyboard_id: Optional[str] = None
    target_file_key: Optional[str] = None


class FigmaBeatUpdateRequest(BaseModel):
    beat: Beat


class FigmaPluginMappingBeatNode(BaseModel):
    beat_number: int
    frame_node_id: str
    image_node_id: str = ""
    label_node_id: str = ""
    meta_node_id: str = ""


class FigmaPluginMappingRequest(BaseModel):
    file_key: str
    file_url: str
    page_id: str
    page_name: str = "Storyboard"
    beat_nodes: List[FigmaPluginMappingBeatNode]


@app.get("/")
async def root():
    return {"message": "Welcome to PLAYWRIGHT API", "version": "1.0.0"}


def _normalize_style_mode(style_mode: Optional[str]) -> str:
    value = (style_mode or "photoreal").strip().lower().replace("-", "").replace("_", "")
    aliases = {
        "photoreal": "photoreal",
        "photo": "photoreal",
        "realistic": "photoreal",
        "anime": "anime",
        "cartoon": "anime",
        "manga": "anime",
    }
    return aliases.get(value, "photoreal")


def _normalize_genre_preset(genre_preset: Optional[str]) -> str:
    value = (genre_preset or "none").strip().lower().replace("-", "").replace("_", "")
    aliases = {
        "none": "none",
        "default": "none",
        "noir": "noir",
        "thriller": "thriller",
        "romcom": "romcom",
        "romanticcomedy": "romcom",
    }
    return aliases.get(value, "none")


def _assign_character_seeds(beats: list[dict]) -> dict[str, int]:
    """
    Assign one stable seed per character name, derived deterministically from
    the name itself. Every beat that contains that character will use the same
    seed, so the diffusion model starts from the same noise state and produces
    consistent facial structure, body proportions, and clothing across all beats.

    The seed is a 31-bit positive integer (FLUX accepts 1–2_147_483_647).
    Using hashlib keeps it stable across Python runs (unlike hash()).
    """
    import hashlib

    char_seeds: dict[str, int] = {}
    all_names: set[str] = set()
    for beat in beats:
        all_names.update(beat.get("characters_present", []))

    for name in all_names:
        digest = int(hashlib.sha256(name.encode()).hexdigest(), 16)
        char_seeds[name] = (digest % 2_147_483_646) + 1  # clamp to [1, 2^31-1]

    return char_seeds


def _pick_beat_seed(beat: dict, char_seeds: dict[str, int], scene_seed: int) -> int:
    """
    Return the seed to use for this beat.

    Priority:
      1. If one character is present → use that character's seed.
      2. If multiple characters are present → use the seed of the first listed
         (the "dominant" character in the beat).
      3. No characters → use the scene seed so environment stays consistent.
    """
    present = beat.get("characters_present", [])
    for name in present:
        if name in char_seeds:
            return char_seeds[name]
    return scene_seed


def _build_diffusion_prompt(
    beat: dict,
    scene_context: dict,
    char_desc_map: dict,
) -> str:
    """
    Assemble a single, complete diffusion prompt from all available context.

    The image provider server only uses visual_description — everything else
    (mood, lighting, color_palette, character descriptions, scene style) must
    be baked directly into this string. FLUX.1-schnell responds best to dense,
    comma-separated tag-style prompts.

    Character descriptions are placed FIRST so the model weights them most
    heavily — this is the primary lever for appearance consistency alongside
    seed locking.
    """
    parts: list[str] = []

    # ── 1. Character physical descriptions FIRST (highest model weight) ───────
    for name in beat.get("characters_present", []):
        desc = char_desc_map.get(name, "").strip()
        if desc:
            parts.append(desc)

    # ── 2. Core visual description from Gemini ────────────────────────────────
    visual = beat.get("visual_description", "").strip()
    if visual:
        parts.append(visual)

    # ── 3. Lighting ───────────────────────────────────────────────────────────
    lighting = beat.get("lighting", "").strip()
    if lighting:
        parts.append(f"{lighting} lighting")

    # ── 4. Mood as atmosphere tag ─────────────────────────────────────────────
    mood = beat.get("mood", "").strip()
    if mood and mood != "default":
        parts.append(f"{mood} atmosphere")

    # ── 5. Color palette ──────────────────────────────────────────────────────
    palette = beat.get("color_palette", "").strip()
    if palette:
        parts.append(palette)

    # ── 6. Foreground depth cue ───────────────────────────────────────────────
    fg = beat.get("foreground_elements", "").strip()
    if fg:
        parts.append(fg)

    # ── 7. Scene-level style (film stock + color grade + visual style) ────────
    sc = scene_context or {}
    style_tags: list[str] = []
    if sc.get("visual_style"):
        style_tags.append(sc["visual_style"])
    if sc.get("film_stock"):
        style_tags.append(sc["film_stock"])
    if sc.get("color_grade"):
        style_tags.append(sc["color_grade"])
    if sc.get("genre"):
        style_tags.append(sc["genre"])
    if sc.get("era"):
        style_tags.append(sc["era"])
    if style_tags:
        parts.append(", ".join(style_tags))

    # ── 8. Cinematic quality tail ─────────────────────────────────────────────
    parts.append("cinematic composition, professional photography, highly detailed, sharp focus")

    return ", ".join(p for p in parts if p)


def _build_negative_prompt(scene_context: dict, beat: dict) -> Optional[str]:
    """Merge scene-level and beat-level negative prompt hints."""
    global_neg = (scene_context or {}).get("negative_space", "")
    beat_neg = beat.get("negative_prompt_hints", "")
    combined = ", ".join(filter(None, [global_neg, beat_neg]))
    return combined if combined else None


async def generate_images_for_beats(beats: List[dict], style_mode: str = "photoreal") -> List[dict]:
    """Generate images for all beats using the image provider."""
    image_results = []
    normalized_style = _normalize_style_mode(style_mode)
    
    for beat in beats:
        payload = ImageProviderBeatPayload(
            beat_number=beat.get("beat_number", 0),
            visual_description=beat.get("visual_description", ""),
            camera_angle=beat.get("camera_angle", ""),
            mood=beat.get("mood", ""),
            lighting=beat.get("lighting", ""),
            characters_present=beat.get("characters_present", []),
            narrator_line=beat.get("narrator_line", ""),
            music_style=beat.get("music_style") or beat.get("music_recommendation"),
            style_mode=normalized_style,
        )
        
        result = await generate_beat_image(payload)
        request_id = result.metadata.get("request_id") or uuid.uuid4().hex
        filename_hint = f"beat_{beat.get('beat_number', 0)}_{request_id}"
        image_path = save_generated_image(result.image_bytes, filename_hint, IMAGES_DIR)
        image_url = f"/api/image/{image_path.name}"
        
        image_results.append({
            "beat_number": beat.get("beat_number", 0),
            "image_url": image_url,
        })
    
    return image_results


@app.post("/api/generate-video")
async def api_generate_video(request: ScriptRequest):
    """
    Full pipeline: analyze script → generate visuals + narration in parallel → render video.
    Uses Server-Sent Events (SSE) to stream progress updates to the frontend.
    """
    if not request.script.strip():
        raise HTTPException(status_code=400, detail="Script cannot be empty")

    def _sse_json(obj) -> str:
        """json.dumps with a fallback encoder that stringifies non-serializable types (e.g. PosixPath)."""
        from pathlib import PurePath
        def _default(o):
            if isinstance(o, PurePath):
                return str(o)
            raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")
        return json.dumps(obj, default=_default)

    async def generate():
        pipeline_start = time.time()
        normalized_style = _normalize_style_mode(request.style_mode)
        normalized_genre = _normalize_genre_preset(request.genre_preset)
        
        try:
            # Stage 1: Analyze script
            print("\n[PIPELINE]: Analyzing script...")
            yield f"data: {_sse_json({'stage': 'analyzing', 'message': 'Analyzing script...'})}\n\n"
            
            result = await decompose_scene(
                request.script,
                genre_preset=normalized_genre,
                style_mode=normalized_style,
            )
            beats = result["beats"]
            character_bible = result.get("character_bible", [])
            scene_context = result.get("scene_context", {})

            # Build a lookup from character name → physical description for prompt injection
            char_desc_map = {
                entry["name"]: entry["description"]
                for entry in character_bible
                if isinstance(entry, dict) and entry.get("name") and entry.get("description")
            }

            # Assign one stable seed per character (derived from their name) so every
            # beat featuring the same character starts from the same noise state,
            # producing consistent appearance across the whole storyboard.
            char_seeds = _assign_character_seeds(beats)

            # Scene seed: used for beats with no characters (environment/establishing shots).
            # Derived from the script text so the world looks consistent too.
            import hashlib as _hl
            scene_seed = (int(_hl.sha256(request.script[:512].encode()).hexdigest(), 16) % 2_147_483_646) + 1

            if char_seeds:
                print(f"[PIPELINE] Character seeds: { {n: s for n, s in char_seeds.items()} }")

            yield f"data: {_sse_json({'stage': 'analyzing', 'message': f'Found {len(beats)} beats', 'beats': beats})}\n\n"
            
            # Stage 2: Generate visuals and narration in parallel
            print("[PIPELINE]: Generating visuals and narration (parallel)...")
            yield f"data: {_sse_json({'stage': 'generating', 'message': 'Generating visuals and narration...'})}\n\n"
            
            # Start voice generation in background
            voice_task = asyncio.create_task(generate_voices_and_sfx(beats))
            
            # Generate images one by one and stream each as it completes
            for i, beat in enumerate(beats):
                print(f"[PIPELINE]: Generating image {i+1}/{len(beats)}...")

                # Assemble the full diffusion prompt — the server only uses visual_description
                diffusion_prompt = _build_diffusion_prompt(beat, scene_context, char_desc_map)
                negative = _build_negative_prompt(scene_context, beat)

                # Pick seed: character seed if any character present, else scene seed
                beat_seed = _pick_beat_seed(beat, char_seeds, scene_seed)
                present = beat.get("characters_present", [])
                seed_source = present[0] if present else "scene"
                print(f"  Prompt ({len(diffusion_prompt)} chars): {diffusion_prompt[:120]}...")
                print(f"  Seed: {beat_seed} (from: {seed_source}) | Camera: {beat.get('camera_angle', '')} | Mood: {beat.get('mood', '')}")
                yield f"data: {_sse_json({'stage': 'generating', 'message': f'Generating image {i+1} of {len(beats)}...'})}\n\n"

                payload = ImageProviderBeatPayload(
                    beat_number=beat.get("beat_number", 0),
                    visual_description=diffusion_prompt,
                    camera_angle=beat.get("camera_angle", ""),
                    mood=beat.get("mood", ""),
                    lighting=beat.get("lighting", ""),
                    characters_present=beat.get("characters_present", []),
                    narrator_line=beat.get("narrator_line", ""),
                    music_style=beat.get("music_style") or beat.get("music_recommendation"),
                    negative_prompt=negative,
                    steps=20,
                    guidance_scale=7.0,
                    seed=beat_seed,
                    style_mode=normalized_style,
                )
                
                result = await generate_beat_image(payload)
                request_id = result.metadata.get("request_id") or uuid.uuid4().hex
                filename_hint = f"beat_{beat.get('beat_number', 0)}_{request_id}"
                image_path = save_generated_image(result.image_bytes, filename_hint, IMAGES_DIR)
                image_url = f"/api/image/{str(image_path.name)}"
                
                print(f"  ✓ Image saved: {image_url}")
                
                # Update beat with image URL
                beat["imageUrl"] = image_url
                beat["image_url"] = image_url

                # Stream the updated beat immediately
                yield f"data: {_sse_json({'stage': 'generating', 'message': f'Image {i+1} of {len(beats)} complete', 'beatUpdate': {'index': i, 'beat': beat}})}\n\n"
            
            # Wait for voice generation to complete
            audio_results = await voice_task
            
            # Attach audio paths to beats (str() guards against PosixPath values)
            audio_map = {a["beat_number"]: str(a.get("audio_path", "")) for a in audio_results if a.get("audio_path")}
            for beat in beats:
                beat_num = beat.get("beat_number", 0)
                if beat_num in audio_map:
                    beat["audio_path"] = audio_map[beat_num]
            
            # Get music recommendation from first beat that has one
            music_rec = None
            for beat in beats:
                if beat.get("music_recommendation") or beat.get("music_style"):
                    music_rec = beat.get("music_recommendation") or beat.get("music_style")
                    break

            yield f"data: {_sse_json({'stage': 'generating', 'message': 'Visuals and narration complete', 'beats': beats})}\n\n"
            
            # Stage 3: Render video
            print("[PIPELINE]: Rendering video...")
            yield f"data: {_sse_json({'stage': 'rendering', 'message': 'Rendering video...'})}\n\n"
            
            video_result = await render_video(beats=beats, audio_files=audio_results)
            print(f"[PIPELINE] complete")
            
            video_url = f"/api/video/{video_result['filename']}"
            
            pipeline_latency = time.time() - pipeline_start
            log_metric("total_pipeline_latency", pipeline_latency)
            
            # Log inference data
            moods = [b.get("mood", "") for b in beats]
            cameras = [b.get("camera_angle", "") for b in beats]
            log_inference(
                script=request.script[:500],
                beats_count=len(beats),
                moods=moods,
                camera_angles=cameras,
                pipeline_latency=pipeline_latency,
            )
            
            end_run("FINISHED")
            
            print(f"[PIPELINE] COMPLETE in {pipeline_latency:.2f}s - Video: {video_url}\n")
            
            # Final result
            yield f"data: {_sse_json({'stage': 'complete', 'message': 'Video ready!', 'videoUrl': video_url, 'beats': beats, 'duration': video_result.get('duration', 0), 'pipelineTime': pipeline_latency})}\n\n"
            
        except Exception as e:
            print(f"[PIPELINE] ERROR: {str(e)}")
            import traceback
            traceback.print_exc()
            end_run("FAILED")
            yield f"data: {_sse_json({'stage': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )

async def generate_images_for_beats(beats: List[dict]) -> List[dict]:
    """Generate images for all beats using the image provider."""
    image_results = []
    
    for beat in beats:
        payload = ImageProviderBeatPayload(
            beat_number=beat.get("beat_number", 0),
            visual_description=beat.get("visual_description", ""),
            camera_angle=beat.get("camera_angle", ""),
            mood=beat.get("mood", ""),
            lighting=beat.get("lighting", ""),
            characters_present=beat.get("characters_present", []),
            narrator_line=beat.get("narrator_line", ""),
            music_style=beat.get("music_style") or beat.get("music_recommendation"),
        )
        
        result = await generate_beat_image(payload)
        request_id = result.metadata.get("request_id") or uuid.uuid4().hex
        filename_hint = f"beat_{beat.get('beat_number', 0)}_{request_id}"
        image_path = save_generated_image(result.image_bytes, filename_hint, IMAGES_DIR)
        image_url = f"/api/image/{image_path.name}"
        
        image_results.append({
            "beat_number": beat.get("beat_number", 0),
            "image_url": image_url,
        })
    
    return image_results

@app.get("/api/video/{filename}")
async def api_get_video(filename: str):
    """Serve rendered video files for playback and download."""
    video_path = VIDEOS_DIR / filename
    
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    
    return FileResponse(
        path=str(video_path),
        media_type="video/mp4",
        filename=filename,
    )

@app.get("/api/image/{filename}")
async def api_get_image(filename: str):
    """Serve generated image files for frontend preview."""
    image_path = IMAGES_DIR / filename

    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(
        path=str(image_path),
        media_type="image/png",
        filename=filename,
    )

@app.get("/api/audio/{filepath:path}")
async def api_get_audio(filepath: str):
    """Serve generated audio files for frontend preview."""
    # Handle both full paths and just filenames
    if filepath.startswith("/"):
        audio_path = Path(filepath)
    else:
        audio_path = AUDIO_DIR / filepath
    
    # Also check in the path directly if it's an absolute path
    if not audio_path.exists() and "/" in filepath:
        audio_path = Path(filepath)

    if not audio_path.exists():
        raise HTTPException(status_code=404, detail=f"Audio not found: {filepath}")

    return FileResponse(
        path=str(audio_path),
        media_type="audio/mpeg",
        filename=audio_path.name,
    )


# For Figma Plugin
@app.post("/api/export-figma")
async def api_export_figma(request: FigmaExportRequest):
    """
    Export storyboard to Figma.

    Resolution order for the target file:
      1. request.target_file_key  (explicit override)
      2. FIGMA_TEMPLATE_FILE_KEY  env var  →  one-click template mode
      3. Neither set              →  returns plugin payload JSON

    Response always includes storyboard_id which the frontend uses to build
    the figma:// deep link that opens the plugin pre-filled.
    """
    if not request.beats:
        raise HTTPException(status_code=400, detail="Beats array cannot be empty")

    try:
        beats_dict = [b.model_dump() for b in request.beats]
        result = await create_figma_storyboard(
            beats_dict,
            storyboard_id=request.storyboard_id,
            target_file_key=request.target_file_key,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/export-figma/{storyboard_id}/beat/{beat_number}")
async def api_update_figma_beat(
    storyboard_id: str,
    beat_number: int,
    request: FigmaBeatUpdateRequest,
):
    """
    Selectively update a single beat's image in Figma without re-exporting
    the whole storyboard. Requires a prior full export so node IDs are stored.
    """
    try:
        beat_dict = request.beat.model_dump()
        result = await update_beat_in_figma(storyboard_id, beat_number, beat_dict)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/export-figma/{storyboard_id}/mapping")
async def api_register_plugin_mapping(
    storyboard_id: str,
    request: FigmaPluginMappingRequest,
):
    """
    Called by the Figma plugin after it creates the file client-side.
    Registers the file_key and per-beat node IDs so future selective
    updates via PATCH /beat/{n} work without re-importing.
    """
    try:
        beat_nodes = [bn.model_dump() for bn in request.beat_nodes]
        result = await register_plugin_mapping(
            storyboard_id,
            file_key=request.file_key,
            file_url=request.file_url,
            page_id=request.page_id,
            page_name=request.page_name,
            beat_nodes=beat_nodes,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/export-figma/{storyboard_id}/mapping")
async def api_get_figma_mapping(storyboard_id: str):
    """
    Retrieve the full Figma node mapping for a storyboard.

    Returns file_key, file_url, and per-beat node IDs (frame, image, label, meta).
    Useful for debugging or for the plugin to verify registered nodes.
    """
    try:
        return get_node_mapping(storyboard_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/export-figma/{storyboard_id}/payload")
async def api_get_figma_payload(storyboard_id: str):
    """
    Return the plugin payload for a storyboard.

    Called by the PLAYWRIGHT Figma plugin to fetch the frame layout and
    image data it needs to create the storyboard file client-side.
    Only available for storyboards exported in plugin_payload mode.
    """
    try:
        return get_plugin_payload(storyboard_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/export-figma")
async def api_list_figma_mappings():
    """
    List all storyboards that have been exported to Figma.

    Returns a summary (file_key, file_url, beat_count, timestamps) for each.
    """
    return get_all_mappings()


@app.delete("/api/export-figma/{storyboard_id}/mapping")
async def api_delete_figma_mapping(storyboard_id: str):
    """
    Delete the Figma node mapping for a storyboard.

    Does NOT delete the Figma file itself — only removes the local mapping record.
    """
    deleted = remove_storyboard_mapping(storyboard_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"No mapping found for storyboard '{storyboard_id}'",
        )
    return {"deleted": True, "storyboard_id": storyboard_id}


class FigmaTemplateRequest(BaseModel):
    file_key: str


@app.post("/api/figma-template")
async def api_set_figma_template(request: FigmaTemplateRequest):
    """
    Save a Figma template file key to the .env file so future exports
    patch into that template. Called by the plugin after it creates a
    new template via the 'Setup Template' button.
    """
    file_key = request.file_key.strip()
    if not file_key:
        raise HTTPException(status_code=400, detail="file_key is required")

    env_path = Path(__file__).parent / ".env"
    try:
        lines = env_path.read_text().splitlines() if env_path.exists() else []
        updated = False
        new_lines = []
        for line in lines:
            if line.startswith("FIGMA_TEMPLATE_FILE_KEY=") or line.startswith("#FIGMA_TEMPLATE_FILE_KEY="):
                new_lines.append(f"FIGMA_TEMPLATE_FILE_KEY={file_key}")
                updated = True
            else:
                new_lines.append(line)
        if not updated:
            new_lines.append(f"FIGMA_TEMPLATE_FILE_KEY={file_key}")
        env_path.write_text("\n".join(new_lines) + "\n")

        # Also update the running process environment so it takes effect immediately
        os.environ["FIGMA_TEMPLATE_FILE_KEY"] = file_key

        return {"saved": True, "file_key": file_key}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not write .env: {exc}")


@app.get("/api/figma-template")
async def api_get_figma_template():
    """Return the currently configured Figma template file key."""
    key = os.getenv("FIGMA_TEMPLATE_FILE_KEY", "").strip()
    return {"file_key": key or None}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
