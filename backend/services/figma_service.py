"""
Figma Integration Service — Production Grade

Capabilities:
  1. Full storyboard export  — POST /api/export-figma
  2. Selective beat update   — PATCH /api/export-figma/{storyboard_id}/beat/{beat_number}
  3. Node mapping retrieval  — GET  /api/export-figma/{storyboard_id}/mapping

Architecture notes
------------------
The Figma REST API is read-heavy; it does NOT expose a "create file" endpoint for
personal-access-token callers.  The canonical write path for programmatic layout is
the Figma Plugin API (runs inside the Figma desktop/web app).

This service therefore uses a two-pronged strategy:

  A) **Direct REST writes** — available operations:
       • POST  /v1/files/{file_key}/images   → upload a raster image, get imageRef
       • PATCH /v1/files/{file_key}/nodes    → update node properties (fill, text, etc.)
       • GET   /v1/files/{file_key}          → read the current document tree
       • GET   /v1/files/{file_key}/nodes    → read specific nodes

  B) **Storyboard data payload** — when a target file_key is provided the service
     uploads each beat image and patches the corresponding frame node.  When no
     file_key is given it returns a fully-structured JSON payload that a companion
     Figma plugin can consume to create the file client-side.

Node mapping is persisted via figma_node_store so every subsequent selective-update
call can locate the exact node to patch without re-reading the whole document.

Layout conventions (mirrored in the plugin companion):
  • Canvas page name : "Storyboard"
  • Frame size       : 1280 × 720 px
  • Grid             : 3 columns, 40 px gap
  • Frame name       : "Beat {n} — {mood}"
  • Child nodes      :
      - image_fill   : rectangle covering the full frame (imageRef fill)
      - label        : text node at bottom-left  (narrator_line, max 2 lines)
      - meta         : text node at top-right    (camera_angle · lighting)
"""

import base64
import io
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from services.figma_node_store import (
    delete_storyboard,
    get_beat_nodes,
    get_storyboard,
    list_storyboards,
    set_plugin_payload,
    upsert_beat_nodes,
    upsert_storyboard,
)

logger = logging.getLogger(__name__)

FIGMA_API_URL = "https://api.figma.com/v1"

# Base URL the Figma plugin sandbox will use to fetch images.
# Override with BACKEND_PUBLIC_URL in .env when deploying.
BACKEND_BASE_URL = os.getenv("BACKEND_PUBLIC_URL", "http://localhost:8000").rstrip("/")

# Layout constants — comic book panel grid (3 cols × 4 rows = 12 panels)
FRAME_W      = 960    # panel width  (matches Figma template)
FRAME_H      = 720    # panel height (matches Figma template)
GRID_COLS    = 3      # 3 columns → 4 rows for 12 beats
GRID_GAP_X   = 12     # tight comic-book gutter between columns
GRID_GAP_Y   = 12     # tight comic-book gutter between rows
CANVAS_PAD   = 60     # outer page margin on all sides
BORDER_W     = 4      # panel border inset (image_fill offset)
# Child layer geometry — derived from template spec
IMAGE_X      = BORDER_W          # 4
IMAGE_Y      = BORDER_W          # 4
IMAGE_W      = FRAME_W - BORDER_W * 2   # 952
IMAGE_H      = FRAME_H - BORDER_W * 2   # 712
CAPTION_Y    = 648    # caption_bg top-y
CAPTION_H    = 64     # caption_bg height  (648 + 64 = 712 = bottom of image)
LABEL_X      = 18     # label text x
LABEL_Y      = 656    # label text y  (caption_bg y + 8)
LABEL_W      = 924    # label text width
LABEL_H      = 48     # label text height
META_X       = 706    # meta text x  (top-right)
META_Y       = 12     # meta text y
META_W       = 240    # meta text width
META_H       = 28     # meta text height
BEAT_NUM_X   = 14     # beat_number badge x
BEAT_NUM_Y   = 12     # beat_number badge y
BEAT_NUM_W   = 60     # beat_number badge width
BEAT_NUM_H   = 28     # beat_number badge height


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _token() -> str:
    token = os.getenv("FIGMA_ACCESS_TOKEN", "")
    if not token:
        raise ValueError("FIGMA_ACCESS_TOKEN is not configured")
    return token


def _headers() -> Dict[str, str]:
    return {
        "X-Figma-Token": _token(),
        "Content-Type": "application/json",
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _frame_position(index: int) -> Tuple[int, int]:
    """Return (x, y) canvas position for the nth beat frame."""
    col = index % GRID_COLS
    row = index // GRID_COLS
    x = CANVAS_PAD + col * (FRAME_W + GRID_GAP_X)
    y = CANVAS_PAD + row * (FRAME_H + GRID_GAP_Y)
    return x, y


async def _verify_token(client: httpx.AsyncClient) -> Dict[str, Any]:
    """Verify the Figma token and return the /me payload."""
    resp = await client.get(f"{FIGMA_API_URL}/me", headers=_headers(), timeout=15.0)
    resp.raise_for_status()
    return resp.json()


async def _upload_image(
    client: httpx.AsyncClient,
    file_key: str,
    image_data: bytes,
    content_type: str = "image/png",
) -> str:
    """
    Upload a raster image to a Figma file and return the imageRef hash.

    Figma endpoint: POST /v1/files/{file_key}/images
    Content-Type must be multipart/form-data.
    Returns the imageRef string used in image-fill nodes.
    """
    upload_headers = {"X-Figma-Token": _token()}
    files = {"image": ("image.png", image_data, content_type)}
    resp = await client.post(
        f"{FIGMA_API_URL}/files/{file_key}/images",
        headers=upload_headers,
        files=files,
        timeout=60.0,
    )
    resp.raise_for_status()
    data = resp.json()
    image_ref = data.get("meta", {}).get("images", {})
    if not image_ref:
        raise RuntimeError(f"Figma image upload returned unexpected payload: {data}")
    return next(iter(image_ref.values()))


async def _patch_node(
    client: httpx.AsyncClient,
    file_key: str,
    node_id: str,
    properties: Dict[str, Any],
) -> None:
    """
    Patch a single node's properties via PATCH /v1/files/{file_key}/nodes.
    """
    payload = {
        "nodes": {
            node_id: {
                "document": properties,
            }
        }
    }
    resp = await client.patch(
        f"{FIGMA_API_URL}/files/{file_key}/nodes",
        headers=_headers(),
        json=payload,
        timeout=30.0,
    )
    resp.raise_for_status()


async def _fetch_file_nodes(
    client: httpx.AsyncClient,
    file_key: str,
    node_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Fetch the document tree (or specific nodes) from a Figma file.
    """
    url = f"{FIGMA_API_URL}/files/{file_key}"
    params: Dict[str, Any] = {}
    if node_ids:
        params["ids"] = ",".join(node_ids)
        url = f"{FIGMA_API_URL}/files/{file_key}/nodes"
    resp = await client.get(url, headers=_headers(), params=params, timeout=30.0)
    resp.raise_for_status()
    return resp.json()


def _decode_image_url(image_url: str) -> Tuple[bytes, str]:
    """
    Accept either a base64 data URL (data:image/png;base64,...) or a plain
    http/https URL and return (raw_bytes, content_type).
    """
    if image_url.startswith("data:"):
        header, encoded = image_url.split(",", 1)
        content_type = header.split(";")[0].replace("data:", "")
        return base64.b64decode(encoded), content_type
    raise ValueError(
        f"Remote image URLs require an async HTTP fetch; got: {image_url[:80]}"
    )


async def _fetch_remote_image(
    client: httpx.AsyncClient, url: str
) -> Tuple[bytes, str]:
    """Download a remote image and return (bytes, content_type)."""
    resp = await client.get(url, timeout=30.0, follow_redirects=True)
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "image/png").split(";")[0]
    return resp.content, content_type


async def _resolve_image(
    client: httpx.AsyncClient, image_url: str
) -> Tuple[bytes, str]:
    """Resolve an image URL (data URI or remote) to raw bytes + content-type."""
    if image_url.startswith("data:"):
        return _decode_image_url(image_url)
    return await _fetch_remote_image(client, image_url)


# ---------------------------------------------------------------------------
# Beat frame builder (used for the plugin-payload path)
# ---------------------------------------------------------------------------

def _build_beat_frame(beat: Dict[str, Any], index: int) -> Dict[str, Any]:
    """
    Build the JSON payload for a single comic-book panel.

    Layer stack (bottom → top), matching the Figma template exactly:
      image_fill   — full-bleed image rectangle, inset 4px
      caption_bg   — semi-opaque black bar behind the narrator text
      label        — narrator line text (Inter 15px SemiBold, white)
      beat_number  — yellow badge top-left (#01 … #12)
      meta         — camera · lighting text top-right (Inter 11px Medium)
    """
    x, y = _frame_position(index)
    beat_num = beat.get("beat_number", index + 1)
    camera   = beat.get("camera_angle", "")
    lighting = beat.get("lighting", "")
    narrator = beat.get("narrator_line", "")
    image_url = beat.get("imageUrl") or beat.get("image_url") or ""
    if image_url and not image_url.startswith("http"):
        image_url = BACKEND_BASE_URL + image_url

    meta_text = f"{camera}  ·  {lighting}" if (camera or lighting) else ""

    return {
        "type": "FRAME",
        "name": f"Beat {beat_num}",
        "x": x,
        "y": y,
        "width": FRAME_W,
        "height": FRAME_H,
        "clipsContent": True,
        # imageUrl at top level so the plugin can find it without walking children
        "imageUrl": image_url,
        "fills": [{"type": "SOLID", "color": {"r": 0.051, "g": 0.051, "b": 0.051}}],
        "strokes": [{"type": "SOLID", "color": {"r": 0, "g": 0, "b": 0}}],
        "strokeWeight": BORDER_W,
        "strokeAlign": "INSIDE",
        "children": [
            # ── image_fill: full-bleed image, inset by border width ───────────
            {
                "type": "RECTANGLE",
                "name": "image_fill",
                "x": IMAGE_X,
                "y": IMAGE_Y,
                "width": IMAGE_W,
                "height": IMAGE_H,
                "fills": [
                    {
                        "type": "IMAGE",
                        "scaleMode": "FILL",
                        "imageUrl": image_url,
                    }
                ],
            },
            # ── caption_bg: semi-opaque black bar behind narrator text ────────
            {
                "type": "RECTANGLE",
                "name": "caption_bg",
                "x": IMAGE_X,
                "y": CAPTION_Y,
                "width": IMAGE_W,
                "height": CAPTION_H,
                "fills": [
                    {"type": "SOLID", "color": {"r": 0, "g": 0, "b": 0}, "opacity": 0.82}
                ],
            },
            # ── label: narrator line inside the caption box ───────────────────
            {
                "type": "TEXT",
                "name": "label",
                "x": LABEL_X,
                "y": LABEL_Y,
                "width": LABEL_W,
                "height": LABEL_H,
                "characters": narrator,
                "style": {
                    "fontFamily": "Inter",
                    "fontSize": 15,
                    "fontWeight": 600,
                    "fills": [{"type": "SOLID", "color": {"r": 1, "g": 1, "b": 1, "a": 1}}],
                    "letterSpacing": 0.1,
                },
            },
            # ── beat_number: yellow badge top-left ────────────────────────────
            {
                "type": "TEXT",
                "name": "beat_number",
                "x": BEAT_NUM_X,
                "y": BEAT_NUM_Y,
                "width": BEAT_NUM_W,
                "height": BEAT_NUM_H,
                "characters": f"#{beat_num:02d}",
                "style": {
                    "fontFamily": "Inter",
                    "fontSize": 14,
                    "fontWeight": 700,
                    "fills": [{"type": "SOLID", "color": {"r": 1, "g": 1, "b": 0, "a": 1}}],
                    "letterSpacing": 0.5,
                },
            },
            # ── meta: camera · lighting, top-right ───────────────────────────
            {
                "type": "TEXT",
                "name": "meta",
                "x": META_X,
                "y": META_Y,
                "width": META_W,
                "height": META_H,
                "characters": meta_text,
                "style": {
                    "fontFamily": "Inter",
                    "fontSize": 11,
                    "fontWeight": 500,
                    "fills": [{"type": "SOLID", "color": {"r": 1, "g": 1, "b": 1, "a": 0.80}}],
                    "textAlignHorizontal": "RIGHT",
                    "letterSpacing": 0.3,
                },
            },
        ],
    }


# ---------------------------------------------------------------------------
# Core public functions
# ---------------------------------------------------------------------------

async def create_figma_storyboard(
    beats: List[Dict[str, Any]],
    *,
    storyboard_id: Optional[str] = None,
    target_file_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Export all beats to Figma.

    Resolution order for the target file:
      1. target_file_key argument (explicit, e.g. from the frontend)
      2. FIGMA_TEMPLATE_FILE_KEY env var  → one-click "Export to Figma" button mode
      3. Neither set                      → plugin payload (JSON for the Figma plugin)

    Template mode (option 2) is the recommended production path:
      • Create a blank Figma file once with frames named "Beat 1" … "Beat N"
        (run `python setup_figma_template.py` for step-by-step guidance)
      • Set FIGMA_TEMPLATE_FILE_KEY=<key> in .env
      • Every export patches images into those frames; unused frames are hidden;
        frames are made visible again on the next export

    Parameters
    ----------
    beats            : list of beat dicts (must include imageUrl / image_url)
    storyboard_id    : stable ID for this storyboard (auto-generated if omitted)
    target_file_key  : explicit Figma file key (overrides env var)
    """
    if not beats:
        raise ValueError("beats list cannot be empty")

    sid = storyboard_id or str(uuid.uuid4())
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    file_name = f"PLAYWRIGHT — {timestamp}"

    # Resolve the file key: explicit arg → env var → plugin payload fallback
    resolved_key = (
        target_file_key
        or os.getenv("FIGMA_TEMPLATE_FILE_KEY", "").strip()
        or ""
    )

    if not resolved_key:
        # No template configured — plugin creates new frames from scratch
        logger.info(
            "FIGMA_TEMPLATE_FILE_KEY not set — returning create_frames plugin payload."
        )
        return _build_plugin_payload(beats, sid, file_name)

    # Template key is set — fetch the template's node IDs and build a patch payload
    # that the plugin will apply to the existing frames via figma.getNodeById().
    logger.info(
        "FIGMA_TEMPLATE_FILE_KEY=%s — building template patch payload for plugin.",
        resolved_key,
    )
    try:
        return await _build_template_patch_payload(beats, sid, file_name, resolved_key)
    except Exception as exc:
        logger.warning(
            "Template patch payload build failed (%s) — falling back to create_frames mode.",
            exc,
        )
        return _build_plugin_payload(beats, sid, file_name)


async def _patch_frame_visibility(
    client: httpx.AsyncClient,
    file_key: str,
    frame_node_id: str,
    visible: bool,
) -> None:
    """Show or hide a frame by patching its visible property."""
    try:
        await _patch_node(client, file_key, frame_node_id, {"visible": visible})
    except Exception as exc:
        logger.warning("Could not set visibility on node %s: %s", frame_node_id, exc)


def _find_node_by_name(node: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    """
    Recursively search a node tree for the first node whose name matches exactly.
    Used to locate label/meta text nodes that may be nested inside wrapper frames.
    """
    if node.get("name") == name:
        return node
    for child in node.get("children", []):
        found = _find_node_by_name(child, name)
        if found:
            return found
    return None


def _find_image_container(node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Find the best node to use as the image fill target inside a panel frame.

    Resolution order:
      1. A child named "image_fill" (explicit, flat structure)
      2. A child named "image_fill" anywhere in the subtree (nested structure)
      3. The largest RECTANGLE or FRAME child that has no TEXT children
         (heuristic for templates that use an unnamed image placeholder)
    """
    # 1. Direct child named image_fill
    for child in node.get("children", []):
        if child.get("name") == "image_fill":
            return child

    # 2. Recursive search for image_fill
    found = _find_node_by_name(node, "image_fill")
    if found:
        return found

    # 3. Heuristic: find the largest non-text container child
    best: Optional[Dict[str, Any]] = None
    best_area = 0
    for child in node.get("children", []):
        ctype = child.get("type", "")
        if ctype not in ("RECTANGLE", "FRAME"):
            continue
        # Skip containers that only hold text
        child_types = {c.get("type") for c in child.get("children", [])}
        if child_types and child_types <= {"TEXT"}:
            continue
        bb = child.get("absoluteBoundingBox") or {}
        area = bb.get("width", 0) * bb.get("height", 0)
        if area > best_area:
            best_area = area
            best = child
    return best


def _find_upload_placeholder(image_container: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Find the upload placeholder overlay inside an image container.
    This is the child named 'Label' that shows 'Upload Image / or drag & drop'.
    It needs to be hidden once a real image is applied.
    """
    for child in image_container.get("children", []):
        if child.get("name") == "Label":
            return child
    return None


def _find_text_node_in_wrapper(wrapper: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Given a FRAME wrapper (e.g. the 'label' or 'meta' frame), find the first
    TEXT node inside it. Handles both flat (TEXT direct child) and nested layouts.
    """
    if wrapper.get("type") == "TEXT":
        return wrapper
    for child in wrapper.get("children", []):
        if child.get("type") == "TEXT":
            return child
        # One more level deep
        for grandchild in child.get("children", []):
            if grandchild.get("type") == "TEXT":
                return grandchild
    return None


def _collect_template_panels(page: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Discover the ordered list of panel frames from the template page.

    Strategy (tried in order):
      1. Direct children named "Beat N" — standard flat layout.
      2. Walk the full subtree and collect all nodes named "Beat N".
      3. Fall back to the largest flat Container child whose children are all
         FRAME nodes — this handles the "Comicbook storyboard template" layout
         where panels are unnamed Container frames inside a grid Container.
    """
    # Strategy 1 & 2: look for Beat-named frames anywhere on the page
    beat_index: Dict[int, Dict[str, Any]] = {}

    def _collect_beats(node: Dict[str, Any]) -> None:
        name: str = node.get("name", "")
        if name.startswith("Beat "):
            try:
                n = int(name.split(" ")[1])
                beat_index[n] = node
            except (IndexError, ValueError):
                pass
        for child in node.get("children", []):
            _collect_beats(child)

    _collect_beats(page)
    if beat_index:
        return [beat_index[k] for k in sorted(beat_index)]

    # Strategy 3: find the grid container — the child of the top-level frame
    # whose children are all FRAME nodes and has the most children.
    best_container: Optional[Dict[str, Any]] = None
    best_count = 0

    def _find_grid_container(node: Dict[str, Any], depth: int = 0) -> None:
        nonlocal best_container, best_count
        children = node.get("children", [])
        frame_children = [c for c in children if c.get("type") == "FRAME"]
        # A grid container has multiple frame children and is not itself a leaf
        if len(frame_children) >= 4 and len(frame_children) > best_count:
            # Make sure these children look like panels (have sub-children)
            has_content = any(c.get("children") for c in frame_children)
            if has_content:
                best_count = len(frame_children)
                best_container = node
        for child in children:
            if depth < 4:
                _find_grid_container(child, depth + 1)

    _find_grid_container(page)
    if best_container:
        panels = [c for c in best_container.get("children", []) if c.get("type") == "FRAME"]
        logger.info(
            "Template panel discovery: found %d panels via grid-container heuristic "
            "(container: '%s')",
            len(panels), best_container.get("name", ""),
        )
        return panels

    return []


async def _export_to_existing_file(
    client: httpx.AsyncClient,
    beats: List[Dict[str, Any]],
    storyboard_id: str,
    file_key: str,
    file_name: str,
) -> Dict[str, Any]:
    """
    Upload beat images and patch nodes in an existing Figma file.

    Template beat-count mismatch handling
    ──────────────────────────────────────
    The template may have more or fewer panel slots than the current storyboard:

    • Fewer beats than template slots  → unused panels are left untouched.
    • More beats than template slots   → extra beats are noted in overflow_beats.

    Panel discovery (tried in order):
      1. Direct page children named "Beat N" (flat layout).
      2. Any node named "Beat N" anywhere in the tree.
      3. Heuristic: the largest grid Container whose children are all FRAMEs
         (handles templates like "Comicbook storyboard template" where panels
         are unnamed Container frames inside a grid).

    Node discovery within each panel (recursive):
      • image_fill — rectangle/frame to patch with the generated image.
        Falls back to the largest non-text FRAME/RECTANGLE child.
      • label      — TEXT node for the narrator line (searched recursively).
      • meta       — TEXT node for camera · lighting (searched recursively).
    """
    doc = await _fetch_file_nodes(client, file_key)
    pages = doc.get("document", {}).get("children", [])
    if not pages:
        raise RuntimeError("Figma file has no pages")

    target_page = next(
        (p for p in pages if p.get("name") == "Storyboard"),
        pages[0],
    )
    page_id = target_page["id"]
    page_name = target_page["name"]

    # Discover panels using the flexible multi-strategy approach
    panels = _collect_template_panels(target_page)
    template_slots = len(panels)
    beat_numbers = [b.get("beat_number", i + 1) for i, b in enumerate(beats)]

    logger.info(
        "Template has %d panel slot(s) | Export has %d beat(s): %s",
        template_slots, len(beat_numbers), beat_numbers,
    )

    if template_slots == 0:
        logger.warning(
            "No template panels found — falling back to plugin payload. "
            "Ensure the template page has Beat-named frames or a grid of panel frames."
        )
        return _build_plugin_payload(beats, storyboard_id, file_name)

    upsert_storyboard(
        storyboard_id,
        file_key=file_key,
        file_url=f"https://www.figma.com/file/{file_key}",
        file_name=file_name,
        page_id=page_id,
        page_name=page_name,
    )

    node_mapping: Dict[str, Any] = {}
    errors: List[str] = []
    overflow_beats: List[int] = []

    # ── Pass 1: patch each beat into its corresponding panel slot ────────────
    for beat in beats:
        beat_num = beat.get("beat_number", 0)
        slot_index = beat_num - 1  # beat_number is 1-based
        image_url = beat.get("imageUrl") or beat.get("image_url") or ""

        if slot_index < 0 or slot_index >= template_slots:
            logger.warning(
                "Beat %d has no template slot (template has %d panel(s))",
                beat_num, template_slots,
            )
            overflow_beats.append(beat_num)
            continue

        panel = panels[slot_index]
        frame_node_id = panel["id"]

        # Locate child nodes — search recursively to handle nested wrappers
        image_node = _find_image_container(panel)
        label_node = _find_node_by_name(panel, "label")
        meta_node  = _find_node_by_name(panel, "meta")

        image_node_id = image_node["id"] if image_node else ""
        label_node_id = label_node["id"] if label_node else ""
        meta_node_id  = meta_node["id"]  if meta_node  else ""

        logger.info(
            "Beat %d → panel '%s' | image_node=%s label_node=%s meta_node=%s",
            beat_num, panel.get("name", ""), image_node_id, label_node_id, meta_node_id,
        )

        if image_url and image_node_id:
            try:
                img_bytes, content_type = await _resolve_image(client, image_url)
                image_ref = await _upload_image(client, file_key, img_bytes, content_type)
                await _patch_node(
                    client,
                    file_key,
                    image_node_id,
                    {"fills": [{"type": "IMAGE", "scaleMode": "FILL", "imageRef": image_ref}]},
                )
            except Exception as exc:
                logger.error("Beat %d image upload failed: %s", beat_num, exc)
                errors.append(f"Beat {beat_num}: image upload failed — {exc}")
        elif image_url and not image_node_id:
            logger.warning(
                "Beat %d: no image node found in panel '%s' — image not patched",
                beat_num, panel.get("name", ""),
            )

        if label_node_id and beat.get("narrator_line"):
            try:
                await _patch_node(
                    client, file_key, label_node_id,
                    {"characters": beat["narrator_line"]},
                )
            except Exception as exc:
                logger.warning("Beat %d label patch failed: %s", beat_num, exc)

        if meta_node_id:
            meta_text = f"{beat.get('camera_angle', '')} · {beat.get('lighting', '')}"
            try:
                await _patch_node(
                    client, file_key, meta_node_id, {"characters": meta_text}
                )
            except Exception as exc:
                logger.warning("Beat %d meta patch failed: %s", beat_num, exc)

        upsert_beat_nodes(
            storyboard_id, beat_num,
            frame_node_id=frame_node_id,
            image_node_id=image_node_id,
            label_node_id=label_node_id,
            meta_node_id=meta_node_id,
        )
        node_mapping[str(beat_num)] = {
            "frame_node_id": frame_node_id,
            "image_node_id": image_node_id,
            "label_node_id": label_node_id,
            "meta_node_id": meta_node_id,
        }

    # Build a summary message
    parts = [f"Patched {len(node_mapping)} beat(s) in Figma file."]
    if overflow_beats:
        parts.append(
            f"{len(overflow_beats)} beat(s) exceeded template capacity "
            f"(Beat {overflow_beats}) — add more panels to the template."
        )
    if errors:
        parts.append(f"{len(errors)} error(s) encountered.")

    return {
        "storyboard_id": storyboard_id,
        "figmaUrl": f"https://www.figma.com/file/{file_key}",
        "fileName": file_name,
        "file_key": file_key,
        "framesCreated": len(node_mapping),
        "nodeMapping": node_mapping,
        "exportMode": "direct_patch",
        "templateSlots": template_slots,
        "usedSlots": len(node_mapping),
        "overflowBeats": overflow_beats,
        "errors": errors,
        "message": " ".join(parts),
    }


async def _build_template_patch_payload(
    beats: List[Dict[str, Any]],
    storyboard_id: str,
    file_name: str,
    file_key: str,
) -> Dict[str, Any]:
    """
    Build a plugin payload that patches an existing Figma template instead of
    creating new frames from scratch.

    Fetches the template's node tree, maps each beat to its panel's existing
    node IDs (image container, label, meta), and returns a 'patches' list the
    plugin can apply via figma.getNodeById().
    """
    async with httpx.AsyncClient() as client:
        doc = await _fetch_file_nodes(client, file_key)

    pages = doc.get("document", {}).get("children", [])
    if not pages:
        raise RuntimeError("Figma template file has no pages")

    target_page = next(
        (p for p in pages if p.get("name") == "Storyboard"),
        pages[0],
    )
    page_id   = target_page["id"]
    page_name = target_page["name"]

    panels = _collect_template_panels(target_page)

    used_slots: set = set()
    patches = []
    for beat in beats:
        beat_num  = beat.get("beat_number", 1)
        slot_idx  = beat_num - 1
        image_url = beat.get("imageUrl") or beat.get("image_url") or ""
        if image_url and not image_url.startswith("http"):
            image_url = BACKEND_BASE_URL + image_url

        narrator  = beat.get("narrator_line", "")
        camera    = beat.get("camera_angle", "")
        lighting  = beat.get("lighting", "")
        meta_text = f"{camera}  ·  {lighting}" if (camera or lighting) else ""

        if slot_idx < 0 or slot_idx >= len(panels):
            logger.warning("Beat %d has no template slot (template has %d panel(s))", beat_num, len(panels))
            continue

        used_slots.add(slot_idx)
        panel      = panels[slot_idx]
        img_node   = _find_image_container(panel)
        label_node = _find_node_by_name(panel, "label")
        meta_node  = _find_node_by_name(panel, "meta")

        # The upload placeholder ('Label') sits inside the image container and
        # must be hidden once a real image fill is applied.
        placeholder_node = _find_upload_placeholder(img_node) if img_node else None

        # label/meta may be FRAME wrappers — find the inner TEXT node for editing.
        label_text_node = _find_text_node_in_wrapper(label_node) if label_node else None
        meta_text_node  = _find_text_node_in_wrapper(meta_node)  if meta_node  else None

        patches.append({
            "beat_number":         beat_num,
            "frame_node_id":       panel["id"],
            "image_node_id":       img_node["id"]          if img_node          else "",
            "placeholder_node_id": placeholder_node["id"]  if placeholder_node  else "",
            "label_node_id":       (label_text_node["id"]  if label_text_node
                                    else label_node["id"]   if label_node else ""),
            "meta_node_id":        (meta_text_node["id"]   if meta_text_node
                                    else meta_node["id"]    if meta_node  else ""),
            "imageUrl":            image_url,
            "label":               narrator,
            "meta":                meta_text,
        })

    # Build list of unused panel slots so the plugin can fill them with a
    # background colour and hide the upload placeholder.
    unused_panels = []
    for idx, panel in enumerate(panels):
        if idx in used_slots:
            continue
        img_node         = _find_image_container(panel)
        placeholder_node = _find_upload_placeholder(img_node) if img_node else None
        label_node       = _find_node_by_name(panel, "label")
        meta_node        = _find_node_by_name(panel, "meta")
        label_text_node  = _find_text_node_in_wrapper(label_node) if label_node else None
        meta_text_node   = _find_text_node_in_wrapper(meta_node)  if meta_node  else None
        unused_panels.append({
            # beat_number lets the plugin find the frame by name ("Beat N")
            # even when the template has been copied to a different file.
            "beat_number":         idx + 1,
            "frame_node_id":       panel["id"],
            "image_node_id":       img_node["id"]          if img_node          else "",
            "placeholder_node_id": placeholder_node["id"]  if placeholder_node  else "",
            "label_node_id":       (label_text_node["id"]  if label_text_node
                                    else label_node["id"]   if label_node else ""),
            "meta_node_id":        (meta_text_node["id"]   if meta_text_node
                                    else meta_node["id"]    if meta_node  else ""),
        })

    plugin_payload = {
        "storyboard_id": storyboard_id,
        "file_name":     file_name,
        "page_name":     page_name,
        "mode":          "patch_template",
        "patches":       patches,
        "unused_panels": unused_panels,
    }

    upsert_storyboard(
        storyboard_id,
        file_key=file_key,
        file_url=f"https://www.figma.com/file/{file_key}",
        file_name=file_name,
        page_id=page_id,
        page_name=page_name,
    )
    set_plugin_payload(storyboard_id, plugin_payload)

    return {
        "storyboard_id": storyboard_id,
        "figmaUrl":      f"https://www.figma.com/file/{file_key}",
        "fileName":      file_name,
        "file_key":      file_key,
        "framesCreated": len(patches),
        "nodeMapping":   {},
        "exportMode":    "plugin_patch_template",
        "pluginPayload": plugin_payload,
        "message": (
            f"Template patch payload ready — {len(patches)} beat(s) mapped to your "
            "Figma template. Open the PLAYWRIGHT plugin to apply."
        ),
    }


def _build_plugin_payload(
    beats: List[Dict[str, Any]],
    storyboard_id: str,
    file_name: str,
) -> Dict[str, Any]:
    """
    Build a plugin payload that creates new frames from scratch (no template).
    Used when FIGMA_TEMPLATE_FILE_KEY is not set.
    """
    frames = [_build_beat_frame(beat, idx) for idx, beat in enumerate(beats)]

    plugin_payload = {
        "storyboard_id": storyboard_id,
        "file_name":     file_name,
        "page_name":     "Storyboard",
        "mode":          "create_frames",    # tells the plugin to create new frames
        "canvas_width":  CANVAS_PAD * 2 + GRID_COLS * FRAME_W + (GRID_COLS - 1) * GRID_GAP_X,
        "frames":        frames,
    }

    upsert_storyboard(
        storyboard_id,
        file_key="",
        file_url="",
        file_name=file_name,
        page_id="",
        page_name="Storyboard",
    )
    set_plugin_payload(storyboard_id, plugin_payload)

    return {
        "storyboard_id": storyboard_id,
        "figmaUrl":      "https://www.figma.com/files/recent",
        "fileName":      file_name,
        "file_key":      "",
        "framesCreated": len(frames),
        "nodeMapping":   {},
        "exportMode":    "plugin_payload",
        "pluginPayload": plugin_payload,
        "message": (
            "Plugin payload ready. Open the PLAYWRIGHT Figma plugin and paste the "
            "storyboard_id to import this storyboard into your file."
        ),
    }


async def update_beat_in_figma(
    storyboard_id: str,
    beat_number: int,
    beat: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Selectively update a single beat's image (and optionally text) in Figma.

    Looks up the node IDs from the persistent store, uploads the new image,
    and patches only the affected nodes — leaving all other beats untouched.

    Parameters
    ----------
    storyboard_id : the storyboard to update
    beat_number   : which beat to regenerate
    beat          : updated beat dict (must include imageUrl / image_url)

    Returns
    -------
    { storyboard_id, beat_number, updated_nodes, message }
    """
    mapping = get_storyboard(storyboard_id)
    if not mapping:
        raise ValueError(
            f"No Figma mapping found for storyboard '{storyboard_id}'. "
            "Run a full export first."
        )

    file_key = mapping.get("file_key", "")
    if not file_key:
        raise ValueError(
            f"Storyboard '{storyboard_id}' was exported as a plugin payload "
            "(no file_key). Re-export with a target_file_key to enable direct patching."
        )

    nodes = get_beat_nodes(storyboard_id, beat_number)
    if not nodes:
        raise ValueError(
            f"No node mapping found for beat {beat_number} in storyboard '{storyboard_id}'."
        )

    image_url = beat.get("imageUrl") or beat.get("image_url") or ""
    updated_nodes: List[str] = []
    errors: List[str] = []

    async with httpx.AsyncClient() as client:
        try:
            await _verify_token(client)
        except Exception as exc:
            logger.warning(
                "Token verification via /me failed (%s). "
                "Proceeding — token may lack current_user:read scope.",
                exc,
            )

        if image_url and nodes.get("image_node_id"):
            try:
                img_bytes, content_type = await _resolve_image(client, image_url)
                image_ref = await _upload_image(client, file_key, img_bytes, content_type)
                await _patch_node(
                    client,
                    file_key,
                    nodes["image_node_id"],
                    {
                        "fills": [
                            {
                                "type": "IMAGE",
                                "scaleMode": "FILL",
                                "imageRef": image_ref,
                            }
                        ]
                    },
                )
                updated_nodes.append("image_fill")
            except Exception as exc:
                logger.error("Beat %s image update failed: %s", beat_number, exc)
                errors.append(f"image_fill: {exc}")

        if nodes.get("label_node_id") and beat.get("narrator_line"):
            try:
                await _patch_node(
                    client,
                    file_key,
                    nodes["label_node_id"],
                    {"characters": beat["narrator_line"]},
                )
                updated_nodes.append("label")
            except Exception as exc:
                logger.warning("Beat %s label update failed: %s", beat_number, exc)
                errors.append(f"label: {exc}")

        if nodes.get("meta_node_id"):
            meta_text = (
                f"{beat.get('camera_angle', '')} · {beat.get('lighting', '')}"
            )
            try:
                await _patch_node(
                    client,
                    file_key,
                    nodes["meta_node_id"],
                    {"characters": meta_text},
                )
                updated_nodes.append("meta")
            except Exception as exc:
                logger.warning("Beat %s meta update failed: %s", beat_number, exc)
                errors.append(f"meta: {exc}")

    upsert_beat_nodes(
        storyboard_id,
        beat_number,
        frame_node_id=nodes["frame_node_id"],
        image_node_id=nodes.get("image_node_id", ""),
        label_node_id=nodes.get("label_node_id", ""),
        meta_node_id=nodes.get("meta_node_id", ""),
    )

    return {
        "storyboard_id": storyboard_id,
        "beat_number": beat_number,
        "file_key": file_key,
        "figmaUrl": f"https://www.figma.com/file/{file_key}",
        "updated_nodes": updated_nodes,
        "errors": errors,
        "message": (
            f"Beat {beat_number} updated: {', '.join(updated_nodes) or 'nothing changed'}."
            + (f" {len(errors)} error(s)." if errors else "")
        ),
    }


async def register_plugin_mapping(
    storyboard_id: str,
    file_key: str,
    file_url: str,
    page_id: str,
    page_name: str,
    beat_nodes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Called by the Figma plugin after it has created the file client-side.
    Registers the file_key and per-beat node IDs so future selective updates work.

    beat_nodes schema:
        [{ beat_number, frame_node_id, image_node_id, label_node_id, meta_node_id }, ...]
    """
    mapping = get_storyboard(storyboard_id)
    if not mapping:
        raise ValueError(f"Storyboard '{storyboard_id}' not found in node store")

    upsert_storyboard(
        storyboard_id,
        file_key=file_key,
        file_url=file_url,
        file_name=mapping.get("file_name", ""),
        page_id=page_id,
        page_name=page_name,
    )

    for bn in beat_nodes:
        upsert_beat_nodes(
            storyboard_id,
            bn["beat_number"],
            frame_node_id=bn["frame_node_id"],
            image_node_id=bn.get("image_node_id", ""),
            label_node_id=bn.get("label_node_id", ""),
            meta_node_id=bn.get("meta_node_id", ""),
        )

    return {
        "storyboard_id": storyboard_id,
        "file_key": file_key,
        "beats_registered": len(beat_nodes),
        "message": "Node mapping registered successfully.",
    }


def get_node_mapping(storyboard_id: str) -> Dict[str, Any]:
    """Return the full node mapping for a storyboard."""
    mapping = get_storyboard(storyboard_id)
    if not mapping:
        raise ValueError(f"No mapping found for storyboard '{storyboard_id}'")
    return mapping


def get_plugin_payload(storyboard_id: str) -> Dict[str, Any]:
    """
    Return the plugin payload for a storyboard so the Figma plugin can fetch
    it via GET /api/export-figma/{storyboard_id}/payload.

    The payload is stored inside the node-map entry under the key
    'plugin_payload'. It is written there by _build_plugin_payload() at
    export time. If the entry exists but the payload was never stored
    (e.g. it was a direct-patch export), raise a clear error.
    """
    mapping = get_storyboard(storyboard_id)
    if not mapping:
        raise ValueError(f"No mapping found for storyboard '{storyboard_id}'")
    payload = mapping.get("plugin_payload")
    if not payload:
        raise ValueError(
            f"Storyboard '{storyboard_id}' has no plugin payload stored. "
            "It may have been exported in direct-patch mode. "
            "Re-export without a target_file_key to generate a plugin payload."
        )
    return payload


def get_all_mappings() -> Dict[str, Any]:
    """Return a summary of all tracked storyboards."""
    return list_storyboards()


def remove_storyboard_mapping(storyboard_id: str) -> bool:
    """Delete the mapping for a storyboard. Returns True if it existed."""
    return delete_storyboard(storyboard_id)
