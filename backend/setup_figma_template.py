"""
PLAYWRIGHT — Figma Template Setup
===================================
Interactive script that:
  1. Walks you through creating the PLAYWRIGHT template file in Figma (2 minutes)
  2. Verifies the file key you paste is reachable with your token
  3. Reads the file and checks how many "Beat N" frames exist
  4. Writes FIGMA_TEMPLATE_FILE_KEY to your .env automatically

Run:
    cd backend
    source venv/bin/activate
    python setup_figma_template.py
"""

import asyncio
import os
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv, set_key
load_dotenv(BACKEND_DIR / ".env")

import httpx

ENV_PATH = BACKEND_DIR / ".env"
FIGMA_API_URL = "https://api.figma.com/v1"
MAX_BEATS = 12  # recommended template size


def _token() -> str:
    t = os.getenv("FIGMA_ACCESS_TOKEN", "")
    if not t:
        print("\nERROR: FIGMA_ACCESS_TOKEN is not set in .env")
        sys.exit(1)
    return t


def _headers():
    return {"X-Figma-Token": _token()}


def _hr(char="─", width=60):
    print(char * width)


def _section(title):
    print()
    _hr()
    print(f"  {title}")
    _hr()


def _extract_file_key(url_or_key: str) -> str:
    """Accept either a raw key or a full Figma URL and return the key."""
    url_or_key = url_or_key.strip()
    # Match https://www.figma.com/file/<key>/... or /design/<key>/...
    m = re.search(r"figma\.com/(?:file|design)/([A-Za-z0-9_-]+)", url_or_key)
    if m:
        return m.group(1)
    # Looks like a bare key (alphanumeric + dashes)
    if re.match(r"^[A-Za-z0-9_-]+$", url_or_key):
        return url_or_key
    return ""


async def verify_and_inspect(file_key: str) -> dict:
    """Fetch the file and return info about its Beat frames."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{FIGMA_API_URL}/files/{file_key}",
            headers=_headers(),
            params={"depth": "3"},
            timeout=30.0,
        )
        if resp.status_code == 403:
            data = resp.json()
            err = data.get("err", "")
            if "scope" in err.lower():
                return {
                    "ok": False,
                    "error": (
                        f"Token scope error: {err}\n"
                        "  Your token needs the 'file_content:read' scope.\n"
                        "  Go to figma.com → Settings → Security → Personal access tokens\n"
                        "  and regenerate with 'file_content:read' checked."
                    ),
                }
            return {"ok": False, "error": f"403 Forbidden — {err or 'check your token'}"}
        if resp.status_code == 404:
            return {"ok": False, "error": "File not found. Double-check the file key/URL."}
        if not resp.is_success:
            return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}

        data = resp.json()
        file_name = data.get("name", "")
        pages = data.get("document", {}).get("children", [])

        # Find the Storyboard page (or fall back to first page)
        target_page = next(
            (p for p in pages if p.get("name") == "Storyboard"),
            pages[0] if pages else {},
        )
        page_name = target_page.get("name", "")

        beat_frames = []
        for child in target_page.get("children", []):
            name = child.get("name", "")
            if name.startswith("Beat "):
                try:
                    n = int(name.split(" ")[1])
                    beat_frames.append(n)
                except (IndexError, ValueError):
                    pass

        beat_frames.sort()

        # Check child node names inside each Beat frame
        child_names_sample = {}
        for child in target_page.get("children", []):
            name = child.get("name", "")
            if name.startswith("Beat ") and len(child_names_sample) < 2:
                children = [c.get("name") for c in child.get("children", [])]
                child_names_sample[name] = children

        return {
            "ok": True,
            "file_name": file_name,
            "page_name": page_name,
            "beat_frames": beat_frames,
            "child_names_sample": child_names_sample,
        }


def _print_instructions():
    _section("HOW TO CREATE THE PLAYWRIGHT TEMPLATE FILE")
    print("""
  You need a Figma file with frames named "Beat 1", "Beat 2", … "Beat 12".
  Each frame should have three child layers:

    ┌─────────────────────────────────────────┐
    │  Frame: "Beat 1"  (1280 × 720)          │
    │  ├─ Rectangle: "image_fill"  (1280×720) │  ← image goes here
    │  ├─ Text:      "label"                  │  ← narrator line
    │  └─ Text:      "meta"                   │  ← camera · lighting
    └─────────────────────────────────────────┘

  QUICK STEPS (takes ~2 minutes):
  ─────────────────────────────────────────────────────────────────────
  1. Open Figma desktop app (or figma.com)
  2. Create a new file  →  File > New design file
  3. Rename the page to "Storyboard"  (double-click the page tab)
  4. For each beat slot (1 to 12):
       a. Press F  →  draw a frame  →  set W=1280, H=720 in the right panel
       b. Name the frame "Beat 1"  (double-click the layer name)
       c. Inside the frame, draw a rectangle covering the full frame
          Name it "image_fill"
       d. Add a text layer near the bottom  →  name it "label"
       e. Add a text layer near the top-right  →  name it "meta"
       f. Repeat for Beat 2, Beat 3, … Beat 12
  5. Arrange the frames in a 3-column grid (optional but looks nice)
  6. Copy the file URL from your browser:
       https://www.figma.com/file/XXXXXXXXXXX/PLAYWRIGHT-Template
                                  ^^^^^^^^^^^
                                  This is your file key

  TIP: You can also duplicate an existing frame 12 times and rename each one.
  TIP: The child layer names (image_fill / label / meta) are case-sensitive.
  ─────────────────────────────────────────────────────────────────────
""")


async def main():
    print()
    print("═" * 60)
    print("  PLAYWRIGHT — Figma Template Setup")
    print("═" * 60)

    token = _token()
    print(f"\n  Token: {token[:12]}…{token[-4:]}")

    existing_key = os.getenv("FIGMA_TEMPLATE_FILE_KEY", "").strip()
    if existing_key:
        print(f"\n  Existing FIGMA_TEMPLATE_FILE_KEY: {existing_key}")
        ans = input("  Re-configure? [y/N] ").strip().lower()
        if ans != "y":
            print("\n  Verifying existing template…")
            info = await verify_and_inspect(existing_key)
            if info["ok"]:
                _print_verification(existing_key, info)
            else:
                print(f"\n  ERROR: {info['error']}")
            return

    _print_instructions()

    # ── Get the file key from the user ────────────────────────────────────────
    while True:
        raw = input("  Paste your Figma file URL or key: ").strip()
        if not raw:
            print("  (skipped)")
            return

        file_key = _extract_file_key(raw)
        if not file_key:
            print("  Could not parse a file key from that input. Try again.")
            continue

        print(f"\n  Parsed file key: {file_key}")
        print("  Verifying with Figma API…")
        info = await verify_and_inspect(file_key)

        if not info["ok"]:
            print(f"\n  ERROR: {info['error']}")
            retry = input("\n  Try a different key? [Y/n] ").strip().lower()
            if retry == "n":
                return
            continue

        _print_verification(file_key, info)

        # ── Warn if the template looks incomplete ─────────────────────────────
        beat_frames = info["beat_frames"]
        if not beat_frames:
            print(
                "\n  WARNING: No frames named 'Beat N' found on the "
                f"'{info['page_name']}' page."
            )
            print("  Make sure your frames are named exactly 'Beat 1', 'Beat 2', etc.")
            retry = input("\n  Try a different key? [Y/n] ").strip().lower()
            if retry != "n":
                continue

        if len(beat_frames) < 4:
            print(
                f"\n  WARNING: Only {len(beat_frames)} Beat frame(s) found. "
                f"Recommended minimum is 8, ideal is {MAX_BEATS}."
            )

        # Check for missing child layers
        sample = info.get("child_names_sample", {})
        for frame_name, children in sample.items():
            missing = [n for n in ("image_fill", "label", "meta") if n not in children]
            if missing:
                print(
                    f"\n  WARNING: {frame_name} is missing child layer(s): {missing}"
                )
                print("  Images/text won't be patched for frames with missing layers.")

        # ── Write to .env ─────────────────────────────────────────────────────
        print(f"\n  Writing FIGMA_TEMPLATE_FILE_KEY={file_key} to .env…")
        set_key(str(ENV_PATH), "FIGMA_TEMPLATE_FILE_KEY", file_key)
        print("  Done! ✓")
        print()
        print("  You can now run:")
        print("    python test_figma_export.py --skip-update")
        print("  and the storyboard will be patched directly into your Figma file.")
        print()
        break


def _print_verification(file_key: str, info: dict):
    _section("TEMPLATE VERIFICATION")
    print(f"  File name   : {info['file_name']}")
    print(f"  File key    : {file_key}")
    print(f"  Page name   : {info['page_name']}")
    beat_frames = info["beat_frames"]
    if beat_frames:
        print(f"  Beat frames : {len(beat_frames)} found  →  {beat_frames}")
    else:
        print("  Beat frames : NONE FOUND")

    sample = info.get("child_names_sample", {})
    if sample:
        print("  Child layers (sample):")
        for fname, children in sample.items():
            status = "✓" if set(children) >= {"image_fill", "label", "meta"} else "⚠"
            print(f"    {status}  {fname}: {children}")


if __name__ == "__main__":
    asyncio.run(main())
