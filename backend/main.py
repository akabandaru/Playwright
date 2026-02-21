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
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_DIR = Path(__file__).parent / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)
IMAGES_DIR = OUTPUT_DIR / "images"
IMAGES_DIR.mkdir(exist_ok=True)
VIDEOS_DIR = OUTPUT_DIR / "videos"
VIDEOS_DIR.mkdir(exist_ok=True)


class ScriptRequest(BaseModel):
    script: str


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


@app.post("/api/generate-video")
async def api_generate_video(request: ScriptRequest):
    """
    Full pipeline: analyze script → generate visuals + narration in parallel → render video.
    Uses Server-Sent Events (SSE) to stream progress updates to the frontend.
    """
    if not request.script.strip():
        raise HTTPException(status_code=400, detail="Script cannot be empty")

    async def generate():
        pipeline_start = time.time()
        
        try:
            # Stage 1: Analyze script
            print("\n[PIPELINE]: Analyzing script...")
            yield f"data: {json.dumps({'stage': 'analyzing', 'message': 'Analyzing script...'})}\n\n"
            
            result = await decompose_scene(request.script)
            beats = result["beats"]
            
            yield f"data: {json.dumps({'stage': 'analyzing', 'message': f'Found {len(beats)} beats', 'beats': beats})}\n\n"
            
            # Stage 2: Generate visuals and narration in parallel
            print("[PIPELINE]: Generating visuals and narration (parallel)...")
            yield f"data: {json.dumps({'stage': 'generating', 'message': 'Generating visuals and narration...'})}\n\n"
            
            # Start voice generation in background
            voice_task = asyncio.create_task(generate_voices_and_sfx(beats))
            
            # Generate images one by one and stream each as it completes
            for i, beat in enumerate(beats):
                print(f"[PIPELINE]: Generating image {i+1}/{len(beats)}...")
                print(f"  Visual: {beat.get('visual_description', '')[:100]}...")
                print(f"  Camera: {beat.get('camera_angle', '')} | Mood: {beat.get('mood', '')} | Lighting: {beat.get('lighting', '')}")
                yield f"data: {json.dumps({'stage': 'generating', 'message': f'Generating image {i+1} of {len(beats)}...'})}\n\n"
                
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
                
                print(f"  ✓ Image saved: {image_url}")
                
                # Update beat with image URL
                beat["imageUrl"] = image_url
                beat["image_url"] = image_url
                
                # Stream the updated beat immediately
                yield f"data: {json.dumps({'stage': 'generating', 'message': f'Image {i+1} of {len(beats)} complete', 'beatUpdate': {'index': i, 'beat': beat}})}\n\n"
            
            # Wait for voice generation to complete
            audio_results = await voice_task
            
            # Get music recommendation from first beat that has one
            music_rec = None
            for beat in beats:
                if beat.get("music_recommendation") or beat.get("music_style"):
                    music_rec = beat.get("music_recommendation") or beat.get("music_style")
                    break

            yield f"data: {json.dumps({'stage': 'generating', 'message': 'Visuals and narration complete', 'beats': beats})}\n\n"
            
            # Stage 3: Render video
            print("[PIPELINE]: Rendering video...")
            yield f"data: {json.dumps({'stage': 'rendering', 'message': 'Rendering video...'})}\n\n"
            
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
            yield f"data: {json.dumps({'stage': 'complete', 'message': 'Video ready!', 'videoUrl': video_url, 'beats': beats, 'musicRecommendation': music_rec, 'duration': video_result.get('duration', 0), 'pipelineTime': pipeline_latency})}\n\n"
            
        except Exception as e:
            print(f"[PIPELINE] ERROR: {str(e)}")
            import traceback
            traceback.print_exc()
            end_run("FAILED")
            yield f"data: {json.dumps({'stage': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
