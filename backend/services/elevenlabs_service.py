import os
import asyncio
import httpx
import uuid
from pathlib import Path
from typing import List, Dict, Any

ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1"
MODEL_ID = "eleven_monolingual_v1"

# Define mood -> voice mapping
MOOD_VOICE_MAP = {
    "happy": "NIPHfiR4kB4aHfvaKvYb",   # Molly
    "sad": "k9073AMdU5sAUtPMH1il", # Jeff
    "tense": "aYIHaVW2uuV2iGj07rJH", # John
    "calm": "4JVOFy4SLQs9my0OLhEw", # Luca
    "melancholic": "auq43ws1oslv0tO4BDa7", # Adam
    "mysterious": "auq43ws1oslv0tO4BDa7", # Adam, 
    "default": "auq43ws1oslv0tO4BDa7",  # Adam
}

TEMP_DIR = Path(__file__).parent.parent / "temp"
TEMP_DIR.mkdir(exist_ok=True)


async def generate_single_voice(
    text: str,
    beat_number: int,
    voice_id: str,
    client: httpx.AsyncClient
) -> Dict[str, Any]:
    """Generate voice audio for a single narrator line."""
    api_key = os.getenv("ELEVENLABS_API_KEY")
    
    url = f"{ELEVENLABS_API_URL}/text-to-speech/{voice_id}"
    
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": api_key,
    }
    
    payload = {
        "text": text,
        "model_id": MODEL_ID,
        "voice_settings": {
            "stability": 0.35,
            "similarity_boost": 0.9,
            "style": 0.8,
            "use_speaker_boost": True,
            "speaking_rate": 0.6
        }
    }

    retries = 3
    delay = 1
    for attempt in range(retries):
        try:
            response = await client.post(url, json=payload, headers=headers, timeout=60.0)
            response.raise_for_status()
            break
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429 and attempt < retries - 1:
                await asyncio.sleep(delay)
                delay *= 2
            else:
                raise

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
    """Generate voice audio for all narrator lines in parallel with mood-based voices."""
    semaphore = asyncio.Semaphore(2)  # Limit concurrency to avoid rate limits
    results = []

    async with httpx.AsyncClient(timeout=60) as client:
        async def safe_generate(beat):
            async with semaphore:
                text = beat.get("narrator_line", "")
                beat_number = beat.get("beat_number", 1)
                mood = beat.get("mood", "").lower()
                voice_id = MOOD_VOICE_MAP.get(mood, MOOD_VOICE_MAP["default"])
                return await generate_single_voice(text, beat_number, voice_id, client)

        tasks = [safe_generate(b) for b in beats if b.get("narrator_line")]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results
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