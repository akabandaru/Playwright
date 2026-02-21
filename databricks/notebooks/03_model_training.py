# Databricks notebook source
# MAGIC %md
# MAGIC # Script Segmentation Model - Training
# MAGIC 
# MAGIC This notebook trains a transformer-based sequence labeling model for beat segmentation.
# MAGIC 
# MAGIC **Model Architecture:**
# MAGIC - Base: DistilBERT (lightweight, fast inference)
# MAGIC - Task: Token classification (BIO tagging for beat boundaries)
# MAGIC - Additional heads: Mood classification, Camera angle prediction
# MAGIC 
# MAGIC **Training Strategy:**
# MAGIC - Multi-task learning for beat segmentation + metadata prediction
# MAGIC - MLflow tracking for experiments
# MAGIC - Model registered to Unity Catalog for serving

# COMMAND ----------

# MAGIC %pip install transformers torch datasets accelerate mlflow

# COMMAND ----------

import os
import json
import torch
import torch.nn as nn
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from torch.utils.data import Dataset, DataLoader
from transformers import (
    DistilBertTokenizer,
    DistilBertModel,
    DistilBertPreTrainedModel,
    TrainingArguments,
    Trainer,
    DataCollatorForTokenClassification,
)
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, f1_score
import mlflow
import mlflow.pytorch
from pyspark.sql import SparkSession

spark = SparkSession.builder.getOrCreate()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Model Architecture

# COMMAND ----------

class ScriptSegmentationModel(DistilBertPreTrainedModel):
    """
    Multi-task model for script segmentation.
    
    Tasks:
    1. Beat boundary detection (BIO tagging)
    2. Mood classification
    3. Camera angle prediction
    """
    
    def __init__(self, config, num_labels=3, num_moods=9, num_cameras=8):
        super().__init__(config)
        
        self.num_labels = num_labels
        self.num_moods = num_moods
        self.num_cameras = num_cameras
        
        self.distilbert = DistilBertModel(config)
        self.dropout = nn.Dropout(config.dropout)
        
        self.beat_classifier = nn.Linear(config.hidden_size, num_labels)
        
        self.mood_classifier = nn.Sequential(
            nn.Linear(config.hidden_size, 256),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(256, num_moods)
        )
        
        self.camera_classifier = nn.Sequential(
            nn.Linear(config.hidden_size, 256),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(256, num_cameras)
        )
        
        self.post_init()
    
    def forward(
        self,
        input_ids: torch.Tensor,
        attention_mask: Optional[torch.Tensor] = None,
        labels: Optional[torch.Tensor] = None,
        mood_labels: Optional[torch.Tensor] = None,
        camera_labels: Optional[torch.Tensor] = None,
    ) -> Dict[str, torch.Tensor]:
        
        outputs = self.distilbert(
            input_ids=input_ids,
            attention_mask=attention_mask,
        )
        
        sequence_output = self.dropout(outputs.last_hidden_state)
        
        beat_logits = self.beat_classifier(sequence_output)
        
        pooled_output = sequence_output[:, 0, :]
        mood_logits = self.mood_classifier(pooled_output)
        camera_logits = self.camera_classifier(pooled_output)
        
        loss = None
        if labels is not None:
            loss_fct = nn.CrossEntropyLoss()
            
            beat_loss = loss_fct(
                beat_logits.view(-1, self.num_labels),
                labels.view(-1)
            )
            
            total_loss = beat_loss
            
            if mood_labels is not None:
                mood_loss = loss_fct(mood_logits, mood_labels)
                total_loss = total_loss + 0.3 * mood_loss
            
            if camera_labels is not None:
                camera_loss = loss_fct(camera_logits, camera_labels)
                total_loss = total_loss + 0.3 * camera_loss
            
            loss = total_loss
        
        return {
            'loss': loss,
            'beat_logits': beat_logits,
            'mood_logits': mood_logits,
            'camera_logits': camera_logits,
        }

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Data Preparation

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

# COMMAND ----------

class ScriptDataset(Dataset):
    """Dataset for script segmentation training."""
    
    def __init__(
        self, 
        texts: List[str],
        labels: List[str],
        moods: List[str],
        cameras: List[str],
        tokenizer,
        max_length: int = 512
    ):
        self.texts = texts
        self.labels = labels
        self.moods = moods
        self.cameras = cameras
        self.tokenizer = tokenizer
        self.max_length = max_length
    
    def __len__(self):
        return len(self.texts)
    
    def __getitem__(self, idx):
        text = self.texts[idx]
        label = self.labels[idx]
        mood = self.moods[idx]
        camera = self.cameras[idx]
        
        encoding = self.tokenizer(
            text,
            truncation=True,
            max_length=self.max_length,
            padding='max_length',
            return_tensors='pt'
        )
        
        label_id = LABEL_TO_ID.get(label, 0)
        label_ids = [label_id] * self.max_length
        
        mood_id = MOOD_TO_ID.get(mood, 0)
        camera_id = CAMERA_TO_ID.get(camera, 0)
        
        return {
            'input_ids': encoding['input_ids'].squeeze(),
            'attention_mask': encoding['attention_mask'].squeeze(),
            'labels': torch.tensor(label_ids, dtype=torch.long),
            'mood_labels': torch.tensor(mood_id, dtype=torch.long),
            'camera_labels': torch.tensor(camera_id, dtype=torch.long),
        }

# COMMAND ----------

df_sequences = spark.table("playwright.sequence_labels").toPandas()

print(f"Total sequences: {len(df_sequences)}")
print(f"Label distribution:\n{df_sequences['label'].value_counts()}")

# COMMAND ----------

texts = df_sequences['text'].tolist()
labels = df_sequences['label'].tolist()
moods = df_sequences['mood'].tolist()
cameras = df_sequences['camera'].tolist()

train_texts, val_texts, train_labels, val_labels, train_moods, val_moods, train_cameras, val_cameras = train_test_split(
    texts, labels, moods, cameras,
    test_size=0.2,
    random_state=42,
    stratify=labels
)

print(f"Training samples: {len(train_texts)}")
print(f"Validation samples: {len(val_texts)}")

# COMMAND ----------

tokenizer = DistilBertTokenizer.from_pretrained('distilbert-base-uncased')

train_dataset = ScriptDataset(
    train_texts, train_labels, train_moods, train_cameras,
    tokenizer, max_length=256
)

val_dataset = ScriptDataset(
    val_texts, val_labels, val_moods, val_cameras,
    tokenizer, max_length=256
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Training with MLflow

# COMMAND ----------

mlflow.set_experiment("/Users/{}/playwright-segmentation".format(
    spark.sql("SELECT current_user()").collect()[0][0]
))

# COMMAND ----------

def compute_metrics(eval_pred):
    """Compute metrics for evaluation."""
    predictions, labels = eval_pred
    
    if isinstance(predictions, tuple):
        beat_preds = predictions[0]
    else:
        beat_preds = predictions
    
    beat_preds = np.argmax(beat_preds, axis=-1)
    
    true_labels = []
    pred_labels = []
    
    for pred_seq, label_seq in zip(beat_preds, labels):
        for pred, label in zip(pred_seq, label_seq):
            if label != -100:
                true_labels.append(label)
                pred_labels.append(pred)
    
    f1 = f1_score(true_labels, pred_labels, average='weighted')
    
    return {'f1': f1}

# COMMAND ----------

from transformers import DistilBertConfig

config = DistilBertConfig.from_pretrained('distilbert-base-uncased')
model = ScriptSegmentationModel(
    config,
    num_labels=len(LABEL_TO_ID),
    num_moods=len(MOOD_TO_ID),
    num_cameras=len(CAMERA_TO_ID)
)

# COMMAND ----------

training_args = TrainingArguments(
    output_dir='/dbfs/FileStore/playwright/model_checkpoints',
    num_train_epochs=5,
    per_device_train_batch_size=16,
    per_device_eval_batch_size=32,
    warmup_steps=500,
    weight_decay=0.01,
    logging_dir='/dbfs/FileStore/playwright/logs',
    logging_steps=100,
    eval_strategy="epoch",
    save_strategy="epoch",
    load_best_model_at_end=True,
    metric_for_best_model='f1',
    greater_is_better=True,
    fp16=torch.cuda.is_available(),
    dataloader_num_workers=4,
    report_to="mlflow",
)

# COMMAND ----------

class CustomTrainer(Trainer):
    """Custom trainer to handle multi-task outputs."""
    
    def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
        labels = inputs.pop("labels")
        mood_labels = inputs.pop("mood_labels", None)
        camera_labels = inputs.pop("camera_labels", None)
        
        outputs = model(
            **inputs,
            labels=labels,
            mood_labels=mood_labels,
            camera_labels=camera_labels
        )
        
        loss = outputs['loss']
        
        return (loss, outputs) if return_outputs else loss

# COMMAND ----------

with mlflow.start_run(run_name="script_segmentation_v1") as run:
    mlflow.log_params({
        "model_type": "distilbert-multitask",
        "num_labels": len(LABEL_TO_ID),
        "num_moods": len(MOOD_TO_ID),
        "num_cameras": len(CAMERA_TO_ID),
        "max_length": 256,
        "train_samples": len(train_dataset),
        "val_samples": len(val_dataset),
    })
    
    trainer = CustomTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        compute_metrics=compute_metrics,
    )
    
    trainer.train()
    
    eval_results = trainer.evaluate()
    mlflow.log_metrics(eval_results)
    
    model_path = "/dbfs/FileStore/playwright/final_model"
    trainer.save_model(model_path)
    tokenizer.save_pretrained(model_path)
    
    mlflow.pytorch.log_model(
        model,
        "model",
        registered_model_name="playwright_segmentation"
    )
    
    print(f"Run ID: {run.info.run_id}")
    print(f"Evaluation results: {eval_results}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Model Evaluation

# COMMAND ----------

model.eval()

sample_text = """
INT. ABANDONED WAREHOUSE - NIGHT

Rain hammers against broken windows. DETECTIVE MAYA CHEN steps through the doorway, flashlight cutting through darkness.

MAYA
(whispered)
I know you're here, Marcus.

A SHADOW shifts behind rusted machinery. MARCUS VALE emerges, hands raised.

MARCUS
You shouldn't have come alone.
"""

inputs = tokenizer(
    sample_text,
    return_tensors='pt',
    truncation=True,
    max_length=256,
    padding='max_length'
)

with torch.no_grad():
    outputs = model(**inputs)

beat_preds = torch.argmax(outputs['beat_logits'], dim=-1)
mood_pred = torch.argmax(outputs['mood_logits'], dim=-1)
camera_pred = torch.argmax(outputs['camera_logits'], dim=-1)

print(f"Predicted mood: {ID_TO_MOOD[mood_pred.item()]}")
print(f"Predicted camera: {ID_TO_CAMERA[camera_pred.item()]}")

tokens = tokenizer.convert_ids_to_tokens(inputs['input_ids'][0])
beat_boundaries = []
for i, (token, pred) in enumerate(zip(tokens, beat_preds[0])):
    if pred.item() == 1:
        beat_boundaries.append(i)
        
print(f"Beat boundaries at token positions: {beat_boundaries}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Register Model for Serving

# COMMAND ----------

from mlflow.tracking import MlflowClient

client = MlflowClient()

model_name = "playwright_segmentation"
model_version = client.get_latest_versions(model_name, stages=["None"])[0].version

client.transition_model_version_stage(
    name=model_name,
    version=model_version,
    stage="Production"
)

print(f"Model {model_name} version {model_version} promoted to Production")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Next Steps
# MAGIC 
# MAGIC Model trained and registered:
# MAGIC - Model: `playwright_segmentation` (Production)
# MAGIC - Location: `/dbfs/FileStore/playwright/final_model`
# MAGIC 
# MAGIC Proceed to **04_model_serving** to deploy the model for inference.
