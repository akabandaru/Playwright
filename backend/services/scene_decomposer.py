"""
scene_decomposer.py

Decomposes a screenplay excerpt into structured visual beats using Gemini,
guided by few-shot examples fetched from Databricks (or the local CSV fallback).

Each beat returned contains:
    beat_number, visual_description, camera_angle, mood,
    lighting, characters_present, narrator_line, music_style
"""

import asyncio
import json
import os
import re
import time
from typing import Any, Dict, List

from google import genai
from google.genai import types

import services.databricks_service as db

# Initialized lazily so load_dotenv() has already run before the key is read
_client: "genai.Client | None" = None
_client_key: str | None = None


def _get_client() -> "genai.Client":
    global _client, _client_key
    current_key = os.getenv("GEMINI_API_KEY")
    if not current_key:
        raise ValueError("GEMINI_API_KEY is not set in environment / .env")
    if _client is None or _client_key != current_key:
        _client = genai.Client(api_key=current_key)
        _client_key = current_key
    return _client

async def close_client():
    global _client
    if _client:
        await _client.aio.aclose()
        _client = None

_BEAT_FIELD_RULES = """For each beat, return a JSON object with EXACTLY these keys:
  beat_number          (integer, starting at 1)

  visual_description   (string — what is visible in the frame; be highly descriptive about environment, texture, time of day, weather, architecture, props, depth, and atmosphere)
  camera_angle         (MUST be one of EXACTLY these: extreme close up, close up, medium shot, full shot, wide shot, long shot)
  mood                 (string — emotional tone of the beat, choose the best match from: happy, sad, tense, calm, melancholic, mysterious, default)
  lighting             (string — lighting style, e.g., harsh, soft, natural, dim, overcast, etc.)
  characters_present   (array of character names in the current beat, only include characters visible in the scene)
  visuals              - Describe ONLY background ambiance and environmental sound effects; the output will be used to generate fitting sound effects for the scene.
                        - Include layered atmospheric sounds (weather, environment, room tone, distant movement, texture).
                        - Avoid dialogue, narration, or character voices unless explicitly described.
                        - Avoid music unless explicitly described in the prompt.
                        - Be specific, vivid, and immersive. Limit to 350 characters maximum.
                        - Focus on: 
                          - Environment (indoor/outdoor, room size, or space type),
                          - Weather (rain, wind, thunder, etc.),
                          - Spatial feeling (e.g., echoing hall, open field, tight room),
                          - Emotional tone through sound (e.g., ominous rumble, bustling city, soft rain).
  narrator_line        (string — a cinematic voiceover, 100-150 characters)
  music_style          (string — music style or feel for this beat, e.g., ambient, orchestral, dark, melancholic, tense, etc.)

Critical continuity and environment rules:
    - Ensure each visual_description has rich environmental detail first, then character action.
    - Avoid generic phrases like "nice room" or "city street"; be concrete and cinematic."""

_SYSTEM_INSTRUCTION = f"""You are a professional film director and screenwriter.
Your job is to break a screenplay scene into distinct visual beats suitable for storyboarding.

Return a top-level JSON object with keys:
    character_bible       (array of objects with keys: name, description)
    beats                 (array of beat objects)

For each character in character_bible:
    - Use canonical character names as they appear in the script
    - description must lock visual continuity: age range, build, skin tone, hair, face traits,
        clothing palette, signature accessory, and cinematic style notes
    - Keep each description 180-260 characters and physically specific

{_BEAT_FIELD_RULES}

Additional rules:
    - Reuse character_bible details whenever a character appears in a beat.

Return ONLY a valid JSON object: {{"character_bible": [...], "beats": [ ... ]}}
No markdown, no explanation, no extra keys.
"""

_REIMAGINE_SYSTEM_INSTRUCTION = f"""You are a professional film director and screenwriter.
You are revising a SINGLE storyboard beat based on user feedback.

You will receive the current beat as JSON plus the user's correction or request.
Apply the user's feedback to produce a revised version of EXACTLY this one beat.

RULES:
- Return EXACTLY ONE beat — never split it into multiple beats.
- Keep the same beat_number.
- Preserve any fields the user did NOT ask to change.
- Apply the user's feedback precisely — if they say "6 infinity stones not 8", fix that detail.
- If the feedback changes the mood or tone, update mood, lighting, narrator_line, visuals, and music_style to match.

{_BEAT_FIELD_RULES}

Return ONLY a valid JSON object with the single revised beat: {{"beat": {{...}}}}
No markdown, no explanation, no extra keys.
"""

CAMERA_ANGLE_MAP = {
    "extreme close up": "extreme close-up, face fills frame, 85mm lens, very shallow depth of field",
    "close up": "close-up portrait, head and shoulders, 85mm lens, shallow depth of field",
    "medium shot": "medium shot, waist-up, 50mm lens, natural perspective",
    "full shot": "full body shot, subject clearly framed, 35mm lens",
    "wide shot": "wide establishing shot, environment dominant, 24mm lens",
    "long shot": "long shot, subject small in frame, environment dominant, 24mm lens",
}

_CAMERA_KEYS = set(CAMERA_ANGLE_MAP.keys())

_GENRE_PRESET_PROMPTS = {
    "none": "Use balanced cinematic visual grammar with no special genre bias.",
    "noir": """Genre preset: noir.
- Favor high-contrast chiaroscuro lighting, deep shadows, rain-slick streets/interiors, smoke/haze, and moral ambiguity.
- Camera language should lean into silhouettes, venetian-blind patterns, reflective surfaces, and suspenseful composition.
- Narrator tone should feel moody, introspective, and cynical.
""",
    "thriller": """Genre preset: thriller.
- Favor tension-forward visuals: tight framing, uneasy angles, partial reveals, and momentum between beats.
- Lighting and environment should sustain suspense and uncertainty.
- Narrator tone should be urgent, ominous, and propulsive.
""",
    "romcom": """Genre preset: rom-com.
- Favor warm, inviting visuals, playful compositions, expressive character interactions, and charming environment details.
- Use brighter, softer lighting and emotionally light pacing with occasional heartfelt beats.
- Narrator tone should be witty, affectionate, and hopeful.
""",
}

_STYLE_MODE_PROMPTS = {
    "photoreal": "Style mode: photoreal. Keep environments and character appearance grounded, physically plausible, and cinematically realistic.",
    "anime": "Style mode: anime. Use anime visual language (clean linework, stylized proportions, expressive framing, cel-shaded look), while preserving scene continuity and camera shot constraints.",
}


def _normalize_genre_preset(genre_preset: str) -> str:
    value = (genre_preset or "none").strip().lower().replace("-", "").replace("_", "")
    aliases = {
        "romcom": "romcom",
        "romanticcomedy": "romcom",
        "thriller": "thriller",
        "noir": "noir",
        "none": "none",
        "default": "none",
    }
    return aliases.get(value, "none")


def _normalize_style_mode(style_mode: str) -> str:
    value = (style_mode or "photoreal").strip().lower().replace("-", "").replace("_", "")
    aliases = {
        "photoreal": "photoreal",
        "photo": "photoreal",
        "realistic": "photoreal",
        "anime": "anime",
        "cartoon": "anime",
        "manga": "anime",
        "none": "photoreal",
        "default": "photoreal",
    }
    return aliases.get(value, "photoreal")


def _normalize_camera_angle(camera_angle: str) -> str:
    text = (camera_angle or "").strip().lower().replace("-", " ")

    direct_aliases = {
        "extreme close up": "extreme close up",
        "extreme closeup": "extreme close up",
        "extreme close": "extreme close up",
        "ecu": "extreme close up",
        "close up": "close up",
        "closeup": "close up",
        "cu": "close up",
        "medium shot": "medium shot",
        "medium": "medium shot",
        "mid shot": "medium shot",
        "ms": "medium shot",
        "full shot": "full shot",
        "full body shot": "full shot",
        "wide shot": "wide shot",
        "wide": "wide shot",
        "establishing shot": "wide shot",
        "long shot": "long shot",
        "ls": "long shot",
    }

    if text in direct_aliases:
        return direct_aliases[text]

    if "extreme" in text and "close" in text:
        return "extreme close up"
    if "close" in text:
        return "close up"
    if "full" in text:
        return "full shot"
    if "long" in text:
        return "long shot"
    if "wide" in text or "establish" in text:
        return "wide shot"
    if "medium" in text or "mid" in text:
        return "medium shot"

    return "medium shot"


def _enforce_camera_angle_map(beats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for beat in beats:
        if not isinstance(beat, dict):
            continue
        normalized = _normalize_camera_angle(str(beat.get("camera_angle", "")))
        if normalized not in _CAMERA_KEYS:
            normalized = "medium shot"
        beat["camera_angle"] = normalized
    return beats

def _build_few_shot_block(examples: List[Dict[str, Any]]) -> str:
    """Render the few-shot examples as a readable prompt block."""
    if not examples:
        return ""

    lines = ["--- FEW-SHOT EXAMPLES ---\n"]
    for ex in examples:
        lines.append(f"GENRE: {ex['genre'].upper()}")
        lines.append(f"SCENE:\n{ex['scene']}\n")
        lines.append("IDEAL BEAT BREAKDOWN:")
        lines.append(json.dumps({"beats": ex["beats"]}, separators=(",", ":")))
        lines.append("")

    lines.append("--- END OF EXAMPLES ---\n")
    return "\n".join(lines)


async def decompose_scene(
    screenplay_text: str,
    genre_preset: str = "none",
    style_mode: str = "photoreal",
) -> Dict[str, Any]:
    """
    Decompose a screenplay scene into structured beats.

    Steps:
      1. Start MLflow run via db.start_run()
      2. Fetch few-shot examples via db.get_few_shot_examples()
      3. Build a few-shot prompt and call Gemini
      4. Parse the JSON response
      5. Log metrics and inference data via db.*
      6. End the MLflow run

    Returns a dict:
        {
            "run_id": str,
            "beats": List[Dict],
            "inference_time_seconds": float,
            "beats_extracted": int,
            "tokens_used": int,
        }
    """
    normalized_genre = _normalize_genre_preset(genre_preset)
    normalized_style = _normalize_style_mode(style_mode)
    genre_prompt = _GENRE_PRESET_PROMPTS[_normalize_genre_preset(genre_preset)]
    style_prompt = _STYLE_MODE_PROMPTS[_normalize_style_mode(style_mode)]

    print(
        f"[DECOMPOSER] Starting run (genre_preset={normalized_genre}, style_mode={normalized_style})..."
    )
    run_id = db.start_run(screenplay_text)
    t_start = time.time()

    try:
        # ── 1. Fetch few-shot examples ────────────────────────────────────────
        print("[DECOMPOSER] Fetching few-shot examples...")
        examples = db.get_few_shot_examples(limit=2)

        # ── 2. Build prompt ───────────────────────────────────────────────────
        few_shot_block = _build_few_shot_block(examples)

        prompt = f"""{_SYSTEM_INSTRUCTION}

    Genre visual grammar guidance:
    {genre_prompt}

    Style guidance:
    {style_prompt}

{few_shot_block}
Now analyze the following scene and return the beat breakdown in the same JSON format.

SCENE TO ANALYZE:
{screenplay_text}

Return JSON:"""

        # ── 3. Call Gemini ────────────────────────────────────────────────────
        print("[DECOMPOSER] Calling Gemini API...")
        response = await _get_client().aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.5,
                top_p=0.9,
                top_k=40,
                max_output_tokens=8192,
                response_mime_type="application/json",
            ),
        )
        raw_text = response.text
        print(f"[DECOMPOSER] Gemini responded")

        # ── 4. Parse response ─────────────────────────────────────────────────
        beats = _parse_beats(raw_text)
        beats = _enforce_camera_angle_map(beats)
        print(f"[DECOMPOSER] Parsed beats")

        # ── 5. Log metrics ────────────────────────────────────────────────────
        inference_time = round(time.time() - t_start, 3)
        beats_extracted = len(beats)

        # token count: candidates[0].token_count when available
        tokens_used = 0
        try:
            tokens_used = response.usage_metadata.total_token_count or 0
        except Exception:
            pass

        db.log_metric("inference_time_seconds", inference_time)
        db.log_metric("beats_extracted", float(beats_extracted))
        db.log_metric("tokens_used", float(tokens_used))

        moods = [b.get("mood", "") for b in beats if b.get("mood")]
        cameras = [b.get("camera_angle", "") for b in beats if b.get("camera_angle")]

        db.log_inference(
            script=screenplay_text,
            beats_count=beats_extracted,
            moods=moods,
            camera_angles=cameras,
            pipeline_latency=inference_time,
        )

        db.end_run("FINISHED")

        return {
            "run_id": run_id,
            "beats": beats,
            "genre_preset": normalized_genre,
            "style_mode": normalized_style,
            "inference_time_seconds": inference_time,
            "beats_extracted": beats_extracted,
            "tokens_used": tokens_used,
        }

    except Exception as exc:
        db.end_run("FAILED")
        raise RuntimeError(f"decompose_scene failed: {exc}") from exc


async def reimagine_beat(
    current_beat: Dict[str, Any],
    user_feedback: str,
    genre_preset: str = "none",
    style_mode: str = "photoreal",
) -> Dict[str, Any]:
    """
    Revise a single beat based on user feedback using Gemini.

    Sends the current beat JSON + the user's natural-language correction to Gemini
    and returns exactly one updated beat with the same structure.
    """
    
    genre_prompt = _GENRE_PRESET_PROMPTS[_normalize_genre_preset(genre_preset)]
    style_prompt = _STYLE_MODE_PROMPTS[_normalize_style_mode(style_mode)]

    prompt = f"""{_REIMAGINE_SYSTEM_INSTRUCTION}

Genre visual grammar guidance:
{genre_prompt}

Style guidance:
{style_prompt}

CURRENT BEAT:
{json.dumps(current_beat, indent=2)}

USER FEEDBACK:
{user_feedback}

Return the revised beat as JSON:"""

    print(f"[REIMAGINE] Beat {current_beat.get('beat_number')} — feedback: {user_feedback[:100]}")

    try:
        response = await _get_client().aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.5,
                top_p=0.9,
                top_k=40,
                max_output_tokens=4096,
                response_mime_type="application/json",
            ),
        )

        raw_text = response.text
        parsed = json.loads(raw_text)

        if isinstance(parsed, dict) and "beat" in parsed:
            beat = parsed["beat"]
        elif isinstance(parsed, dict) and "beats" in parsed and len(parsed["beats"]) > 0:
            beat = parsed["beats"][0]
        elif isinstance(parsed, dict) and "beat_number" in parsed:
            beat = parsed
        else:
            raise ValueError(f"Unexpected response shape: {list(parsed.keys()) if isinstance(parsed, dict) else type(parsed)}")

        beat["beat_number"] = current_beat.get("beat_number", 1)
        beats = _enforce_camera_angle_map([beat])
        beat = beats[0]

        print(f"[REIMAGINE] Beat {beat['beat_number']} revised successfully")
        return beat

    except Exception as exc:
        raise RuntimeError(f"reimagine_beat failed: {exc}") from exc


def _parse_beats(raw: str) -> List[Dict[str, Any]]:
    """
    Robustly extract the beats array from Gemini's JSON response.
    Handles both {"beats": [...]} and a bare [...] array.
    """
    # Try direct parse first
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "beats" in parsed:
            return parsed["beats"]
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            print(f"[DECOMPOSER] Parsed JSON dict but no 'beats' key — keys present: {list(parsed.keys())}")
    except json.JSONDecodeError as e:
        print(f"[DECOMPOSER] json.loads failed ({e}), attempting fallback extraction")

    # Try to extract array and fix common JSON issues
    start = raw.find("[")
    end = raw.rfind("]") + 1
    if start != -1 and end > start:
        json_str = raw[start:end]
        
        # Try parsing as-is first
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass
        
        # Fix common issues: trailing commas, unescaped quotes in strings
        # Remove trailing commas before ] or }
        json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
        
        # Try again after fixes
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass
        
        # Last resort: try to parse individual beat objects
        beats = []
        beat_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
        matches = re.findall(beat_pattern, json_str)
        for match in matches:
            try:
                # Fix trailing commas in individual objects
                fixed = re.sub(r',\s*([}\]])', r'\1', match)
                beat = json.loads(fixed)
                if isinstance(beat, dict) and "beat_number" in beat:
                    beats.append(beat)
            except json.JSONDecodeError:
                continue
        
        if beats:
            print(f"[DECOMPOSER] Recovered {len(beats)} beats from malformed JSON")
            return beats

    raise ValueError(f"Could not parse beats from Gemini response: {raw[:200]}")
