# Databricks notebook source
# MAGIC %md
# MAGIC # Script Segmentation Model - Serving
# MAGIC 
# MAGIC This notebook sets up model serving for the trained segmentation model:
# MAGIC 1. Create inference function
# MAGIC 2. Deploy to Databricks Model Serving
# MAGIC 3. Create REST API endpoint

# COMMAND ----------

# MAGIC %pip install transformers torch mlflow

# COMMAND ----------

import os
import json
import torch
import mlflow
from typing import List, Dict, Any
from transformers import DistilBertTokenizer
from pyspark.sql import SparkSession

spark = SparkSession.builder.getOrCreate()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Load Production Model

# COMMAND ----------

LABEL_TO_ID = {'O': 0, 'B-BEAT': 1, 'I-BEAT': 2}
ID_TO_LABEL = {v: k for k, v in LABEL_TO_ID.items()}

MOOD_TO_ID = {
    'neutral': 0, 'tense': 1, 'romantic': 2, 'action': 3,
    'mysterious': 4, 'comedic': 5, 'dramatic': 6, 'serene': 7, 'melancholic': 8
}
ID_TO_MOOD = {v: k for k, v in MOOD_TO_ID.items()}

CAMERA_TO_ID = {
    'medium shot': 0, 'close-up': 1, 'wide shot': 2, 'over-the-shoulder': 3,
    'pov shot': 4, 'tracking shot': 5, 'low angle': 6, 'high angle': 7
}
ID_TO_CAMERA = {v: k for k, v in CAMERA_TO_ID.items()}

LIGHTING_OPTIONS = [
    'natural daylight', 'golden hour', 'low-key dramatic', 'high-key bright',
    'neon noir', 'candlelit', 'moonlit', 'harsh shadows'
]

# COMMAND ----------

model_uri = "models:/playwright_segmentation/Production"
model = mlflow.pytorch.load_model(model_uri)
model.eval()

tokenizer = DistilBertTokenizer.from_pretrained('/dbfs/FileStore/playwright/final_model')

print("Model loaded successfully")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Inference Pipeline

# COMMAND ----------

class ScriptSegmenter:
    """Production inference class for script segmentation."""
    
    def __init__(self, model, tokenizer, device='cpu'):
        self.model = model.to(device)
        self.tokenizer = tokenizer
        self.device = device
        
    def segment_script(self, script: str) -> List[Dict[str, Any]]:
        """
        Segment a script into beats with metadata.
        
        Returns list of beats with:
        - beat_number
        - text
        - visual_description
        - camera_angle
        - mood
        - lighting
        - characters_present
        - narrator_line
        """
        paragraphs = self._split_into_paragraphs(script)
        
        all_beats = []
        current_beat_text = []
        beat_number = 1
        
        for para in paragraphs:
            prediction = self._predict_paragraph(para)
            
            if prediction['is_beat_start'] and current_beat_text:
                beat = self._create_beat(
                    beat_number,
                    '\n'.join(current_beat_text),
                    prediction
                )
                all_beats.append(beat)
                beat_number += 1
                current_beat_text = []
            
            current_beat_text.append(para)
        
        if current_beat_text:
            prediction = self._predict_paragraph('\n'.join(current_beat_text))
            beat = self._create_beat(
                beat_number,
                '\n'.join(current_beat_text),
                prediction
            )
            all_beats.append(beat)
        
        if all_beats and 'music_recommendation' not in all_beats[0]:
            all_beats[0]['music_recommendation'] = self._suggest_music(all_beats[0])
        
        return all_beats[:8]
    
    def _split_into_paragraphs(self, script: str) -> List[str]:
        """Split script into meaningful paragraphs."""
        lines = script.strip().split('\n')
        paragraphs = []
        current_para = []
        
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current_para:
                    paragraphs.append('\n'.join(current_para))
                    current_para = []
            else:
                current_para.append(line)
        
        if current_para:
            paragraphs.append('\n'.join(current_para))
        
        return paragraphs
    
    def _predict_paragraph(self, text: str) -> Dict[str, Any]:
        """Get model predictions for a paragraph."""
        inputs = self.tokenizer(
            text,
            return_tensors='pt',
            truncation=True,
            max_length=256,
            padding='max_length'
        ).to(self.device)
        
        with torch.no_grad():
            outputs = self.model(**inputs)
        
        beat_preds = torch.argmax(outputs['beat_logits'], dim=-1)
        mood_pred = torch.argmax(outputs['mood_logits'], dim=-1).item()
        camera_pred = torch.argmax(outputs['camera_logits'], dim=-1).item()
        
        is_beat_start = (beat_preds[0][1].item() == 1)
        
        return {
            'is_beat_start': is_beat_start,
            'mood': ID_TO_MOOD.get(mood_pred, 'neutral'),
            'camera_angle': ID_TO_CAMERA.get(camera_pred, 'medium shot'),
        }
    
    def _create_beat(
        self, 
        beat_number: int, 
        text: str, 
        prediction: Dict
    ) -> Dict[str, Any]:
        """Create a beat object with all required fields."""
        characters = self._extract_characters(text)
        visual_desc = self._generate_visual_description(text, characters)
        narrator_line = self._generate_narrator_line(text)
        lighting = self._suggest_lighting(prediction['mood'], text)
        
        return {
            'beat_number': beat_number,
            'visual_description': visual_desc,
            'camera_angle': prediction['camera_angle'],
            'mood': prediction['mood'],
            'lighting': lighting,
            'characters_present': characters,
            'narrator_line': narrator_line,
        }
    
    def _extract_characters(self, text: str) -> List[str]:
        """Extract character names from text."""
        import re
        
        char_pattern = re.compile(r'^([A-Z][A-Z\s\.\'\-]+)(?:\s*\(.*\))?$', re.MULTILINE)
        matches = char_pattern.findall(text)
        
        stopwords = {'INT', 'EXT', 'THE', 'A', 'AN', 'AND', 'BUT', 'OR', 'CUT', 'FADE'}
        characters = [
            m.strip() for m in matches 
            if m.strip() and m.strip() not in stopwords and len(m.strip()) < 30
        ]
        
        return list(set(characters))[:5]
    
    def _generate_visual_description(self, text: str, characters: List[str]) -> str:
        """Generate visual description from text."""
        import re
        
        scene_match = re.search(
            r'(INT\.|EXT\.|INT/EXT\.)\s*(.+?)(?:\s*[-–—]\s*(.+))?$',
            text,
            re.MULTILINE | re.IGNORECASE
        )
        
        parts = []
        
        if scene_match:
            location = scene_match.group(2).strip()
            time = scene_match.group(3).strip() if scene_match.group(3) else ''
            parts.append(f"{location}")
            if time:
                parts.append(time.lower())
        
        if characters:
            if len(characters) == 1:
                parts.append(f"{characters[0]} in frame")
            else:
                parts.append(f"{', '.join(characters[:2])} in scene")
        
        action_lines = [
            line.strip() for line in text.split('\n')
            if line.strip() and not line.strip().isupper() and not line.strip().startswith('(')
        ]
        
        if action_lines:
            action_summary = ' '.join(action_lines[:2])[:150]
            parts.append(action_summary)
        
        return '. '.join(parts) if parts else "Cinematic scene moment"
    
    def _generate_narrator_line(self, text: str) -> str:
        """Generate a narrator line (100-150 chars)."""
        clean_text = ' '.join(text.split())
        
        if len(clean_text) <= 150:
            return clean_text[:150]
        
        sentences = clean_text.replace('!', '.').replace('?', '.').split('.')
        sentences = [s.strip() for s in sentences if s.strip()]
        
        if sentences:
            result = sentences[0]
            if len(result) < 100 and len(sentences) > 1:
                result += '. ' + sentences[1]
            return result[:150]
        
        return clean_text[:150]
    
    def _suggest_lighting(self, mood: str, text: str) -> str:
        """Suggest lighting based on mood and content."""
        mood_lighting = {
            'tense': 'low-key dramatic',
            'romantic': 'golden hour',
            'action': 'harsh shadows',
            'mysterious': 'low-key dramatic',
            'comedic': 'high-key bright',
            'dramatic': 'low-key dramatic',
            'serene': 'natural daylight',
            'melancholic': 'moonlit',
            'neutral': 'natural daylight',
        }
        
        text_lower = text.lower()
        if 'night' in text_lower:
            return 'moonlit' if mood != 'action' else 'neon noir'
        elif 'morning' in text_lower or 'dawn' in text_lower:
            return 'golden hour'
        elif 'sunset' in text_lower or 'evening' in text_lower:
            return 'golden hour'
        
        return mood_lighting.get(mood, 'natural daylight')
    
    def _suggest_music(self, beat: Dict) -> str:
        """Suggest music for the first beat."""
        mood = beat.get('mood', 'neutral')
        
        music_suggestions = {
            'tense': 'ambient electronic tension with low drones',
            'romantic': 'soft piano with string accompaniment',
            'action': 'driving percussion with orchestral hits',
            'mysterious': 'ethereal pads with subtle dissonance',
            'comedic': 'playful woodwinds and pizzicato strings',
            'dramatic': 'orchestral strings building crescendo',
            'serene': 'gentle acoustic guitar and ambient textures',
            'melancholic': 'solo cello with minimal piano',
            'neutral': 'cinematic ambient underscore',
        }
        
        return music_suggestions.get(mood, 'cinematic ambient underscore')

# COMMAND ----------

segmenter = ScriptSegmenter(model, tokenizer)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Test Inference

# COMMAND ----------

test_script = """
INT. ABANDONED WAREHOUSE - NIGHT

Rain hammers against broken windows. DETECTIVE MAYA CHEN (40s) steps through the doorway, flashlight cutting through darkness.

MAYA
(whispered)
I know you're here, Marcus.

A SHADOW shifts behind rusted machinery. MARCUS VALE (50s) emerges, hands raised, face half-lit by moonlight.

MARCUS
You shouldn't have come alone.

Maya's hand moves to her holster. Thunder RUMBLES outside.

MAYA
I never do.

RED AND BLUE LIGHTS flood through the windows. Marcus smiles—but it doesn't reach his eyes.
"""

beats = segmenter.segment_script(test_script)

for beat in beats:
    print(f"\n=== Beat {beat['beat_number']} ===")
    print(f"Mood: {beat['mood']}")
    print(f"Camera: {beat['camera_angle']}")
    print(f"Lighting: {beat['lighting']}")
    print(f"Characters: {beat['characters_present']}")
    print(f"Visual: {beat['visual_description'][:100]}...")
    print(f"Narrator: {beat['narrator_line'][:100]}...")
    if 'music_recommendation' in beat:
        print(f"Music: {beat['music_recommendation']}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Create Model Serving Endpoint

# COMMAND ----------

import mlflow
from mlflow.models.signature import infer_signature

class SegmentationModelWrapper(mlflow.pyfunc.PythonModel):
    """Wrapper for MLflow model serving."""
    
    def load_context(self, context):
        import torch
        from transformers import DistilBertTokenizer
        
        self.model = mlflow.pytorch.load_model(context.artifacts["model"])
        self.tokenizer = DistilBertTokenizer.from_pretrained(
            context.artifacts["tokenizer"]
        )
        self.model.eval()
        
        from types import SimpleNamespace
        self.segmenter = self._create_segmenter()
    
    def _create_segmenter(self):
        return ScriptSegmenter(self.model, self.tokenizer)
    
    def predict(self, context, model_input):
        if isinstance(model_input, dict):
            script = model_input.get('script', '')
        else:
            script = model_input.iloc[0]['script']
        
        beats = self.segmenter.segment_script(script)
        return {'beats': beats}

# COMMAND ----------

import pandas as pd

input_example = pd.DataFrame([{
    "script": test_script
}])

output_example = {"beats": beats}

signature = infer_signature(input_example, output_example)

# COMMAND ----------

with mlflow.start_run(run_name="segmentation_serving"):
    mlflow.pyfunc.log_model(
        artifact_path="segmentation_model",
        python_model=SegmentationModelWrapper(),
        artifacts={
            "model": "models:/playwright_segmentation/Production",
            "tokenizer": "/dbfs/FileStore/playwright/final_model"
        },
        signature=signature,
        input_example=input_example,
        registered_model_name="playwright_segmentation_serving"
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Deploy to Model Serving

# COMMAND ----------

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import EndpointCoreConfigInput, ServedModelInput

w = WorkspaceClient()

endpoint_name = "playwright-segmentation"

try:
    w.serving_endpoints.create(
        name=endpoint_name,
        config=EndpointCoreConfigInput(
            served_models=[
                ServedModelInput(
                    model_name="playwright_segmentation_serving",
                    model_version="1",
                    workload_size="Small",
                    scale_to_zero_enabled=True,
                )
            ]
        )
    )
    print(f"Created endpoint: {endpoint_name}")
except Exception as e:
    print(f"Endpoint may already exist or error: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Test Endpoint

# COMMAND ----------

import requests
import json

DATABRICKS_HOST = dbutils.secrets.get(scope="playwright", key="databricks_host")
DATABRICKS_TOKEN = dbutils.secrets.get(scope="playwright", key="databricks_token")

endpoint_url = f"https://{DATABRICKS_HOST}/serving-endpoints/{endpoint_name}/invocations"

headers = {
    "Authorization": f"Bearer {DATABRICKS_TOKEN}",
    "Content-Type": "application/json"
}

payload = {
    "inputs": [{"script": test_script}]
}

response = requests.post(endpoint_url, headers=headers, json=payload)
print(json.dumps(response.json(), indent=2))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Endpoint Ready
# MAGIC 
# MAGIC The model is now deployed and accessible at:
# MAGIC ```
# MAGIC POST https://<databricks-host>/serving-endpoints/playwright-segmentation/invocations
# MAGIC ```
# MAGIC 
# MAGIC Update your FastAPI backend to call this endpoint instead of Gemini for script analysis.
