"""
scene_decomposer.py

Decomposes a screenplay excerpt into structured visual beats using Gemini,
guided by few-shot examples fetched from Databricks (or the local CSV fallback).

Each beat returned contains:
    beat_number, visual_description, camera_angle, mood,
    lighting, characters_present, narrator_line, music_style
"""

import json
import os
import time
from typing import Any, Dict, List

from google import genai
from google.genai import types

import services.databricks_service as db

# Initialized lazily so load_dotenv() has already run before the key is read
_client: "genai.Client | None" = None


def _get_client() -> "genai.Client":
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return _client

async def close_client():
    global _client
    if _client:
        await _client.aio.aclose()
        _client = None

_SYSTEM_INSTRUCTION = """You are a professional film director and screenwriter.
Your job is to break a screenplay scene into 4-8 distinct visual beats suitable for storyboarding.

For each beat return a JSON object with EXACTLY these keys:
  beat_number          (integer, starting at 1)
  visual_description   (string — what is visible in the frame, a description of the actors and the environment, keep primary actor's description consistent for each beat)
  camera_angle         (one of: wide shot, medium shot, close-up, extreme close-up,
                        over-the-shoulder, low angle, high angle, dutch angle,
                        POV shot, tracking shot)
  mood                 (string — emotional tone of the beat, only choose the best match out of this list: happy, sad, tense, calm, melancholic, mysterious, default)
  lighting             (string — lighting style)
  characters_present   (array of character name strings)
  visuals              - Describe ONLY background ambience and environmental sound effects; the output will be used to generate fitting sound effects for the scene.
                        - Include layered atmospheric sounds (weather, environment, room tone, distant movement, texture)
                        - Avoid dialogue, narration, or character voices
                        - Avoid music unless explicitly described
                        - Be 350 characters max, but include as much detail as possible within that limit
                        - Be vivid, specific, and immersive
                        - Sound like instructions for a Hollywood sound designer

                        Focus on:
                        - Environment (indoor/outdoor, size of space; use solely this if it strongly influences the scene; for example rain fall, echoing footsteps in a hallway, or bustling city sounds would be dominating sounds to include)
                        - Weather (rain, wind, thunder, etc.)
                        - Spatial feeling (echoing hall, tight room, open field)
                        - Emotional tone through sound (ominous rumble, soft rain, bustling city sounds, etc.)
  narrator_line        (string — cinematic voiceover, 100-150 characters, make it descriptive of the scene and very vague)
  music_style          (string — music style/feel for this beat)

Return ONLY a valid JSON object: {"beats": [ ... ]}
No markdown, no explanation, no extra keys."""


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


async def decompose_scene(screenplay_text: str) -> Dict[str, Any]:
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
    print("[DECOMPOSER] Starting run...")
    run_id = db.start_run(screenplay_text)
    t_start = time.time()

    try:
        # ── 1. Fetch few-shot examples ────────────────────────────────────────
        print("[DECOMPOSER] Fetching few-shot examples...")
        examples = db.get_few_shot_examples(limit=2)

        # ── 2. Build prompt ───────────────────────────────────────────────────
        few_shot_block = _build_few_shot_block(examples)

        prompt = f"""{_SYSTEM_INSTRUCTION}

{few_shot_block}
Now analyze the following scene and return the beat breakdown in the same JSON format.

SCENE TO ANALYZE:
{screenplay_text}

Return JSON:"""

        # ── 3. Call Gemini ────────────────────────────────────────────────────
        print("[DECOMPOSER] Calling Gemini API...")
        response = await _get_client().aio.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.5,
                top_p=0.9,
                top_k=40,
                max_output_tokens=1200,
                response_mime_type="application/json",
            ),
        )
        raw_text = response.text
        print(f"[DECOMPOSER] Gemini responded")

        # ── 4. Parse response ─────────────────────────────────────────────────
        beats = _parse_beats(raw_text)
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
            "inference_time_seconds": inference_time,
            "beats_extracted": beats_extracted,
            "tokens_used": tokens_used,
        }

    except Exception as exc:
        db.end_run("FAILED")
        raise RuntimeError(f"decompose_scene failed: {exc}") from exc


def _parse_beats(raw: str) -> List[Dict[str, Any]]:
    """
    Robustly extract the beats array from Gemini's JSON response.
    Handles both {"beats": [...]} and a bare [...] array.
    """
    import re
    
    # Try direct parse first
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "beats" in parsed:
            return parsed["beats"]
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

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
