import os
import asyncio
import httpx
import uuid
from pathlib import Path
from typing import List, Dict, Any

ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1"
VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel
MODEL_ID = "eleven_monolingual_v1"

TEMP_DIR = Path(__file__).parent.parent / "temp"
TEMP_DIR.mkdir(exist_ok=True)

async def generate_single_voice(
    text: str, 
    beat_number: int,
    client: httpx.AsyncClient
) -> Dict[str, Any]:
    """Generate voice audio for a single narrator line."""
    api_key = os.getenv("ELEVENLABS_API_KEY")
    
    url = f"{ELEVENLABS_API_URL}/text-to-speech/{VOICE_ID}"
    
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": api_key,
    }
    
    payload = {
        "text": text,
        "model_id": MODEL_ID,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
        }
    }
    
    response = await client.post(url, json=payload, headers=headers, timeout=60.0)
    response.raise_for_status()
    
    filename = f"narration_{beat_number}_{uuid.uuid4().hex[:8]}.mp3"
    filepath = TEMP_DIR / filename
    
    with open(filepath, "wb") as f:
        f.write(response.content)
    
    return {
        "beat_number": beat_number,
        "audio_path": str(filepath),
        "filename": filename,
    }

async def generate_voices(beats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Generate voice audio for all narrator lines in parallel."""
    async with httpx.AsyncClient() as client:
        tasks = []
        for beat in beats:
            narrator_line = beat.get("narrator_line", "")
            if narrator_line:
                tasks.append(
                    generate_single_voice(
                        narrator_line,
                        beat.get("beat_number", 1),
                        client
                    )
                )
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        processed_results = []
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append({
                    "beat_number": idx + 1,
                    "audio_path": None,
                    "error": str(result),
                })
            else:
                processed_results.append(result)
        
        return processed_results
