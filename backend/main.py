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
from services.figma_service import create_figma_storyboard
from services.image_provider_models import GenerateFrameRequest, ImageProviderBeatPayload
from services.image_provider_service import (
    ImageProviderClientError,
    check_image_provider_health,
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


@app.get("/")
async def root():
    return {"message": "Welcome to PLAYWRIGHT API", "version": "1.0.0"}


@app.post("/api/generate-video")
async def api_generate_video(request: ScriptRequest):
    """
    Full pipeline: analyze script → generate visuals + narration in parallel → render video.
    Uses Server-Sent Events (SSE) to stream progress updates to the frontend.
    """
    if not request.script.strip():
        raise HTTPException(status_code=400, detail="Script cannot be empty")

    try:
        result = await decompose_scene(request.script)
        return {"beats": result["beats"], "run_id": result["run_id"]}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/generate-images")
async def api_generate_images(request: BeatsRequest):
    """
    Generate images for each beat using external image provider API.
    """
    if not request.beats:
        raise HTTPException(status_code=400, detail="Beats array cannot be empty")
    
    start_time = time.time()
    
    try:
        beats_dict = [b.model_dump() for b in request.beats]
        image_results = []

        for beat in request.beats:
            payload = ImageProviderBeatPayload(
                beat_number=beat.beat_number,
                visual_description=beat.visual_description,
                camera_angle=beat.camera_angle,
                mood=beat.mood,
                lighting=beat.lighting,
                characters_present=beat.characters_present,
                narrator_line=beat.narrator_line,
                music_style=beat.music_style or beat.music_recommendation,
            )

            result = await generate_beat_image(payload)
            request_id = result.metadata.get("request_id") or uuid.uuid4().hex
            filename_hint = f"beat_{beat.beat_number}_{request_id}"
            image_path = save_generated_image(result.image_bytes, filename_hint, IMAGES_DIR)
            image_url = f"/api/image/{image_path.name}"

            image_results.append(
                {
                    "beat_number": beat.beat_number,
                    "image_url": image_url,
                    "provider_metadata": result.metadata,
                }
            )
        
        latency = time.time() - start_time
        log_metric("image_generation_latency", latency)
        
        for beat, img_result in zip(beats_dict, image_results):
            beat["imageUrl"] = img_result.get("image_url")
            beat["image_url"] = img_result.get("image_url")
        
        return {
            "beats": beats_dict,
            "imageResults": image_results,
            "latency": latency,
        }
    
    except ImageProviderClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/generate-frame")
async def api_generate_frame(request: GenerateFrameRequest):
    """
    Generate a single frame from one beat via external image provider.
    """
    try:
        beat_payload = ImageProviderBeatPayload(**request.model_dump(exclude={"return_base64", "save_to_disk"}))
        result = await generate_beat_image(beat_payload)

        response: dict = {
            "metadata": result.metadata,
        }

        if request.save_to_disk:
            request_id = result.metadata.get("request_id") or uuid.uuid4().hex
            filename_hint = f"beat_{request.beat_number}_{request_id}"
            image_path = save_generated_image(result.image_bytes, filename_hint, IMAGES_DIR)
            response["fileUrl"] = f"/api/image/{image_path.name}"

        if request.return_base64:
            response["image_b64"] = result.image_b64

        return response
    except ImageProviderClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/image-provider-health")
async def api_image_provider_health():
    """
    Health pass-through for the external image provider tunnel.
    """
    try:
        data = await check_image_provider_health()
        return {"ok": True, "provider": data}
    except ImageProviderClientError as exc:
        raise HTTPException(status_code=503, detail=f"provider unreachable / tunnel not ready: {exc}")


@app.post("/api/generate-voice")
async def api_generate_voice(request: BeatsRequest):
    """
    Generate voice narration for each beat using ElevenLabs.
    Uses Rachel voice with specified settings.
    """
    if not request.beats:
        raise HTTPException(status_code=400, detail="Beats array cannot be empty")
    
    start_time = time.time()
    
    try:
        beats_dict = [b.model_dump() for b in request.beats]
        audio_results = await generate_voices(beats_dict)
        
        latency = time.time() - start_time
        log_metric("voice_generation_latency", latency)
        
        music_rec = None
        for beat in request.beats:
            if beat.music_recommendation:
                music_rec = beat.music_recommendation
                break
        
        return {
            "audioUrls": audio_results,
            "musicRecommendation": music_rec,
            "latency": latency,
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/generate-narration")
async def api_generate_narration(request: BeatsRequest):
    """Alias for generate-voice endpoint."""
    return await api_generate_voice(request)


@app.post("/api/render-video")
async def api_render_video(request: RenderRequest):
    """
    Render final video from images and audio.
    Applies Ken Burns effect and concatenates clips.
    """
    if not request.beats:
        raise HTTPException(status_code=400, detail="Beats array cannot be empty")
    
    start_time = time.time()
    
    try:
        beats_dict = [b.model_dump() for b in request.beats]
        
        result = await render_video(
            beats=beats_dict,
            audio_files=request.audioUrls,
        )
        
        latency = time.time() - start_time
        log_metric("render_latency", latency)
        log_metric("total_pipeline_latency", latency)
        
        moods = [b.get("mood", "") for b in beats_dict]
        cameras = [b.get("camera_angle", "") for b in beats_dict]
        log_inference(
            script="",
            beats_count=len(beats_dict),
            moods=moods,
            camera_angles=cameras,
            pipeline_latency=latency,
        )
        
        end_run("FINISHED")
        
        video_url = f"/api/video/{result['filename']}"
        
        return {
            "videoUrl": video_url,
            "filename": result["filename"],
            "duration": result.get("duration", 0),
            "renderTime": result.get("render_time", latency),
        }
    
    except Exception as e:
        end_run("FAILED")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/export-figma")
async def api_export_figma(request: FigmaExportRequest):
    """
    Export storyboard to Figma.
    Creates a new Figma file with frames for each beat.
    """
    if not request.beats:
        raise HTTPException(status_code=400, detail="Beats array cannot be empty")
    
    try:
        beats_dict = [b.model_dump() for b in request.beats]
        result = await create_figma_storyboard(beats_dict)
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    async def generate():
        pipeline_start = time.time()
        
        try:
            # Stage 1: Analyze script
            yield f"data: {json.dumps({'stage': 'analyzing', 'message': 'Analyzing script...'})}\n\n"
            
            result = await decompose_scene(request.script)
            beats = result["beats"]
            
            yield f"data: {json.dumps({'stage': 'analyzing', 'message': f'Found {len(beats)} beats', 'beats': beats})}\n\n"
            
            # Stage 2: Generate visuals and narration in parallel
            yield f"data: {json.dumps({'stage': 'generating', 'message': 'Generating visuals and narration...'})}\n\n"
            
            image_task = generate_images(beats)
            voice_task = generate_voices(beats)
            
            image_results, audio_results = await asyncio.gather(image_task, voice_task)
            
            # Merge image URLs into beats
            for beat, img_result in zip(beats, image_results):
                beat["imageUrl"] = img_result.get("image_url")
                beat["image_url"] = img_result.get("image_url")
            
            # Get music recommendation
            music_rec = None
            for beat in beats:
                if beat.get("music_recommendation"):
                    music_rec = beat["music_recommendation"]
                    break
            
            yield f"data: {json.dumps({'stage': 'generating', 'message': 'Visuals and narration complete', 'beats': beats})}\n\n"
            
            # Stage 3: Render video
            yield f"data: {json.dumps({'stage': 'rendering', 'message': 'Rendering video...'})}\n\n"
            
            video_result = await render_video(beats=beats, audio_files=audio_results)
            
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
            
            # Final result
            yield f"data: {json.dumps({'stage': 'complete', 'message': 'Video ready!', 'videoUrl': video_url, 'beats': beats, 'musicRecommendation': music_rec, 'duration': video_result.get('duration', 0), 'pipelineTime': pipeline_latency})}\n\n"
            
        except Exception as e:
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


@app.get("/api/video/{filename}")
async def api_get_video(filename: str):
    """Serve rendered video files for playback and download."""
    video_path = OUTPUT_DIR / filename
    
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    
    return FileResponse(
        path=str(video_path),
        media_type="video/mp4",
        filename=filename,
    )


@app.get("/api/image/{filename}")
async def api_get_image(filename: str):
    """
    Serve generated image files for frontend preview.
    """
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
    """Export storyboard to Figma."""
    if not request.beats:
        raise HTTPException(status_code=400, detail="Beats array cannot be empty")
    
    try:
        beats_dict = [b.model_dump() for b in request.beats]
        result = await create_figma_storyboard(beats_dict)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
