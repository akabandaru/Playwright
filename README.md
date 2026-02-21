# Full Stack Application

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

- Python 3.10 (recommended for local SDXL)
- Conda (recommended)
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

# Local SD model source (Hugging Face ID or local .safetensors/.ckpt path)
SD_MODEL_PATH=stabilityai/stable-diffusion-xl-base-1.0
```

### 2. Backend Setup

```bash
cd backend

# Create conda environment (recommended)
conda create -n playwright-sd python=3.10 -y
conda activate playwright-sd

# Install dependencies
pip install -r requirements.txt

# Install CUDA-enabled torch for GPU inference
pip install --index-url https://download.pytorch.org/whl/cu121 torch torchvision

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

| Method | Endpoint  | Description        |
|--------|-----------|-------------------|
| GET    | /         | Welcome message   |
| GET    | /health   | Health check      |
| GET    | /docs     | API documentation |
