# PLAYWRIGHT Storyboard — Figma Plugin

Creates a full storyboard in Figma from a PLAYWRIGHT export. Each beat becomes a 1280×720 frame with the generated image, narrator line, and camera/lighting metadata.

---

## How it works

```
Backend (Python)          Figma Plugin (this)
─────────────────         ──────────────────────────────────────
POST /api/export-figma    ← you call this first (via test script or frontend)
  → storyboard_id         → paste into plugin UI
  → plugin payload        ← plugin fetches via GET /api/export-figma/{id}/payload
  stored in DB

                          Plugin creates frames on canvas
                          POST /api/export-figma/{id}/mapping
                          ← registers node IDs back to backend

                          Future: PATCH /api/export-figma/{id}/beat/{n}
                          ← selective image update without re-exporting
```

---

## Install (one-time)

1. Open **Figma desktop app** (required — browser Figma doesn't support local plugins)
2. Go to **Plugins → Development → Import plugin from manifest…**
3. Select `figma-plugin/manifest.json` from this repo
4. The plugin now appears under **Plugins → Development → PLAYWRIGHT Storyboard**

---

## Usage

### Step 1 — Export from the backend

Run the test script (or trigger from the frontend):

```bash
cd backend
source venv/bin/activate
python test_figma_export.py
```

Copy the `storyboard_id` printed at the end, e.g.:
```
✓ storyboard_id = c45d1b0f-0aee-49b1-ab8b-a38f5b91f4d8
```

### Step 2 — Run the plugin in Figma

1. Open any Figma file (or create a blank one — the plugin will use the current page)
2. Run **Plugins → Development → PLAYWRIGHT Storyboard**
3. Confirm the **Backend URL** matches where your server is running (`http://localhost:8000`)
4. Paste the `storyboard_id` into the input field
5. Click **▶ Import Storyboard**

The plugin will:
- Fetch the beat layout + images from the backend
- Create a frame for each beat on the canvas (1280×720, 3-column grid)
- Fill each frame with the generated image, narrator text, and camera/lighting label
- Register all node IDs back to the backend so future selective updates work
- Zoom the canvas to fit all frames

### Step 3 — Selective beat update (after regenerating an image)

Once the plugin has run and node IDs are registered, you can update a single beat without re-running the full export:

```bash
# Re-generate beat 3's image, then call:
PATCH /api/export-figma/{storyboard_id}/beat/3
{ "beat": { "beat_number": 3, "imageUrl": "data:image/png;base64,..." } }
```

Only beat 3's nodes are patched in Figma — all other beats are untouched.

---

## Plugin file structure

```
figma-plugin/
├── manifest.json   — plugin metadata + network permissions
├── code.js         — plugin sandbox: creates Figma nodes
├── ui.html         — plugin UI: input, progress, log, result card
└── README.md       — this file
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Failed to fetch payload" | Make sure the backend is running (`uvicorn main:app --reload`) |
| "No mapping found" | Re-run `test_figma_export.py` to generate a fresh storyboard_id |
| Images show as dark placeholder | The image data URI in the payload may be empty — check that `imageUrl` is set on each beat before exporting |
| Plugin not visible | Make sure you imported the manifest in the **Figma desktop app**, not browser Figma |
| CORS error in plugin log | Add your backend URL to `networkAccess.allowedDomains` in `manifest.json` |
