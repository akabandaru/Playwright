# PLAYWRIGHT

**Transforms screenplays into visual storyboards and videos in minutes, not days.**

Writers and filmmakers paste their script, and our AI instantly breaks it down into cinematic beats — complete with generated visuals, voiceover narration, sound design, and a rendered video. Review each beat, reimagine scenes with natural language feedback, and export to Figma or video with one click.

---

## Setup

### 1. Environment Variables

Create `backend/.env` with your API keys:

```
GEMINI_API_KEY=your_gemini_api_key
ELEVENLABS_API_KEY=your_elevenlabs_api_key
FIGMA_ACCESS_TOKEN=your_figma_access_token

DATABRICKS_HOST=your_databricks_host
DATABRICKS_TOKEN=your_databricks_token
DATABRICKS_HTTP_PATH=your_http_path
DATABRICKS_MLFLOW_EXPERIMENT_NAME=/playwright-runs

IMAGE_PROVIDER_URL=your_cloudflare_tunnel_url
IMAGE_PROVIDER_GENERATE_TIMEOUT_SECONDS=300
IMAGE_PROVIDER_HEALTH_TIMEOUT_SECONDS=20
```

### 2. Backend

Requires **Python 3.12**.

```bash
cd backend

# Create and activate virtual environment
python3.12 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt

# Start the server
uvicorn main:app --reload
```

API available at `http://localhost:8000` | Docs at `http://localhost:8000/docs`

### 3. Frontend

Requires **Node.js 18+**.

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

Frontend available at `http://localhost:5173`

---

## Tools & Technologies

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Frontend** | React 19 | UI framework |
| | Vite 7 | Build tool and dev server |
| | Tailwind CSS 4 | Styling |
| | Framer Motion | Animations and transitions |
| **Backend** | FastAPI | API framework with SSE streaming |
| | Uvicorn | ASGI server |
| | Pydantic | Request/response validation |
| **AI / Generation** | Google Gemini 2.5 Flash | Script decomposition and beat reimagining |
| | Stable Diffusion (via Cloudflare tunnel) | Image generation from beat descriptions |
| | ElevenLabs | Voice narration, sound effects, and music |
| **Video** | MoviePy + FFmpeg | Video rendering from images and audio |
| **Observability** | Databricks + MLflow | Experiment tracking and inference logging |
| **Design** | Figma Plugin API | Storyboard export to Figma |
