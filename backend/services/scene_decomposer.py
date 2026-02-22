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

_SYSTEM_INSTRUCTION = """You are a professional storyboard director and AI image prompt engineer. Your output feeds directly into FLUX.1, a state-of-the-art text-to-image diffusion model. FLUX responds best to dense, specific, comma-separated prompts that combine cinematic language with concrete visual detail and pop culture references it was trained on.

Your job: break a screenplay scene into distinct visual beats. Each beat becomes one generated image.

Return ONLY valid JSON with EXACTLY these keys: scene_context, character_bible, beats.

━━━ SCENE CONTEXT (defined once, applied to every beat) ━━━

  genre         — e.g. "neo-noir thriller", "gritty crime drama", "sci-fi action", "psychological horror", "period romance"
  era           — time period + world: e.g. "present-day Gotham City", "1970s New York City", "near-future 2049 Los Angeles", "medieval fantasy"
  film_stock    — camera look: e.g. "Kodak 5219 35mm grain", "ARRI Alexa desaturated digital", "Super 8 warm overexposed", "RED Dragon 8K"
  color_grade   — dominant palette: e.g. "teal-orange blockbuster grade", "cold blue-grey desaturated", "warm golden-hour amber", "high-contrast monochrome"
  visual_style  — name a SPECIFIC FILM whose look matches: e.g. "The Dark Knight (2008)", "Blade Runner 2049", "No Country for Old Men", "Heat (1995)", "Mad Max: Fury Road", "Sicario", "Drive (2011)", "Prisoners (2013)"
  negative_space — what to avoid in every frame: e.g. "no cartoon style, no anime, no bright cheerful colors, no CGI look, no smiling faces"

━━━ CHARACTER BIBLE ━━━

  name          — exact name from the script
  description   — 180-260 chars. Physical specifics ONLY: age, build, skin tone (e.g. "deep brown", "pale freckled", "warm olive"), hair, face, outfit with colors/materials, one signature item.
                  Example: "JOKER, 35-40, lean wiry build, pale white greasepaint skin, smeared red lipstick grin, green-dyed messy hair, purple wool suit jacket over green vest, silver switchblade in hand"

━━━ BEAT FIELDS ━━━

  beat_number   — integer starting at 1

  visual_description — THE ONLY FIELD SENT TO THE IMAGE MODEL. Write it as a dense, comma-separated prompt.
                  
                  STRUCTURE (in this order):
                  1. Shot type: "extreme close-up", "wide establishing shot", "low angle medium shot", "dutch angle"
                  2. Subject + action: what is happening, using character names and specific verbs
                  3. Environment: materials and textures — "cracked concrete pillars", "neon-lit rain-slicked asphalt", "oak-paneled boardroom with fluorescent overhead", "rusted chain-link fence"
                  4. Lighting: directional and specific — "single overhead fluorescent casting harsh downward shadows", "sodium streetlight from camera-left", "golden magic-hour backlight rim"
                  5. Atmosphere: "light fog", "dust motes in shaft of light", "rain streaking the air", "cigarette smoke curling"
                  6. Style anchor: end with the specific film name from visual_style + film_stock + color_grade
                  
                  CRITICAL RULES:
                  • 250-400 characters. Every word is a model instruction.
                  • Embed the character's full physical description from character_bible inline — the model needs it every time
                  • Use named film references FLUX knows: "cinematic still from The Dark Knight", "in the style of Blade Runner 2049", "reminiscent of Heat 1995 shootout scene"
                  • Use specific material words: "brushed steel", "cracked asphalt", "worn leather", "neon-soaked glass", "raw concrete"
                  • AVOID: vague adjectives ("nice", "beautiful"), abstract emotions, narrative context the model can't visualize
                  • Every beat must look like the SAME film — same color grade, same film stock, same world

  camera_angle  — one of: wide shot, medium shot, close-up, extreme close-up, over-the-shoulder, low angle, high angle, dutch angle, POV shot, tracking shot

  mood          — happy, sad, tense, calm, melancholic, mysterious, default

  lighting      — specific and directional (used for audio/display): e.g. "single practical lamp casting long shadows", "overcast diffused daylight through frosted glass"

  color_palette — dominant colors in THIS frame: e.g. "deep navy shadows, amber skin tones, rust jacket, grey concrete floor"

  foreground_elements — depth cue in immediate foreground: e.g. "rain-slicked cobblestones blurred in extreme foreground", "out-of-focus chain-link fence", "candle flame sharp, face soft behind"
                  Use "" if the subject IS the foreground

  characters_present — array of character names visible (must match character_bible names exactly)

  visuals       — background ambiance + environmental sounds for AUDIO GENERATION ONLY. No dialogue, no music. Max 350 chars.

  narrator_line — cinematic voiceover, 100-150 characters. Poetic but grounded.

  music_style   — specific: "Hans Zimmer low drone sparse piano", "80s synth noir pulse", "sparse acoustic guitar melancholic fingerpicking"

  negative_prompt_hints — frame-specific things to avoid: e.g. "no smiling, no bright colors, no visible logos, no modern cars"

━━━ CONTINUITY RULES ━━━
1. visual_description MUST end with the specific film name + film_stock + color_grade — this makes every frame look like the same movie
2. Embed each character's full bible description inline in visual_description every time they appear
3. Environment evolves logically — rain in beat 1 means rain in beat 2 unless the script changes it
4. color_palette per beat is a specific instance of scene_context.color_grade — same palette, different composition
5. No generic filler: no "nice room", "city street", "walks forward" — every detail must be specific and visual

Return ONLY valid JSON: {"scene_context": {...}, "character_bible": [...], "beats": [...]}
No markdown, no explanation, no extra keys.
"""

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
        parsed_result = _parse_scene(raw_text)
        beats = parsed_result["beats"]
        character_bible = parsed_result.get("character_bible", [])
        scene_context = parsed_result.get("scene_context", {})
        print(f"[DECOMPOSER] Parsed {len(beats)} beats, {len(character_bible)} characters in bible, scene_context keys: {list(scene_context.keys())}")

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
            "character_bible": character_bible,
            "scene_context": scene_context,
            "inference_time_seconds": inference_time,
            "beats_extracted": beats_extracted,
            "tokens_used": tokens_used,
        }

    except Exception as exc:
        db.end_run("FAILED")
        raise RuntimeError(f"decompose_scene failed: {exc}") from exc


def _parse_scene(raw: str) -> Dict[str, Any]:
    """
    Robustly extract the full scene object (character_bible + beats) from Gemini's JSON response.
    Returns {"character_bible": [...], "beats": [...]}.
    """
    import re

    def _extract_full(parsed: Any) -> "Dict[str, Any] | None":
        """Pull scene_context, character_bible, and beats from a parsed dict."""
        if not isinstance(parsed, dict) or "beats" not in parsed:
            return None
        return {
            "scene_context": parsed.get("scene_context", {}),
            "character_bible": parsed.get("character_bible", []),
            "beats": parsed["beats"],
        }

    # Try direct parse first
    try:
        parsed = json.loads(raw)
        result = _extract_full(parsed)
        if result:
            return result
        if isinstance(parsed, list):
            return {"scene_context": {}, "character_bible": [], "beats": parsed}
        print(f"[DECOMPOSER] Parsed JSON dict but no 'beats' key — keys present: {list(parsed.keys())}")
    except json.JSONDecodeError as e:
        print(f"[DECOMPOSER] json.loads failed ({e}), attempting fallback extraction")

    # Try to find the outer object and fix common JSON issues
    obj_start = raw.find("{")
    obj_end = raw.rfind("}") + 1
    if obj_start != -1 and obj_end > obj_start:
        json_str = re.sub(r',\s*([}\]])', r'\1', raw[obj_start:obj_end])
        try:
            result = _extract_full(json.loads(json_str))
            if result:
                return result
        except json.JSONDecodeError:
            pass

    # Fall back to extracting just the beats array
    start = raw.find("[")
    end = raw.rfind("]") + 1
    if start != -1 and end > start:
        for candidate in (raw[start:end], re.sub(r',\s*([}\]])', r'\1', raw[start:end])):
            try:
                beats = json.loads(candidate)
                if isinstance(beats, list):
                    return {"scene_context": {}, "character_bible": [], "beats": beats}
            except json.JSONDecodeError:
                pass

        # Last resort: recover individual beat objects
        beats = []
        beat_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
        for match in re.findall(beat_pattern, raw[start:end]):
            try:
                beat = json.loads(re.sub(r',\s*([}\]])', r'\1', match))
                if isinstance(beat, dict) and "beat_number" in beat:
                    beats.append(beat)
            except json.JSONDecodeError:
                continue

        if beats:
            print(f"[DECOMPOSER] Recovered {len(beats)} beats from malformed JSON")
            return {"scene_context": {}, "character_bible": [], "beats": beats}

    raise ValueError(f"Could not parse scene from Gemini response: {raw[:200]}")


def _parse_beats(raw: str) -> List[Dict[str, Any]]:
    """Legacy wrapper — use _parse_scene for new code."""
    return _parse_scene(raw)["beats"]
