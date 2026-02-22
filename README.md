# **Note:** `main2` is our main file.

# Playwright

A modern full-stack application with React (Vite) frontend and FastAPI backend.

## Project Structure

```
├── backend/
│   ├── main.py              # FastAPI application
│   └── requirements.txt     # Python dependencies
├── frontend/
│   ├── src/
│   │   ├── App.jsx          # Main React component
│   │   └── App.css          # Styles
│   └── package.json         # Node dependencies
├── .env                     # Environment variables
└── README.md
```

## Prerequisites

- Python 3.10+
- Node.js 18+
- npm or yarn

## Setup

### 1. Environment Variables

Copy the `.env` file and fill in your API keys:

```
GEMINI_API_KEY=your_gemini_api_key
ELEVENLABS_API_KEY=your_elevenlabs_key
FIGMA_ACCESS_TOKEN=your_figma_token
DATABRICKS_HOST=your_databricks_host
DATABRICKS_TOKEN=your_databricks_token
DATABRICKS_MLFLOW_EXPERIMENT_ID=your_experiment_id

# External image provider Cloudflare tunnel URL
IMAGE_PROVIDER_URL=https://attraction-local-inspector-shoot.trycloudflare.com

# Optional provider timeouts
IMAGE_PROVIDER_GENERATE_TIMEOUT_SECONDS=300
IMAGE_PROVIDER_HEALTH_TIMEOUT_SECONDS=20
```

### 2. Backend Setup

```bash
cd backend

# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`

API Documentation: `http://localhost:8000/docs`

### 3. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Run development server
npm run dev
```

The frontend will be available at `http://localhost:5173`

## Development

### Backend

- FastAPI with automatic OpenAPI documentation
- CORS configured for frontend communication
- Environment variables loaded via python-dotenv

### Frontend

- React 18 with Vite for fast development
- Modern UI with gradient styling
- Backend health check integration

## Available Scripts

### Backend

```bash
uvicorn main:app --reload          # Development server with hot reload
uvicorn main:app --host 0.0.0.0    # Production server
```

### Frontend

```bash
npm run dev      # Start development server
npm run build    # Build for production
npm run preview  # Preview production build
```

## API Endpoints

| Method | Endpoint | Description       |
| ------ | -------- | ----------------- |
| GET    | /        | Welcome message   |
| GET    | /health  | Health check      |
| GET    | /docs    | API documentation |

## External Image Provider Integration

- `POST /api/generate-frame`: Generates one image from one beat (saves PNG to backend outputs and returns metadata + file URL).
- `POST /api/generate-images`: Batch generate images for beats.
- `GET /api/image-provider-health`: Checks upstream provider health (`/health` pass-through).

### Sample Local Test (`/api/generate-frame`)

```bash
curl -X POST http://127.0.0.1:8000/api/generate-frame \
	-H "Content-Type: application/json" \
	-d '{
		"beat_number": 1,
		"visual_description": "Massive flames recede to reveal a dark bat symbol.",
		"camera_angle": "wide shot",
		"mood": "ominous",
		"lighting": "firelight",
		"characters_present": [],
		"narrator_line": "Some symbols are born in fire.",
		"music_style": "dark, percussive, building crescendo",
		"width": 832,
		"height": 464,
		"steps": 8,
		"guidance_scale": 3.0,
		"return_base64": false,
		"save_to_disk": true
	}'
```
