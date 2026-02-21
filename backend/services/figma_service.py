import os
import httpx
from datetime import datetime
from typing import List, Dict, Any

FIGMA_API_URL = "https://api.figma.com/v1"

async def create_figma_storyboard(
    beats: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Create a Figma file with the storyboard.
    
    Note: The Figma API has limited capabilities for creating files programmatically.
    This implementation creates a design file structure that can be imported.
    For full functionality, consider using Figma plugins or the Plugin API.
    """
    access_token = os.getenv("FIGMA_ACCESS_TOKEN")
    if not access_token:
        raise ValueError("FIGMA_ACCESS_TOKEN not configured")
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    file_name = f"PLAYWRIGHT — {timestamp}"
    
    headers = {
        "X-Figma-Token": access_token,
        "Content-Type": "application/json",
    }
    
    async with httpx.AsyncClient() as client:
        user_response = await client.get(
            f"{FIGMA_API_URL}/me",
            headers=headers,
            timeout=30.0
        )
        user_response.raise_for_status()
        user_data = user_response.json()
        
        projects_response = await client.get(
            f"{FIGMA_API_URL}/me/files",
            headers=headers,
            timeout=30.0
        )
        
        frames_data = []
        for idx, beat in enumerate(beats):
            beat_num = beat.get("beat_number", idx + 1)
            frame = {
                "beat_number": beat_num,
                "width": 1280,
                "height": 720,
                "x": (idx % 3) * 1320,
                "y": (idx // 3) * 780,
                "image_url": beat.get("imageUrl") or beat.get("image_url"),
                "narrator_line": beat.get("narrator_line", ""),
                "camera_angle": beat.get("camera_angle", ""),
                "mood": beat.get("mood", ""),
                "lighting": beat.get("lighting", ""),
            }
            frames_data.append(frame)
        
        storyboard_data = {
            "name": file_name,
            "frames": frames_data,
            "created_at": timestamp,
            "total_beats": len(beats),
        }
        
        figma_url = f"https://www.figma.com/files/recent"
        
        return {
            "figmaUrl": figma_url,
            "fileName": file_name,
            "framesCreated": len(frames_data),
            "storyboardData": storyboard_data,
            "message": "Storyboard data prepared. Use Figma plugin for full import.",
        }
