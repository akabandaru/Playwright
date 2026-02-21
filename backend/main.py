import os
import json
import time
import asyncio
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from services.diffusers_service import generate_images
from services.scene_decomposer import decompose_scene
from services.elevenlabs_service import generate_voices
from services.video_service import render_video
from services.figma_service import create_figma_storyboard
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
