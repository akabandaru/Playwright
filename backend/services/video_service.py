import os
import asyncio
import httpx
import uuid
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from moviepy import (
    ImageClip, 
    AudioFileClip, 
    concatenate_videoclips, 
    CompositeAudioClip,
)
import numpy as np

TEMP_DIR = Path(__file__).parent.parent / "temp"
OUTPUT_DIR = Path(__file__).parent.parent / "outputs"
VIDEOS_DIR = OUTPUT_DIR / "videos"
IMAGES_DIR = OUTPUT_DIR / "images"

VIDEOS_DIR.mkdir(exist_ok=True)

async def download_image(url: str, client: httpx.AsyncClient) -> str:
    """Download an image or resolve local path and save to temp directory."""
    # Handle local API paths like /api/image/filename.png
    if url.startswith("/api/image/"):
        filename = url.replace("/api/image/", "")
        local_path = IMAGES_DIR / filename
        if local_path.exists():
            return str(local_path)
        # If not found locally, try downloading with full URL
        url = f"http://localhost:8000{url}"
    
    # Handle relative paths without http
    if not url.startswith("http"):
        url = f"http://localhost:8000{url}"
    
    response = await client.get(url, timeout=60.0)
    response.raise_for_status()
    
    filename = f"image_{uuid.uuid4().hex[:8]}.png"
    filepath = TEMP_DIR / filename
    
    with open(filepath, "wb") as f:
        f.write(response.content)
    
    return str(filepath)

def ken_burns_effect(clip, zoom_start=1.0, zoom_end=1.05):
    """Apply Ken Burns zoom effect to a clip."""
    w, h = clip.size
    duration = clip.duration
    
    def zoom_frame(get_frame, t):
        frame = get_frame(t)
        progress = t / duration
        current_zoom = zoom_start + (zoom_end - zoom_start) * progress
        
        new_w = int(w * current_zoom)
        new_h = int(h * current_zoom)
        
        from PIL import Image
        img = Image.fromarray(frame)
        img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        
        left = (new_w - w) // 2
        top = (new_h - h) // 2
        img_cropped = img_resized.crop((left, top, left + w, top + h))
        
        return np.array(img_cropped)
    
    return clip.transform(zoom_frame)

async def render_video(
    beats: List[Dict[str, Any]],
    audio_files: List[Dict[str, Any]],
    background_music_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Render the final video from images and audio."""
    start_time = time.time()
    
    async with httpx.AsyncClient() as client:
        download_tasks = []
        for beat in beats:
            image_url = beat.get("imageUrl") or beat.get("image_url")
            print(f"[VIDEO] Beat {beat.get('beat_number')}: image_url = {image_url}")
            if image_url:
                download_tasks.append(download_image(image_url, client))
        
        print(f"[VIDEO] Downloading {len(download_tasks)} images...")
        image_paths = await asyncio.gather(*download_tasks, return_exceptions=True)
        print(f"[VIDEO] Downloaded images: {image_paths}")
    
    audio_map = {a["beat_number"]: a["audio_path"] for a in audio_files if a.get("audio_path")}
    
    clips = []
    for idx, beat in enumerate(beats):
        beat_num = beat.get("beat_number", idx + 1)
        
        if idx < len(image_paths) and not isinstance(image_paths[idx], Exception):
            image_path = image_paths[idx]
        else:
            continue
        
        audio_path = audio_map.get(beat_num)
        if audio_path and os.path.exists(audio_path):
            audio_clip = AudioFileClip(audio_path)
            duration = audio_clip.duration
        else:
            duration = 4.0
            audio_clip = None
        
        image_clip = ImageClip(image_path, duration=duration)
        image_clip = image_clip.resized((1280, 720))
        
        image_clip = ken_burns_effect(image_clip, zoom_start=1.0, zoom_end=1.05)
        
        if audio_clip:
            image_clip = image_clip.with_audio(audio_clip)
        
        clips.append(image_clip)
    
    if not clips:
        raise ValueError("No valid clips to render")
    
    final_video = concatenate_videoclips(clips, method="compose")
    
    if background_music_path and os.path.exists(background_music_path):
        bg_music = AudioFileClip(background_music_path)
        bg_music = bg_music.with_volume_scaled(0.15)
        
        if bg_music.duration < final_video.duration:
            loops_needed = int(final_video.duration / bg_music.duration) + 1
            bg_music = concatenate_videoclips([bg_music] * loops_needed)
        
        bg_music = bg_music.subclipped(0, final_video.duration)
        
        if final_video.audio:
            final_audio = CompositeAudioClip([final_video.audio, bg_music])
            final_video = final_video.with_audio(final_audio)
        else:
            final_video = final_video.with_audio(bg_music)
    
    output_filename = f"playwright_{uuid.uuid4().hex[:8]}.mp4"
    output_path = VIDEOS_DIR / output_filename
    
    await asyncio.to_thread(
        final_video.write_videofile,
        str(output_path),
        fps=24,
        codec="libx264",
        audio_codec="aac",
        threads=4,
        preset="medium",
        logger=None,
    )
    
    for clip in clips:
        clip.close()
    final_video.close()
    
    render_time = time.time() - start_time
    
    return {
        "filename": output_filename,
        "path": str(output_path),
        "duration": final_video.duration if hasattr(final_video, 'duration') else 0,
        "render_time": render_time,
    }
