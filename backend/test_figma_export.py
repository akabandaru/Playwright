"""
Figma Export Integration Test
==============================
Tests the full Figma export pipeline end-to-end using real images from the
backend/data/ and backend/outputs/ directories (or auto-generated placeholders
if no images are present).

What this script does
---------------------
1. Discovers PNG/JPG images in the test image directories.
2. Encodes each image as a base64 data URI (the same format SDXL produces).
3. Builds a list of Beat dicts that mirror what the frontend sends.
4. Calls create_figma_storyboard() — the same function the API calls.
5. Prints a structured report:
     • Token verification result
     • Export mode (plugin_payload vs direct_patch)
     • storyboard_id  ← copy this for selective-update tests
     • Plugin payload frame count
     • Node mapping (if direct-patch mode)
6. Optionally runs a selective beat update (PATCH path) if you supply a
   FIGMA_FILE_KEY and the storyboard was already exported.

Usage
-----
# Basic test — plugin payload mode (no Figma file needed):
    cd backend
    source venv/bin/activate
    python test_figma_export.py

# Direct-patch mode (requires an existing Figma file with Beat frames):
    FIGMA_FILE_KEY=abc123XYZ python test_figma_export.py

# Test selective beat update only (requires prior export):
    FIGMA_FILE_KEY=abc123XYZ STORYBOARD_ID=<sid> python test_figma_export.py --update-only

Environment variables
---------------------
FIGMA_ACCESS_TOKEN   — read from .env automatically
FIGMA_FILE_KEY       — optional; enables direct-patch mode
STORYBOARD_ID        — optional; skip full export and only test selective update
"""

import argparse
import asyncio
import base64
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Make sure imports resolve whether you run from backend/ or project root ──
BACKEND_DIR = Path(__file__).parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv
load_dotenv(BACKEND_DIR / ".env")

from services.figma_service import create_figma_storyboard, update_beat_in_figma

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("figma_test")

# ── Directories to scan for test images (in priority order) ─────────────────
IMAGE_SEARCH_DIRS = [
    BACKEND_DIR / "data",
    BACKEND_DIR / "outputs",
    BACKEND_DIR / "scripts",
]
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

# ── Sample beat metadata (visual content doesn't matter for the API test) ───
BEAT_TEMPLATES = [
    {
        "camera_angle": "Wide Shot",
        "mood": "tense",
        "lighting": "Low-key, harsh shadows",
        "narrator_line": "The city never sleeps — and neither does the guilt.",
        "music_recommendation": "Dark ambient, 80 BPM",
        "characters_present": ["Detective Kane"],
        "visual_description": "Rain-slicked streets, neon reflections, lone figure.",
    },
    {
        "camera_angle": "Close-Up",
        "mood": "melancholic",
        "lighting": "Soft side-light, golden hour",
        "narrator_line": "She left without a word. Just the scent of jasmine.",
        "music_recommendation": "Solo piano, rubato",
        "characters_present": ["Elena"],
        "visual_description": "A woman's silhouette against a frosted window.",
    },
    {
        "camera_angle": "Extreme Close-Up",
        "mood": "tense",
        "lighting": "High contrast, single source",
        "narrator_line": "The gun was cold. His hands were colder.",
        "music_recommendation": "Strings, staccato",
        "characters_present": ["Detective Kane"],
        "visual_description": "Fingers wrapping around a revolver grip.",
    },
    {
        "camera_angle": "Medium Shot",
        "mood": "calm",
        "lighting": "Diffused natural light",
        "narrator_line": "In the end, the truth was simpler than the lie.",
        "music_recommendation": "Acoustic guitar, fingerpicked",
        "characters_present": ["Detective Kane", "Elena"],
        "visual_description": "Two figures facing each other across a kitchen table.",
    },
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _find_images(max_count: int = 4) -> List[Path]:
    """Scan the search directories and return up to max_count image paths."""
    found: List[Path] = []
    for d in IMAGE_SEARCH_DIRS:
        if not d.exists():
            continue
        for p in sorted(d.iterdir()):
            if p.suffix.lower() in IMAGE_EXTENSIONS:
                found.append(p)
                if len(found) >= max_count:
                    return found
    return found


def _image_to_data_uri(path: Path) -> str:
    """Read an image file and return a base64 data URI."""
    suffix = path.suffix.lower().lstrip(".")
    mime = "image/jpeg" if suffix in ("jpg", "jpeg") else f"image/{suffix}"
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode()
    return f"data:{mime};base64,{b64}"


def _generate_placeholder_data_uri(beat_number: int, width: int = 640, height: int = 360) -> str:
    """
    Generate a minimal solid-colour PNG as a placeholder when no real images
    are found.  Uses only stdlib — no Pillow required.
    """
    import struct
    import zlib

    # Pick a distinct colour per beat
    colours = [
        (30, 60, 114),   # deep blue
        (90, 30, 90),    # purple
        (20, 80, 60),    # forest green
        (100, 40, 20),   # burnt orange
    ]
    r, g, b = colours[(beat_number - 1) % len(colours)]

    def _pack_chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    # PNG signature
    sig = b"\x89PNG\r\n\x1a\n"
    # IHDR
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = _pack_chunk(b"IHDR", ihdr_data)
    # IDAT — one row per scanline, filter byte 0x00 + RGB pixels
    raw_rows = b""
    row = bytes([0]) + bytes([r, g, b] * width)
    raw_rows = row * height
    compressed = zlib.compress(raw_rows, 9)
    idat = _pack_chunk(b"IDAT", compressed)
    # IEND
    iend = _pack_chunk(b"IEND", b"")

    png_bytes = sig + ihdr + idat + iend
    b64 = base64.b64encode(png_bytes).decode()
    return f"data:image/png;base64,{b64}"


def _build_beats(image_paths: List[Path]) -> List[Dict[str, Any]]:
    """
    Combine image files with beat metadata templates to produce the beat dicts
    that the Figma service expects.
    """
    beats: List[Dict[str, Any]] = []
    num_beats = max(len(image_paths), len(BEAT_TEMPLATES))

    for i in range(num_beats):
        template = BEAT_TEMPLATES[i % len(BEAT_TEMPLATES)].copy()
        beat_number = i + 1

        if i < len(image_paths):
            image_url = _image_to_data_uri(image_paths[i])
            source = image_paths[i].name
        else:
            image_url = _generate_placeholder_data_uri(beat_number)
            source = f"placeholder_{beat_number}.png (generated)"

        beat = {
            "beat_number": beat_number,
            "imageUrl": image_url,
            "image_url": image_url,
            "_image_source": source,  # informational only
            **template,
        }
        beats.append(beat)
        logger.info("  Beat %d  ← %s  (%d bytes)", beat_number, source, len(image_url))

    return beats


def _print_section(title: str) -> None:
    width = 60
    print(f"\n{'─' * width}")
    print(f"  {title}")
    print(f"{'─' * width}")


def _pretty(obj: Any, indent: int = 2) -> str:
    """JSON-pretty-print, truncating long base64 strings."""
    def _truncate(o: Any) -> Any:
        if isinstance(o, str) and o.startswith("data:") and len(o) > 80:
            return o[:60] + f"…[{len(o)} chars]"
        if isinstance(o, dict):
            return {k: _truncate(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_truncate(v) for v in o]
        return o
    return json.dumps(_truncate(obj), indent=indent, ensure_ascii=False)


# ── Main test logic ───────────────────────────────────────────────────────────

async def run_full_export(
    file_key: Optional[str],
    storyboard_id: Optional[str],
) -> str:
    """Run a full storyboard export and return the storyboard_id."""
    _print_section("STEP 1 — Discover test images")
    image_paths = _find_images(max_count=4)
    if image_paths:
        print(f"  Found {len(image_paths)} image(s):")
        for p in image_paths:
            print(f"    {p}")
    else:
        print("  No images found — will use generated colour placeholders.")

    beats = _build_beats(image_paths)

    _print_section("STEP 2 — Call create_figma_storyboard()")
    mode = "direct_patch" if file_key else "plugin_payload"
    print(f"  Export mode  : {mode}")
    print(f"  Beat count   : {len(beats)}")
    if file_key:
        print(f"  Target file  : {file_key}")
    if storyboard_id:
        print(f"  Storyboard ID: {storyboard_id}")

    # Strip the informational _image_source key before passing to the service
    clean_beats = [{k: v for k, v in b.items() if k != "_image_source"} for b in beats]

    result = await create_figma_storyboard(
        clean_beats,
        storyboard_id=storyboard_id,
        target_file_key=file_key or None,
    )

    _print_section("STEP 3 — Export result")
    print(_pretty({k: v for k, v in result.items() if k != "pluginPayload"}))

    if result.get("exportMode") == "plugin_payload":
        payload = result.get("pluginPayload", {})
        _print_section("Plugin payload summary")
        print(f"  storyboard_id : {result['storyboard_id']}")
        print(f"  file_name     : {payload.get('file_name')}")
        print(f"  page_name     : {payload.get('page_name')}")
        print(f"  frames        : {len(payload.get('frames', []))}")
        print(f"  canvas_width  : {payload.get('canvas_width')} px")
        print()
        print("  Frame layout:")
        for frame in payload.get("frames", []):
            children = frame.get("children", [])
            child_names = [c["name"] for c in children]
            print(
                f"    [{frame['name']}]  x={frame['x']} y={frame['y']}  "
                f"children={child_names}"
            )

    if result.get("errors"):
        _print_section("Errors")
        for err in result["errors"]:
            print(f"  ⚠  {err}")

    sid = result["storyboard_id"]
    print(f"\n  ✓ storyboard_id = {sid}")
    print("    (use this with --storyboard-id for the selective update test)")
    return sid


async def run_selective_update(storyboard_id: str, file_key: str) -> None:
    """Run a selective beat update for beat 1 using the first available image."""
    _print_section("SELECTIVE UPDATE — PATCH beat 1")
    print(f"  storyboard_id : {storyboard_id}")
    print(f"  file_key      : {file_key}")

    image_paths = _find_images(max_count=1)
    if image_paths:
        new_image_url = _image_to_data_uri(image_paths[0])
        print(f"  New image     : {image_paths[0].name}")
    else:
        new_image_url = _generate_placeholder_data_uri(beat_number=99)
        print("  New image     : generated placeholder (magenta)")

    updated_beat = {
        "beat_number": 1,
        "imageUrl": new_image_url,
        "image_url": new_image_url,
        "narrator_line": "UPDATED — selective regeneration test.",
        "camera_angle": "Extreme Wide Shot",
        "mood": "mysterious",
        "lighting": "Moonlit, deep blue",
        "visual_description": "Updated visual.",
        "characters_present": [],
    }

    result = await update_beat_in_figma(storyboard_id, 1, updated_beat)

    _print_section("Selective update result")
    print(_pretty(result))


async def main(args: argparse.Namespace) -> None:
    token = os.getenv("FIGMA_ACCESS_TOKEN", "")
    if not token:
        print("ERROR: FIGMA_ACCESS_TOKEN is not set. Check backend/.env")
        sys.exit(1)

    print(f"\n{'═' * 60}")
    print("  PLAYWRIGHT — Figma Export Integration Test")
    print(f"{'═' * 60}")
    print(f"  Token        : {token[:12]}…{token[-4:]}")
    print(f"  File key     : {args.file_key or '(none — plugin payload mode)'}")
    print(f"  Update only  : {args.update_only}")

    if args.update_only:
        if not args.storyboard_id:
            print("ERROR: --storyboard-id is required with --update-only")
            sys.exit(1)
        if not args.file_key:
            print("ERROR: --file-key is required with --update-only")
            sys.exit(1)
        await run_selective_update(args.storyboard_id, args.file_key)
    else:
        sid = await run_full_export(args.file_key, args.storyboard_id)
        if args.file_key and not args.skip_update:
            print("\n  Running selective update test on the same storyboard…")
            await run_selective_update(sid, args.file_key)

    print(f"\n{'═' * 60}")
    print("  Test complete.")
    print(f"{'═' * 60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Test the Figma export integration end-to-end.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--file-key",
        default=os.getenv("FIGMA_FILE_KEY", ""),
        help="Figma file key for direct-patch mode (env: FIGMA_FILE_KEY)",
    )
    parser.add_argument(
        "--storyboard-id",
        default=os.getenv("STORYBOARD_ID", ""),
        help="Reuse an existing storyboard_id instead of generating a new one",
    )
    parser.add_argument(
        "--update-only",
        action="store_true",
        help="Skip full export and only test selective beat update",
    )
    parser.add_argument(
        "--skip-update",
        action="store_true",
        help="Skip the selective update step after a full export",
    )
    args = parser.parse_args()
    asyncio.run(main(args))
