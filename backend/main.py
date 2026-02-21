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


from services.diffusers_service import generate_images
from services.scene_decomposer import decompose_scene
from services.elevenlabs_service import generate_voices
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


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


class AnalyzeRequest(BaseModel):
    script: str
    use_databricks: bool = True


@app.post("/api/analyze")
async def api_analyze(request: ScriptRequest):
    """
    Analyze a script and break it down into visual beats.
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
    Generate images for each beat using local Diffusers SDXL pipeline.
    Runs generations sequentially for single-GPU stability.
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
    Export a full storyboard to Figma.

    Resolution order for the target file:
      1. request.target_file_key  (explicit override)
      2. FIGMA_TEMPLATE_FILE_KEY  env var  →  one-click "Export to Figma" mode
      3. Neither set              →  returns a plugin payload JSON

    Template mode handles variable beat counts automatically:
      - Unused template frames are hidden so they don't clutter the canvas.
      - Beats that exceed the template's frame count are reported in overflowBeats.

    Response includes:
      exportMode      : "direct_patch" | "plugin_payload"
      figmaUrl        : direct link to the Figma file (direct_patch only)
      templateSlots   : total Beat frames in the template
      usedSlots       : frames that were patched
      hiddenSlots     : frame numbers that were hidden (fewer beats than template)
      overflowBeats   : beat numbers with no matching template frame
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
    Selectively update a single beat's image (and text) in an existing Figma file.

    Requires a prior full export so that node IDs are in the mapping store.
    Only patches the nodes for the specified beat — all other beats are untouched.
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
    Register node IDs after the Figma plugin has created the file client-side.

    The plugin calls this endpoint once it has created the Figma file and knows
    the file_key and per-beat node IDs. This enables future selective updates
    via PATCH /api/export-figma/{storyboard_id}/beat/{beat_number}.
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