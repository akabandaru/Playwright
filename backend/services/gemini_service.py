import os
import json
import google.generativeai as genai
from typing import List, Dict, Any

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

SYSTEM_PROMPT = """You are a professional film director and screenwriter analyzing scripts to create detailed storyboards.

Given a script or scene, break it down into 4-8 visual beats. Each beat represents a distinct camera shot or moment.

For each beat, provide:
1. beat_number: Sequential number starting from 1
2. visual_description: Detailed description of what's visible in the frame (characters, setting, actions, props)
3. camera_angle: One of: "wide shot", "medium shot", "close-up", "extreme close-up", "over-the-shoulder", "low angle", "high angle", "dutch angle", "POV shot", "tracking shot"
4. mood: The emotional tone (e.g., "tense", "romantic", "mysterious", "action", "melancholic", "hopeful", "dark", "serene")
5. lighting: Lighting style (e.g., "low-key dramatic", "high-key bright", "natural daylight", "golden hour", "neon noir", "candlelit", "moonlit", "harsh shadows")
6. characters_present: Array of character names visible in this beat
7. narrator_line: A narrator voiceover line for this beat (100-150 characters max). Should be evocative and cinematic.
8. music_recommendation: ONLY for beat_number 1, suggest a music style/track type (e.g., "ambient electronic tension", "orchestral strings crescendo")

Return ONLY a valid JSON array of beat objects. No additional text or explanation."""

async def analyze_script(script: str) -> List[Dict[str, Any]]:
    """Analyze a script and return structured beat breakdown."""
    model = genai.GenerativeModel(
        model_name="gemini-1.5-pro",
        generation_config={
            "temperature": 0.7,
            "top_p": 0.95,
            "top_k": 40,
            "max_output_tokens": 8192,
            "response_mime_type": "application/json",
        },
    )
    
    chat = model.start_chat(history=[])
    
    prompt = f"""{SYSTEM_PROMPT}

SCRIPT TO ANALYZE:
{script}

Return the JSON array of beats:"""

    response = await chat.send_message_async(prompt)
    
    try:
        beats = json.loads(response.text)
        if isinstance(beats, dict) and "beats" in beats:
            beats = beats["beats"]
        return beats
    except json.JSONDecodeError:
        text = response.text
        start = text.find('[')
        end = text.rfind(']') + 1
        if start != -1 and end > start:
            return json.loads(text[start:end])
        raise ValueError("Failed to parse Gemini response as JSON")
