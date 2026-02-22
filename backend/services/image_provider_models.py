from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ImageProviderBeatPayload(BaseModel):
    beat_number: int
    visual_description: str
    camera_angle: str
    mood: str
    lighting: str
    characters_present: List[str] = Field(default_factory=list)
    narrator_line: str
    music_style: Optional[str] = None
<<<<<<< HEAD
    # Context fields for cross-beat visual consistency
    style_anchor: Optional[str] = None
    character_descriptions: Optional[List[str]] = None
    previous_beat_context: Optional[str] = None
    color_palette: Optional[str] = None
    foreground_elements: Optional[str] = None
    negative_prompt: Optional[str] = None
=======
    style_mode: Optional[str] = "photoreal"
>>>>>>> main
    width: Optional[int] = None
    height: Optional[int] = None
    steps: Optional[int] = None
    guidance_scale: Optional[float] = None
    seed: Optional[int] = None


class GenerateFrameRequest(ImageProviderBeatPayload):
    return_base64: bool = False
    save_to_disk: bool = True


class ImageProviderErrorResponse(BaseModel):
    detail: Any


class ImageProviderGenerateResponse(BaseModel):
    request_id: Optional[str] = None
    server_time_utc: Optional[str] = None
    beat_number: Optional[int] = None
    image_b64: Optional[str] = None
    prompt_used: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    requested_width: Optional[int] = None
    requested_height: Optional[int] = None
    seed_used: Optional[int] = None
    seconds: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


@dataclass
class GeneratedBeatImage:
    metadata: Dict[str, Any]
    image_bytes: bytes
    image_b64: str
