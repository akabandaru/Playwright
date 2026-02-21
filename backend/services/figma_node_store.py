"""
Figma Node Mapping Store

Persists the relationship between storyboard beats and their Figma node IDs.
Backed by a JSON file so mappings survive server restarts.

Schema:
    {
        "<storyboard_id>": {
            "file_key": "abc123",
            "file_url": "https://www.figma.com/file/abc123/...",
            "file_name": "PLAYWRIGHT — 2026-02-21 14:30",
            "page_id": "0:1",
            "page_name": "Storyboard",
            "created_at": "2026-02-21T14:30:00",
            "updated_at": "2026-02-21T14:30:00",
            "beats": {
                "<beat_number>": {
                    "frame_node_id": "1:2",
                    "image_node_id": "1:3",
                    "label_node_id": "1:4",
                    "meta_node_id": "1:5",
                    "beat_number": 1,
                    "last_synced_at": "2026-02-21T14:30:00"
                }
            }
        }
    }
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)

_STORE_PATH = Path(__file__).parent.parent / "data" / "figma_node_map.json"
_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)

_store: Dict[str, Any] = {}


def _load() -> None:
    """Load the mapping from disk into memory."""
    global _store
    if _STORE_PATH.exists():
        try:
            with open(_STORE_PATH, "r", encoding="utf-8") as f:
                _store = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load figma_node_map.json: %s — starting fresh", exc)
            _store = {}
    else:
        _store = {}


def _save() -> None:
    """Persist the in-memory mapping to disk."""
    try:
        with open(_STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(_store, f, indent=2, ensure_ascii=False)
    except OSError as exc:
        logger.error("Could not persist figma_node_map.json: %s", exc)


_load()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def upsert_storyboard(
    storyboard_id: str,
    *,
    file_key: str,
    file_url: str,
    file_name: str,
    page_id: str,
    page_name: str,
) -> None:
    """Create or update the top-level storyboard entry."""
    existing = _store.get(storyboard_id, {})
    _store[storyboard_id] = {
        **existing,
        "file_key": file_key,
        "file_url": file_url,
        "file_name": file_name,
        "page_id": page_id,
        "page_name": page_name,
        "created_at": existing.get("created_at", _now()),
        "updated_at": _now(),
        "beats": existing.get("beats", {}),
    }
    _save()


def upsert_beat_nodes(
    storyboard_id: str,
    beat_number: int,
    *,
    frame_node_id: str,
    image_node_id: str,
    label_node_id: str,
    meta_node_id: str,
) -> None:
    """Record or update the Figma node IDs for a single beat."""
    if storyboard_id not in _store:
        raise KeyError(f"Storyboard '{storyboard_id}' not found in node store")
    _store[storyboard_id]["beats"][str(beat_number)] = {
        "frame_node_id": frame_node_id,
        "image_node_id": image_node_id,
        "label_node_id": label_node_id,
        "meta_node_id": meta_node_id,
        "beat_number": beat_number,
        "last_synced_at": _now(),
    }
    _store[storyboard_id]["updated_at"] = _now()
    _save()


def get_storyboard(storyboard_id: str) -> Optional[Dict[str, Any]]:
    """Return the full mapping for a storyboard, or None if not found."""
    return _store.get(storyboard_id)


def get_beat_nodes(storyboard_id: str, beat_number: int) -> Optional[Dict[str, Any]]:
    """Return the node IDs for a specific beat, or None if not found."""
    entry = _store.get(storyboard_id)
    if not entry:
        return None
    return entry.get("beats", {}).get(str(beat_number))


def list_storyboards() -> Dict[str, Any]:
    """Return a summary of all tracked storyboards."""
    return {
        sid: {
            "file_key": v["file_key"],
            "file_url": v["file_url"],
            "file_name": v["file_name"],
            "beat_count": len(v.get("beats", {})),
            "created_at": v["created_at"],
            "updated_at": v["updated_at"],
        }
        for sid, v in _store.items()
    }


def delete_storyboard(storyboard_id: str) -> bool:
    """Remove a storyboard mapping. Returns True if it existed."""
    if storyboard_id in _store:
        del _store[storyboard_id]
        _save()
        return True
    return False


def set_plugin_payload(storyboard_id: str, payload: Dict[str, Any]) -> None:
    """Store the plugin payload blob on an existing storyboard entry."""
    if storyboard_id not in _store:
        raise KeyError(f"Storyboard '{storyboard_id}' not found in node store")
    _store[storyboard_id]["plugin_payload"] = payload
    _save()
