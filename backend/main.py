import os
import time
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from services.scene_decomposer import decompose_scene
from services.replicate_service import generate_images
from services.elevenlabs_service import generate_voices
from services.video_service import render_video
from services.figma_service import create_figma_storyboard
from services.databricks_service import (
    end_run,
    log_metric,
    log_inference,
    log_dataset_stats,
    get_dashboard_stats,
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
        "http://localhost:3000",
        "https://*.vercel.app",
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


class BeatsRequest(BaseModel):
    beats: List[Beat]


class RenderRequest(BaseModel):
    beats: List[Beat]
    audioUrls: List[dict]


class FigmaExportRequest(BaseModel):
    beats: List[Beat]


@app.get("/")
async def root():
    return {"message": "Welcome to PLAYWRIGHT API", "version": "1.0.0"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.post("/api/analyze")
async def api_analyze(request: ScriptRequest):
    """
    Analyze a script and break it down into visual beats.
    Uses Gemini 1.5 Pro with few-shot examples and MLflow tracking via scene_decomposer.
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
    Generate images for each beat using Replicate SDXL.
    Runs all generations in parallel.
    """
    if not request.beats:
        raise HTTPException(status_code=400, detail="Beats array cannot be empty")
    
    start_time = time.time()
    
    try:
        beats_dict = [b.model_dump() for b in request.beats]
        image_results = await generate_images(beats_dict)
        
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
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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


@app.get("/api/video/{filename}")
async def api_get_video(filename: str):
    """
    Serve rendered video files for playback and download.
    """
    video_path = OUTPUT_DIR / filename
    
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    
    return FileResponse(
        path=str(video_path),
        media_type="video/mp4",
        filename=filename,
    )


@app.get("/api/dashboard")
async def api_dashboard():
    """
    Get aggregated stats from inference logs.
    Returns total runs, average latency, most common moods/cameras.
    """
    try:
        stats = get_dashboard_stats()
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)