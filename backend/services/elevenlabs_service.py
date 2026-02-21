import os
import asyncio
from urllib import response
import httpx
import uuid
from pathlib import Path
from typing import List, Dict, Any
from elevenlabs.client import ElevenLabs
from elevenlabs.play import play
from pydub import AudioSegment

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

elevenlabs = ElevenLabs(
    api_key=os.getenv("ELEVENLABS_API_KEY"),
)


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
            "stability": 0.45,
            "similarity_boost": 0.9,
            "style": 0.9,
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
            char_cost = response.headers.get("x-character-count")
            request_id = response.headers.get("request-id")
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

async def generate_sound_effects(scene_description: str) -> str:
    """Generate sound effects for the scene using ElevenLabs."""
    
    audio_generator = elevenlabs.text_to_sound_effects.convert(
        text=scene_description
    )

    audio_filename = f"sfx_{uuid.uuid4().hex[:8]}.mp3"
    audio_path = TEMP_DIR / audio_filename

    with open(audio_path, "wb") as f:
        for chunk in audio_generator:
            f.write(chunk)

    return str(audio_path)

def mix_narration_with_sfx(narration_path: str, sfx_path: str, output_path: str, narration_volume: float = -5.0, sfx_volume: float = -20.0):
    """
    Mix narration with background sound effects (from ElevenLabs).
    """
    # Load narration
    narration = AudioSegment.from_mp3(narration_path)
    narration = narration + narration_volume  # Lower the volume of narration if needed

    # Load sound effects
    sfx = AudioSegment.from_mp3(sfx_path)
    sfx = sfx + sfx_volume  # Adjust SFX volume if needed

    # Loop sound effect to match the length of narration
    sfx = sfx * (len(narration) // len(sfx) + 1)

    # Overlay sound effects on narration
    mixed_audio = narration.overlay(sfx)

    # Export mixed audio to file
    mixed_audio.export(output_path, format="mp3")
    return output_path

# def mix_narration_with_sfx(narration_path, sfx_path, output_path,
#                            narration_volume=-5.0,
#                            sfx_volume=-22.0):

#     narration = AudioSegment.from_mp3(narration_path) + narration_volume
#     sfx = AudioSegment.from_mp3(sfx_path) + sfx_volume

#     # Make ambience softer and less repetitive
#     sfx = sfx.low_pass_filter(4000)

#     def loop_with_crossfade(base, target_length, crossfade_ms=800):
#         import random
#         output = AudioSegment.empty()

#         while len(output) < target_length:
#             gain = random.uniform(-1.5, 1.5)
#             varied = base + gain
#             if len(output) == 0:
#                 output = varied
#             else:
#                 output = output.append(varied, crossfade=crossfade_ms)

#         return output[:target_length]

#     sfx = loop_with_crossfade(sfx, len(narration))

#     mixed = narration.overlay(sfx)
#     mixed.export(output_path, format="mp3")

#     return output_path

async def generate_scene_audio(screenplay_text: str, visuals: str,beat_number: int, voice_id: str, mood: str) -> str:
    # Step 1: Generate the narration
    async with httpx.AsyncClient() as client:
        narration = await generate_single_voice(screenplay_text, beat_number, voice_id, client)

    # Step 2: Generate sound effects based on the scene description
    scene_description = scene_description = f"""
        Cinematic background ambience.
        Scene: {visuals}.
        Mood: {mood}.
        Narator line: {screenplay_text}.
        No voices. Background ambience only.
        """  
    # Custom description for sound effects
    sfx_path = await generate_sound_effects(scene_description)

    # Step 3: Mix narration with sound effects
    output_path = TEMP_DIR / f"final_scene_{beat_number}.mp3"
    final_audio_path = mix_narration_with_sfx(narration['audio_path'], sfx_path, output_path)

    return final_audio_path


async def generate_voices_and_sfx(beats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Generate voice audio and sound effects for all narrator lines in parallel with mood-based voices."""
    semaphore = asyncio.Semaphore(2)  # Limit concurrency to avoid rate limits
    results = []

    async with httpx.AsyncClient(timeout=60) as client:
        async def safe_generate(beat):
            async with semaphore:
                text = beat.get("narrator_line", "")
                visuals = beat.get("visuals", "")
                beat_number = beat.get("beat_number", 1)
                mood = beat.get("mood", "default").lower()
                voice_id = MOOD_VOICE_MAP.get(mood, MOOD_VOICE_MAP["default"])
                return await generate_scene_audio(text, visuals, beat_number, voice_id, mood)

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
            processed_results.append({"beat_number": idx + 1, "audio_path": result})

    return processed_results