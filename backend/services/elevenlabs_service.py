import os
import asyncio
import httpx
import uuid
from typing import Optional
from pathlib import Path
from typing import List, Dict, Any
from elevenlabs.client import ElevenLabs
try:
    from pydub import AudioSegment
    _audio_segment_import_error = None
except Exception as exc:
    AudioSegment = None
    _audio_segment_import_error = exc


ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1"
MODEL_ID = "eleven_monolingual_v1"

VOICE_OPTIONS = [
    {"id": "NIPHfiR4kB4aHfvaKvYb", "name": "Molly", "mood": "Happy"},
    {"id": "k9073AMdU5sAUtPMH1il", "name": "Jeff", "mood": "Sad"},
    {"id": "aYIHaVW2uuV2iGj07rJH", "name": "John", "mood": "Tense"},
    {"id": "4JVOFy4SLQs9my0OLhEw", "name": "Luca", "mood": "Calm"},
    {"id": "auq43ws1oslv0tO4BDa7", "name": "Adam", "mood": "Melancholic / Mysterious / Default"},
]
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

elevenlabs = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"),)

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
    response = None

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

    if response is None:
        raise RuntimeError("Failed to generate voice after retries.")

    filename = f"narration_{beat_number}_{uuid.uuid4().hex[:8]}.mp3"
    filepath = TEMP_DIR / filename
    
    with open(filepath, "wb") as f:
        f.write(response.content)
    
    return {
        "beat_number": beat_number,
        "audio_path": str(filepath),
        "filename": filename,
    }

def generate_sound_effects(scene_description: str) -> str:
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


def generate_music(scene_description: str, mood: str, length_ms: int, music_style: str) -> str:
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


def mix_narration_with_sfx(narration_path: str, sfx_path: str, music_path: str, output_path: str, target_narration_db: float = -18.0, sfx_offset_db: float = -10.0, music_offset_db: float = -6.0):
    """
    Mix narration with background sound effects (from ElevenLabs).
    """
    if AudioSegment is None:
        raise RuntimeError(f"pydub/audio backend unavailable: {_audio_segment_import_error}")

    # Load narration
    narration = AudioSegment.from_mp3(narration_path)
    sfx = AudioSegment.from_mp3(sfx_path)
    music = AudioSegment.from_mp3(music_path)

    narration = narration.apply_gain(target_narration_db - narration.dBFS)
    sfx = sfx.apply_gain(target_narration_db - sfx.dBFS + sfx_offset_db)
    music = music.apply_gain(target_narration_db - music.dBFS + music_offset_db)

    # Loop SFX and music to match narration length
    def fit_to_length(audio, target_length):
        if len(audio) == target_length:
            return audio
        elif len(audio) > target_length:
            return audio[:target_length]
        else:
            return (audio * (target_length // len(audio) + 1))[:target_length]

    sfx = fit_to_length(sfx, len(narration))
    music = fit_to_length(music, len(narration))

    # Layering order matters
    mixed = sfx.overlay(music)
    mixed = mixed.overlay(narration)

    mixed.export(output_path, format="mp3")

    # Clean up temp files
    for path in [narration_path, sfx_path, music_path]:
        try:
            os.remove(path)
        except Exception as e:
            print(f"Failed to delete {path}: {e}")

    return output_path


async def generate_scene_audio(screenplay_text: str, visuals: str,beat_number: int, voice_id: str, mood: str, music_style: str, client: httpx.AsyncClient) -> str:
    # Step 1: Generate the narration
    narration = await generate_single_voice(screenplay_text, beat_number, voice_id, client)

    narration_length = await asyncio.to_thread(get_mp3_length, narration['audio_path'])
    narration_length *= 1000

    # Step 2: Generate sound effects based on the scene description
    scene_description = f"""
        Cinematic background ambience.
        Scene: {visuals}.
        Mood: {mood}.
        No voices. Background ambience only.
        """  
    async def safe_thread(func, *args):
        try:
            return await asyncio.to_thread(func, *args)
        except Exception as e:
            print(f"{func.__name__} failed:", e)
            return None

    sfx_path, music_path = await asyncio.gather(
        safe_thread(generate_sound_effects, scene_description),
        safe_thread(generate_music, scene_description, mood, narration_length, music_style)
    )

    # Step 3: Mix narration with sound effects
    output_path = TEMP_DIR / f"final_scene_{beat_number}.mp3"

    if sfx_path and music_path:
        final_audio_path = mix_narration_with_sfx(
            narration['audio_path'],
            sfx_path,
            music_path,
            output_path
        )
    else:
        # Narration only fallback
        final_audio_path = narration['audio_path']
    
    final_length = await asyncio.to_thread(get_mp3_length, final_audio_path)
    print(f"Length of final mixed audio: {final_length} milliseconds")

    return str(final_audio_path)

async def generate_voices_and_sfx(beats: List[Dict[str, Any]], voice_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Generate voice audio and sound effects for all narrator lines in parallel with mood-based voices."""
    semaphore = asyncio.Semaphore(2)  # Limit concurrency to avoid rate limits

    async with httpx.AsyncClient(timeout=60) as client:
        async def safe_generate(beat):
            async with semaphore:
                text = beat.get("narrator_line", "")
                visuals = beat.get("visuals", "")
                beat_number = beat.get("beat_number")
                mood = beat.get("mood", "default").lower()
                music_style = beat.get("music_style", "cinematic")
                selected_voice = voice_id or MOOD_VOICE_MAP["default"]
                return await generate_scene_audio(text, visuals, beat_number, selected_voice, mood, music_style, client)

        filtered_beats = [b for b in beats if b.get("narrator_line")]
        tasks = [safe_generate(b) for b in filtered_beats]

        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results
    processed_results = []

    for beat, result in zip(filtered_beats, results):
        beat_number = beat.get("beat_number")

        if isinstance(result, Exception):
            processed_results.append({
                "beat_number": beat_number,
                "audio_path": None,
                "error": str(result),
            })
        else:
            processed_results.append({
                "beat_number": beat_number,
                "audio_path": result
            })

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