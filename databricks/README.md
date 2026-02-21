# PLAYWRIGHT - Databricks ML Pipeline

Train a custom script segmentation model using Cornell Movie Dialogs and IMSDB datasets.

## Overview

This pipeline trains a transformer-based model to segment screenplays into visual "beats" - discrete moments that can be turned into storyboard frames. Each beat includes:

- **Visual description** - What's visible in the frame
- **Camera angle** - Suggested shot type
- **Mood** - Emotional tone
- **Lighting** - Lighting style
- **Characters** - Who's in the scene
- **Narrator line** - Voiceover text

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Script Segmentation Model                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐                                               │
│  │  DistilBERT  │  ← Pretrained encoder                        │
│  │   Encoder    │                                               │
│  └──────┬───────┘                                               │
│         │                                                        │
│         ▼                                                        │
│  ┌──────────────────────────────────────────────────────┐       │
│  │              Multi-Task Heads                         │       │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐     │       │
│  │  │   Beat     │  │   Mood     │  │  Camera    │     │       │
│  │  │ Boundary   │  │ Classifier │  │ Classifier │     │       │
│  │  │ (BIO Tag)  │  │            │  │            │     │       │
│  │  └────────────┘  └────────────┘  └────────────┘     │       │
│  └──────────────────────────────────────────────────────┘       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Datasets

### Cornell Movie Dialogs Corpus
- **Source**: http://www.cs.cornell.edu/~cristian/Cornell_Movie-Dialogs_Corpus.html
- **Size**: 220,579 conversational exchanges from 617 movies
- **Use**: Dialogue patterns, character interactions

### IMSDB (Internet Movie Script Database)
- **Source**: https://imsdb.com
- **Size**: 1,000+ full movie scripts
- **Use**: Scene structure, action descriptions, formatting

## Notebooks

Run these in order on Databricks:

### 1. `01_data_ingestion.py`
Downloads and ingests raw data into Delta tables:
- `playwright.cornell_lines` - Individual dialogue lines
- `playwright.cornell_movies` - Movie metadata  
- `playwright.imsdb_scripts` - Full screenplays

### 2. `02_data_preprocessing.py`
Processes scripts into training data:
- Parses screenplay format (INT./EXT., characters, dialogue)
- Segments scenes into beats using rule-based heuristics
- Creates BIO-tagged sequences for training
- Outputs: `playwright.training_beats`, `playwright.sequence_labels`

### 3. `03_model_training.py`
Trains the segmentation model:
- Multi-task DistilBERT architecture
- Beat boundary detection (BIO tagging)
- Mood classification (9 classes)
- Camera angle prediction (8 classes)
- MLflow experiment tracking
- Model registered to Unity Catalog

### 4. `04_model_serving.py`
Deploys model for inference:
- Creates inference wrapper class
- Deploys to Databricks Model Serving
- Creates REST endpoint

## Setup

### 1. Create Databricks Workspace

```bash
# Set environment variables
export DATABRICKS_HOST="your-workspace.cloud.databricks.com"
export DATABRICKS_TOKEN="your-token"
```

### 2. Create Database

```sql
CREATE DATABASE IF NOT EXISTS playwright;
```

### 3. Create Secrets Scope

```bash
databricks secrets create-scope --scope playwright
databricks secrets put --scope playwright --key databricks_host
databricks secrets put --scope playwright --key databricks_token
```

### 4. Run Notebooks

Import notebooks to your workspace and run in sequence.

## Model Serving Endpoint

Once deployed, the model is available at:

```
POST https://<databricks-host>/serving-endpoints/playwright-segmentation/invocations
```

### Request Format

```json
{
  "inputs": [{
    "script": "INT. COFFEE SHOP - DAY\n\nJOHN sits alone at a table..."
  }]
}
```

### Response Format

```json
{
  "predictions": [{
    "beats": [
      {
        "beat_number": 1,
        "visual_description": "Coffee shop interior, morning light...",
        "camera_angle": "wide shot",
        "mood": "serene",
        "lighting": "natural daylight",
        "characters_present": ["JOHN"],
        "narrator_line": "The morning sun filters through...",
        "music_recommendation": "soft piano with ambient textures"
      }
    ]
  }]
}
```

## Integration with Backend

The FastAPI backend automatically uses the Databricks model when available:

```python
# backend/services/segmentation_service.py

async def segment_script(script: str, use_databricks: bool = True):
    if use_databricks:
        beats = await segment_with_databricks(script)
        if beats:
            return beats
    
    # Fallback to Gemini
    from services.gemini_service import analyze_script
    return await analyze_script(script)
```

Set these environment variables to enable:

```bash
DATABRICKS_HOST=your-workspace.cloud.databricks.com
DATABRICKS_TOKEN=your-token
```

## Training Metrics

Expected metrics after training:

| Metric | Value |
|--------|-------|
| Beat Boundary F1 | ~0.85 |
| Mood Accuracy | ~0.75 |
| Camera Accuracy | ~0.70 |
| Inference Latency | <100ms |

## Cost Optimization

- Model uses DistilBERT (66M params) vs BERT (110M params)
- Scale-to-zero enabled on serving endpoint
- Batch inference for multiple scripts

## Monitoring

MLflow tracks:
- Training loss curves
- Validation metrics per epoch
- Model artifacts and versions
- Inference latency in production

View experiments at:
```
https://<databricks-host>/#mlflow/experiments/<experiment-id>
```
