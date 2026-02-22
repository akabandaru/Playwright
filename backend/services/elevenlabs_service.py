import os
import asyncio
import logging
import shutil
from urllib import response
import httpx
import uuid
from pathlib import Path
from typing import List, Dict, Any
from elevenlabs.client import ElevenLabs
from elevenlabs.play import play
try:
    from pydub import AudioSegment
    _audio_segment_import_error = None
except Exception as exc:
    AudioSegment = None
    _audio_segment_import_error = exc

logger = logging.getLogger(__name__)

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
            "speed": 0.85
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


async def generate_music(scene_description: str, mood: str, length_ms: int, music_style: str) -> str:
    """
    Generate background music using ElevenLabs Music API.
    """
    # You can either use a fixed prompt template per mood
    prompt = f"""
        Cinematic background score.
        Mood: {mood}.
        Scene: {scene_description}.
        Music Style: {music_style}. 
        Instrumental only. No vocals. Absolutely no speech or words. Just music. No narration in the music. 
        The music should reflect the following:
        - The tone and emotion of the scene: {mood} (such as melancholic, tense, calm, ominous, etc.).
        - Consider the atmosphere described in the scene: (e.g., heavy rain, distant city hum, whistling wind, etc.).
        - The music should either support or contrast the scene to create tension, atmosphere, or drama (e.g., ominous drones, building tension, peaceful piano, etc.).
        - Focus on creating a **musical texture** that enhances the feeling described in the scene, for example: a soft melody for calm, a building orchestral score for tension, or a low, rumbling bass for mystery.
        - The music should **match the pacing** of the narrative, whether it's slow and atmospheric or fast and building in intensity.
        - The music should be playing for the entire duration of the scene, and should be designed to loop seamlessly if needed.
        """

    print(f"Generating music with prompt: {prompt.strip()}")

    length_ms = int(round(max(length_ms, 3000)))

    composition_plan = elevenlabs.music.composition_plan.create(
        prompt=prompt,
        music_length_ms=length_ms,
    )

    composition = elevenlabs.music.compose(
        composition_plan=composition_plan
    )

    music_filename = f"music_{uuid.uuid4().hex[:8]}.mp3"
    music_path = TEMP_DIR / music_filename

    with open(music_path, "wb") as f:
        for chunk in composition:
            f.write(chunk)

    return str(music_path)


def mix_narration_with_sfx(narration_path: str, sfx_path: str, music_path: str, output_path: str, narration_volume: float = -5.0, sfx_volume: float = -20.0, music_volume: float = -8.0):
    """
    Mix narration with background sound effects (from ElevenLabs).
    """
    if AudioSegment is None:
        raise RuntimeError(f"pydub/audio backend unavailable: {_audio_segment_import_error}")

    # Load narration
    narration = AudioSegment.from_mp3(narration_path) + narration_volume
    sfx = AudioSegment.from_mp3(sfx_path) + sfx_volume
    music = AudioSegment.from_mp3(music_path) + music_volume

    # Loop SFX and music to match narration length
    def loop_to_length(audio, target_length):
        return (audio * (target_length // len(audio) + 1))[:target_length]

    sfx = loop_to_length(sfx, len(narration))
    music = loop_to_length(music, len(narration))

    # Layering order matters
    mixed = narration.overlay(sfx)
    mixed = mixed.overlay(music)

    mixed.export(output_path, format="mp3")
    return output_path


async def generate_scene_audio(screenplay_text: str, visuals: str,beat_number: int, voice_id: str, mood: str, music_style: str) -> str:
    # Step 1: Generate the narration
    async with httpx.AsyncClient() as client:
        narration = await generate_single_voice(screenplay_text, beat_number, voice_id, client)

    if AudioSegment is None:
        logger.warning(
            "Audio backend unavailable; using narration-only audio for beat=%s detail=%s",
            beat_number,
            str(_audio_segment_import_error),
        )
        output_path = TEMP_DIR / f"final_scene_{beat_number}.mp3"
        shutil.copyfile(narration["audio_path"], output_path)
        return str(output_path)

    narration_length = get_mp3_length(narration['audio_path']) * 1000
    # Step 2: Generate sound effects based on the scene description
    scene_description = scene_description = f"""
        Cinematic background ambience.
        Scene: {visuals}.
        Mood: {mood}.
        Narator line: {screenplay_text}.
        No voices. Background ambience only.
        """  
    # Custom description for sound effects
    try:
        sfx_path = await generate_sound_effects(scene_description)
        sfx_length = get_mp3_length(sfx_path) * 1000

        print(f"Length of narration: {narration_length} milliseconds")
        print(f"Length of sound effects: {sfx_length} milliseconds")

        music_path = await generate_music(
            scene_description,
            mood,
            narration_length,
            music_style,
        )

        # Step 3: Mix narration with sound effects
        output_path = TEMP_DIR / f"final_scene_{beat_number}.mp3"
        final_audio_path = mix_narration_with_sfx(narration['audio_path'], sfx_path, music_path, output_path)

        final_length = get_mp3_length(final_audio_path)
        print(f"Length of final mixed audio: {final_length} milliseconds")

        return final_audio_path
    except Exception as exc:
        logger.warning(
            "SFX/music mix unavailable for beat=%s, using narration-only audio. detail=%s",
            beat_number,
            str(exc),
        )
        output_path = TEMP_DIR / f"final_scene_{beat_number}.mp3"
        shutil.copyfile(narration["audio_path"], output_path)
        return str(output_path)

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
                music_style = beat.get("music_style", "cinematic")
                voice_id = MOOD_VOICE_MAP["default"] # MOOD_VOICE_MAP.get(mood, MOOD_VOICE_MAP["default"])
                return await generate_scene_audio(text, visuals, beat_number, voice_id, mood, music_style)

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

def get_mp3_length(mp3_path: str) -> float:
    """Return the length (duration) of an MP3 file in seconds."""
    if AudioSegment is None:
        return 0.0

    # Load the MP3 file
    audio = AudioSegment.from_mp3(mp3_path)
    
    # Return the duration in milliseconds
    print(f"Audio length in ms: {len(audio)}")
    return float(len(audio)) / 1000.0