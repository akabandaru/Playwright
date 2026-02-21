# Local SDXL Setup (No API Server, Windows)

This setup runs Stable Diffusion directly inside your backend process (no AUTOMATIC1111 server, no `/sdapi` calls).

## 1) Prerequisites

PowerShell:

```powershell
python --version
nvidia-smi
```

If `nvidia-smi` works and shows your RTX 4060, CUDA is visible.

## 2) Create and use conda environment

```powershell
conda create -n playwright-sd python=3.10 -y
conda activate playwright-sd
```

## 3) Install backend deps

```powershell
cd C:\Users\arnav\Documents\Projects\Hacklytics2026\Playwright\backend
pip install -r requirements.txt
```

Install CUDA-enabled PyTorch (recommended for GPU inference):

```powershell
pip install --index-url https://download.pytorch.org/whl/cu121 torch torchvision
```

Verify environment and CUDA:

```powershell
python -c "import sys, torch; print(sys.executable); print(torch.__version__); print(torch.cuda.is_available())"
```

## 4) Choose your model source

Set model reference with env var `SD_MODEL_PATH`.

### Option A: Hugging Face model ID

```powershell
$env:SD_MODEL_PATH="stabilityai/stable-diffusion-xl-base-1.0"
```

### Option B: Local checkpoint file (`.safetensors` / `.ckpt`)

```powershell
$env:SD_MODEL_PATH="D:\models\sdxl\your_model.safetensors"
```

## 5) Run backend

```powershell
cd C:\Users\arnav\Documents\Projects\Hacklytics2026\Playwright\backend
uvicorn main:app --reload
```

Your existing endpoint remains:
- `POST http://127.0.0.1:8000/api/generate-images`

## 6) Minimal direct test

Run this script:

```powershell
cd C:\Users\arnav\Documents\Projects\Hacklytics2026\Playwright\backend
python .\scripts\test_local_diffusers_txt2img.py
```

Expected output:
- saves `backend\scripts\frame.png`

## 7) Shot helper

Included shot types in test + service:
- `ECU`: extreme close-up, 85mm lens
- `CU`: close-up portrait, head and shoulders
- `MS`: medium shot, waist-up
- `FS`: full body shot
- `LS`: wide establishing shot, subject small in frame

## 8) Troubleshooting

### Wrong Python environment
- Ensure VS Code terminal and backend both use the same interpreter.
- Re-run: `python --version` and `pip -V`.
- VS Code workspace is pinned to:
  - `C:/Users/arnav/anaconda3/envs/playwright-sd/python.exe`

### Model not found
- If using local path, verify file exists and extension is `.safetensors` or `.ckpt`.
- If using HF ID, verify internet access and permissions.

### GPU not used (CPU fallback)
- Check: `python -c "import torch; print(torch.cuda.is_available())"`
- Should print `True`.
- While generating, `nvidia-smi` should show Python VRAM usage.

### Out of memory
- Reduce generation settings in env vars or service defaults:
  - `SD_WIDTH=832`
  - `SD_HEIGHT=468`
  - `SD_STEPS=16`
