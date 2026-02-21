"""
Script Segmentation Service

Uses the trained Databricks model for beat segmentation.
Falls back to Gemini if Databricks endpoint is unavailable.
"""

import os
import httpx
from typing import List, Dict, Any, Optional

DATABRICKS_HOST = os.getenv("DATABRICKS_HOST")
DATABRICKS_TOKEN = os.getenv("DATABRICKS_TOKEN")
ENDPOINT_NAME = "playwright-segmentation"


async def segment_with_databricks(script: str) -> Optional[List[Dict[str, Any]]]:
    """
    Call the Databricks model serving endpoint for segmentation.
    
    Returns None if the endpoint is unavailable.
    """
    if not DATABRICKS_HOST or not DATABRICKS_TOKEN:
        return None
    
    endpoint_url = f"https://{DATABRICKS_HOST}/serving-endpoints/{ENDPOINT_NAME}/invocations"
    
    headers = {
        "Authorization": f"Bearer {DATABRICKS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "inputs": [{"script": script}]
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                endpoint_url,
                headers=headers,
                json=payload,
                timeout=60.0
            )
            response.raise_for_status()
            
            result = response.json()
            
            if "predictions" in result:
                beats = result["predictions"][0].get("beats", [])
            elif "beats" in result:
                beats = result["beats"]
            else:
                beats = result.get("outputs", [{}])[0].get("beats", [])
            
            return beats
            
    except Exception as e:
        print(f"Databricks endpoint error: {e}")
        return None


async def segment_script(script: str, use_databricks: bool = True) -> List[Dict[str, Any]]:
    """
    Segment a script into beats.
    
    Tries Databricks model first, falls back to Gemini if unavailable.
    """
    if use_databricks:
        beats = await segment_with_databricks(script)
        if beats:
            return beats
    
    from services.gemini_service import analyze_script
    return await analyze_script(script)


class LocalSegmenter:
    """
    Local segmentation using rule-based approach.
    Used when both Databricks and Gemini are unavailable.
    """
    
    MOOD_KEYWORDS = {
        'tense': ['gun', 'knife', 'blood', 'scream', 'fear', 'danger', 'threat', 'dark'],
        'romantic': ['kiss', 'love', 'embrace', 'tender', 'gentle', 'heart', 'passion'],
        'action': ['run', 'fight', 'chase', 'explode', 'crash', 'punch', 'kick', 'shoot'],
        'mysterious': ['shadow', 'hidden', 'secret', 'strange', 'unknown', 'eerie'],
        'comedic': ['laugh', 'joke', 'funny', 'smile', 'grin', 'absurd'],
        'dramatic': ['cry', 'tears', 'angry', 'shout', 'confront', 'reveal'],
    }
    
    CAMERA_ANGLES = [
        'wide shot', 'medium shot', 'close-up', 'extreme close-up',
        'over-the-shoulder', 'low angle', 'high angle', 'pov shot'
    ]
    
    def __init__(self):
        import re
        self.scene_pattern = re.compile(
            r'^(INT\.|EXT\.|INT/EXT\.)\s*(.+?)(?:\s*[-–—]\s*(.+))?$',
            re.MULTILINE | re.IGNORECASE
        )
        self.character_pattern = re.compile(r'^([A-Z][A-Z\s\.\'\-]+)$', re.MULTILINE)
    
    def segment(self, script: str) -> List[Dict[str, Any]]:
        """Segment script using rules."""
        paragraphs = self._split_paragraphs(script)
        beats = []
        
        for i, para in enumerate(paragraphs[:8]):
            beat = self._create_beat(i + 1, para)
            beats.append(beat)
        
        if beats:
            beats[0]['music_recommendation'] = self._suggest_music(beats[0]['mood'])
        
        return beats
    
    def _split_paragraphs(self, script: str) -> List[str]:
        """Split into paragraph groups."""
        lines = script.strip().split('\n')
        paragraphs = []
        current = []
        
        for line in lines:
            if not line.strip():
                if current:
                    paragraphs.append('\n'.join(current))
                    current = []
            else:
                current.append(line)
        
        if current:
            paragraphs.append('\n'.join(current))
        
        merged = []
        temp = []
        for para in paragraphs:
            temp.append(para)
            if len('\n'.join(temp)) > 200 or len(temp) >= 3:
                merged.append('\n'.join(temp))
                temp = []
        
        if temp:
            merged.append('\n'.join(temp))
        
        return merged
    
    def _create_beat(self, beat_number: int, text: str) -> Dict[str, Any]:
        """Create beat from text."""
        characters = self._extract_characters(text)
        mood = self._detect_mood(text)
        camera = self._suggest_camera(text, characters)
        lighting = self._suggest_lighting(mood, text)
        visual = self._create_visual_description(text, characters)
        narrator = self._create_narrator_line(text)
        
        return {
            'beat_number': beat_number,
            'visual_description': visual,
            'camera_angle': camera,
            'mood': mood,
            'lighting': lighting,
            'characters_present': characters,
            'narrator_line': narrator,
        }
    
    def _extract_characters(self, text: str) -> List[str]:
        """Extract character names."""
        matches = self.character_pattern.findall(text)
        stopwords = {'INT', 'EXT', 'THE', 'A', 'AN', 'CUT', 'FADE'}
        return [m.strip() for m in matches if m.strip() not in stopwords][:5]
    
    def _detect_mood(self, text: str) -> str:
        """Detect mood from keywords."""
        text_lower = text.lower()
        for mood, keywords in self.MOOD_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return mood
        return 'dramatic'
    
    def _suggest_camera(self, text: str, characters: List[str]) -> str:
        """Suggest camera angle."""
        text_lower = text.lower()
        
        if 'close' in text_lower:
            return 'close-up'
        if 'wide' in text_lower or 'establishing' in text_lower:
            return 'wide shot'
        
        if len(characters) == 1:
            return 'close-up'
        elif len(characters) == 2:
            return 'over-the-shoulder'
        elif len(characters) > 2:
            return 'wide shot'
        
        return 'medium shot'
    
    def _suggest_lighting(self, mood: str, text: str) -> str:
        """Suggest lighting."""
        text_lower = text.lower()
        
        if 'night' in text_lower:
            return 'moonlit'
        if 'morning' in text_lower or 'dawn' in text_lower:
            return 'golden hour'
        
        mood_lighting = {
            'tense': 'low-key dramatic',
            'romantic': 'golden hour',
            'action': 'harsh shadows',
            'mysterious': 'low-key dramatic',
            'comedic': 'high-key bright',
            'dramatic': 'low-key dramatic',
        }
        
        return mood_lighting.get(mood, 'natural daylight')
    
    def _create_visual_description(self, text: str, characters: List[str]) -> str:
        """Create visual description."""
        parts = []
        
        scene_match = self.scene_pattern.search(text)
        if scene_match:
            parts.append(scene_match.group(2).strip())
            if scene_match.group(3):
                parts.append(scene_match.group(3).strip().lower())
        
        if characters:
            parts.append(f"{', '.join(characters[:2])} in scene")
        
        lines = [l.strip() for l in text.split('\n') if l.strip() and not l.strip().isupper()]
        if lines:
            parts.append(lines[0][:100])
        
        return '. '.join(parts) if parts else "Cinematic moment"
    
    def _create_narrator_line(self, text: str) -> str:
        """Create narrator line."""
        clean = ' '.join(text.split())
        return clean[:150]
    
    def _suggest_music(self, mood: str) -> str:
        """Suggest music."""
        suggestions = {
            'tense': 'ambient electronic tension',
            'romantic': 'soft piano with strings',
            'action': 'driving percussion',
            'mysterious': 'ethereal pads',
            'comedic': 'playful woodwinds',
            'dramatic': 'orchestral crescendo',
        }
        return suggestions.get(mood, 'cinematic underscore')
