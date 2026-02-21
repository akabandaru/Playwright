# Databricks notebook source
# MAGIC %md
# MAGIC # Script Segmentation Model - Data Preprocessing
# MAGIC 
# MAGIC This notebook processes raw scripts to create training data for beat segmentation:
# MAGIC 1. Parse scene boundaries (INT./EXT. markers)
# MAGIC 2. Identify beat boundaries within scenes
# MAGIC 3. Extract features for each segment
# MAGIC 4. Create labeled training dataset

# COMMAND ----------

# MAGIC %pip install transformers torch nltk spacy
# MAGIC %pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl

# COMMAND ----------

import re
import json
import nltk
import spacy
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, udf, explode, lit, monotonically_increasing_id
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, 
    ArrayType, FloatType, BooleanType
)

spark = SparkSession.builder.getOrCreate()
nltk.download('punkt')
nlp = spacy.load('en_core_web_sm')

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Script Parsing Utilities

# COMMAND ----------

@dataclass
class ScriptElement:
    """Represents a parsed element from a screenplay."""
    element_type: str  # SCENE_HEADING, ACTION, CHARACTER, DIALOGUE, PARENTHETICAL, TRANSITION
    text: str
    line_number: int
    raw_text: str

@dataclass 
class Beat:
    """Represents a visual beat in the script."""
    beat_id: int
    elements: List[ScriptElement]
    scene_id: int
    start_line: int
    end_line: int
    visual_description: str
    characters: List[str]
    mood: str
    action_type: str

# COMMAND ----------

class ScreenplayParser:
    """Parser for standard screenplay format."""
    
    SCENE_HEADING_PATTERN = re.compile(
        r'^(INT\.|EXT\.|INT/EXT\.|I/E\.)[\s]+(.+?)(?:\s*[-–—]\s*(.+))?$',
        re.IGNORECASE
    )
    
    CHARACTER_PATTERN = re.compile(r'^([A-Z][A-Z\s\.\'\-]+)(\s*\(.*\))?$')
    
    PARENTHETICAL_PATTERN = re.compile(r'^\s*\(.*\)\s*$')
    
    TRANSITION_PATTERN = re.compile(
        r'^(FADE IN:|FADE OUT:|CUT TO:|DISSOLVE TO:|SMASH CUT:|MATCH CUT:|FADE TO BLACK|THE END).*$',
        re.IGNORECASE
    )
    
    def __init__(self):
        self.elements = []
        self.scenes = []
        
    def parse(self, script_text: str) -> List[ScriptElement]:
        """Parse a screenplay into structured elements."""
        lines = script_text.split('\n')
        self.elements = []
        
        current_character = None
        
        for i, line in enumerate(lines):
            raw_line = line
            line = line.strip()
            
            if not line:
                continue
            
            element = self._classify_line(line, i, raw_line, current_character)
            if element:
                self.elements.append(element)
                if element.element_type == 'CHARACTER':
                    current_character = element.text
                elif element.element_type in ['SCENE_HEADING', 'ACTION']:
                    current_character = None
        
        return self.elements
    
    def _classify_line(
        self, 
        line: str, 
        line_num: int, 
        raw_line: str,
        current_character: Optional[str]
    ) -> Optional[ScriptElement]:
        """Classify a single line of the screenplay."""
        
        if self.SCENE_HEADING_PATTERN.match(line):
            return ScriptElement('SCENE_HEADING', line, line_num, raw_line)
        
        if self.TRANSITION_PATTERN.match(line):
            return ScriptElement('TRANSITION', line, line_num, raw_line)
        
        if self.PARENTHETICAL_PATTERN.match(line):
            return ScriptElement('PARENTHETICAL', line, line_num, raw_line)
        
        if self.CHARACTER_PATTERN.match(line) and len(line) < 50:
            char_match = self.CHARACTER_PATTERN.match(line)
            char_name = char_match.group(1).strip()
            if char_name not in ['THE', 'A', 'AN', 'AND', 'BUT', 'OR']:
                return ScriptElement('CHARACTER', char_name, line_num, raw_line)
        
        if current_character and not line.isupper():
            return ScriptElement('DIALOGUE', line, line_num, raw_line)
        
        return ScriptElement('ACTION', line, line_num, raw_line)
    
    def extract_scenes(self) -> List[Dict]:
        """Extract scenes from parsed elements."""
        scenes = []
        current_scene = None
        
        for element in self.elements:
            if element.element_type == 'SCENE_HEADING':
                if current_scene:
                    scenes.append(current_scene)
                
                match = self.SCENE_HEADING_PATTERN.match(element.text)
                current_scene = {
                    'scene_id': len(scenes),
                    'heading': element.text,
                    'location_type': match.group(1) if match else '',
                    'location': match.group(2) if match else '',
                    'time_of_day': match.group(3) if match else '',
                    'start_line': element.line_number,
                    'elements': []
                }
            elif current_scene:
                current_scene['elements'].append({
                    'type': element.element_type,
                    'text': element.text,
                    'line': element.line_number
                })
        
        if current_scene:
            scenes.append(current_scene)
        
        return scenes

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Beat Segmentation Logic

# COMMAND ----------

class BeatSegmenter:
    """Segments scenes into visual beats."""
    
    BEAT_TRIGGERS = [
        'suddenly', 'then', 'but', 'meanwhile', 'later',
        'moments later', 'beat', 'pause', 'silence',
        'cut to', 'angle on', 'close on', 'wide on',
        'pov', 'reverse', 'two shot', 'over shoulder'
    ]
    
    MOOD_KEYWORDS = {
        'tense': ['gun', 'knife', 'blood', 'scream', 'fear', 'danger', 'threat', 'dark'],
        'romantic': ['kiss', 'love', 'embrace', 'tender', 'gentle', 'heart', 'passion'],
        'action': ['run', 'fight', 'chase', 'explode', 'crash', 'punch', 'kick', 'shoot'],
        'mysterious': ['shadow', 'hidden', 'secret', 'strange', 'unknown', 'eerie'],
        'comedic': ['laugh', 'joke', 'funny', 'smile', 'grin', 'absurd'],
        'dramatic': ['cry', 'tears', 'angry', 'shout', 'confront', 'reveal'],
        'serene': ['calm', 'peaceful', 'quiet', 'still', 'gentle', 'soft'],
        'melancholic': ['sad', 'alone', 'lonely', 'grief', 'loss', 'memory']
    }
    
    CAMERA_INDICATORS = {
        'close-up': ['close on', 'close-up', 'cu on', 'tight on', 'eyes', 'face', 'hand'],
        'wide shot': ['wide', 'establishing', 'aerial', 'landscape', 'vista'],
        'medium shot': ['medium', 'waist', 'two shot', 'group'],
        'pov shot': ['pov', 'point of view', 'subjective', 'through eyes'],
        'over-the-shoulder': ['over shoulder', 'ots', 'behind'],
        'tracking shot': ['follows', 'tracking', 'dolly', 'moving with'],
        'low angle': ['low angle', 'looking up', 'from below'],
        'high angle': ['high angle', 'looking down', 'from above', 'bird']
    }
    
    def __init__(self):
        self.nlp = nlp
    
    def segment_scene(self, scene: Dict) -> List[Dict]:
        """Segment a scene into beats."""
        elements = scene.get('elements', [])
        if not elements:
            return []
        
        beats = []
        current_beat_elements = []
        beat_id = 0
        
        for i, element in enumerate(elements):
            should_split = self._should_split_beat(element, current_beat_elements, elements, i)
            
            if should_split and current_beat_elements:
                beat = self._create_beat(
                    beat_id, 
                    current_beat_elements, 
                    scene['scene_id'],
                    scene
                )
                beats.append(beat)
                beat_id += 1
                current_beat_elements = []
            
            current_beat_elements.append(element)
        
        if current_beat_elements:
            beat = self._create_beat(
                beat_id, 
                current_beat_elements, 
                scene['scene_id'],
                scene
            )
            beats.append(beat)
        
        return beats
    
    def _should_split_beat(
        self, 
        element: Dict, 
        current_elements: List[Dict],
        all_elements: List[Dict],
        index: int
    ) -> bool:
        """Determine if a new beat should start."""
        if not current_elements:
            return False
        
        text_lower = element['text'].lower()
        
        for trigger in self.BEAT_TRIGGERS:
            if trigger in text_lower:
                return True
        
        if element['type'] == 'CHARACTER':
            dialogue_count = sum(1 for e in current_elements if e['type'] == 'DIALOGUE')
            if dialogue_count >= 4:
                return True
        
        if element['type'] == 'ACTION':
            action_count = sum(1 for e in current_elements if e['type'] == 'ACTION')
            if action_count >= 3:
                return True
        
        total_text = ' '.join(e['text'] for e in current_elements)
        if len(total_text) > 500:
            return True
        
        return False
    
    def _create_beat(
        self, 
        beat_id: int, 
        elements: List[Dict], 
        scene_id: int,
        scene: Dict
    ) -> Dict:
        """Create a beat dictionary from elements."""
        full_text = ' '.join(e['text'] for e in elements)
        
        characters = list(set(
            e['text'] for e in elements if e['type'] == 'CHARACTER'
        ))
        
        action_text = ' '.join(
            e['text'] for e in elements if e['type'] == 'ACTION'
        )
        
        dialogue_text = ' '.join(
            e['text'] for e in elements if e['type'] == 'DIALOGUE'
        )
        
        mood = self._detect_mood(full_text)
        camera = self._suggest_camera(full_text, elements)
        
        visual_desc = self._generate_visual_description(
            action_text, 
            characters, 
            scene,
            elements
        )
        
        return {
            'beat_id': beat_id,
            'scene_id': scene_id,
            'start_line': elements[0]['line'] if elements else 0,
            'end_line': elements[-1]['line'] if elements else 0,
            'full_text': full_text,
            'action_text': action_text,
            'dialogue_text': dialogue_text,
            'characters': characters,
            'mood': mood,
            'suggested_camera': camera,
            'visual_description': visual_desc,
            'element_count': len(elements),
            'has_dialogue': any(e['type'] == 'DIALOGUE' for e in elements),
            'has_action': any(e['type'] == 'ACTION' for e in elements)
        }
    
    def _detect_mood(self, text: str) -> str:
        """Detect the mood of a beat."""
        text_lower = text.lower()
        mood_scores = {}
        
        for mood, keywords in self.MOOD_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                mood_scores[mood] = score
        
        if mood_scores:
            return max(mood_scores, key=mood_scores.get)
        return 'neutral'
    
    def _suggest_camera(self, text: str, elements: List[Dict]) -> str:
        """Suggest camera angle based on content."""
        text_lower = text.lower()
        
        for camera, indicators in self.CAMERA_INDICATORS.items():
            if any(ind in text_lower for ind in indicators):
                return camera
        
        dialogue_count = sum(1 for e in elements if e['type'] == 'DIALOGUE')
        char_count = len(set(e['text'] for e in elements if e['type'] == 'CHARACTER'))
        
        if char_count == 1 and dialogue_count > 0:
            return 'close-up'
        elif char_count == 2:
            return 'over-the-shoulder'
        elif char_count > 2:
            return 'wide shot'
        
        return 'medium shot'
    
    def _generate_visual_description(
        self, 
        action_text: str, 
        characters: List[str],
        scene: Dict,
        elements: List[Dict]
    ) -> str:
        """Generate a visual description for the beat."""
        parts = []
        
        location = scene.get('location', '')
        time = scene.get('time_of_day', '')
        loc_type = scene.get('location_type', '')
        
        if location:
            setting = f"{loc_type} {location}".strip()
            if time:
                setting += f" - {time}"
            parts.append(setting)
        
        if characters:
            if len(characters) == 1:
                parts.append(f"{characters[0]} in frame")
            else:
                parts.append(f"{', '.join(characters[:3])} in scene")
        
        if action_text:
            action_summary = action_text[:200].strip()
            if action_summary:
                parts.append(action_summary)
        
        return '. '.join(parts) if parts else "Scene moment"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Process Scripts and Create Training Data

# COMMAND ----------

def process_script_to_beats(script_text: str, script_id: str) -> List[Dict]:
    """Process a full script into beats."""
    parser = ScreenplayParser()
    segmenter = BeatSegmenter()
    
    parser.parse(script_text)
    scenes = parser.extract_scenes()
    
    all_beats = []
    global_beat_id = 0
    
    for scene in scenes:
        scene_beats = segmenter.segment_scene(scene)
        for beat in scene_beats:
            beat['global_beat_id'] = global_beat_id
            beat['script_id'] = script_id
            beat['scene_heading'] = scene.get('heading', '')
            global_beat_id += 1
        all_beats.extend(scene_beats)
    
    return all_beats

# COMMAND ----------

df_scripts = spark.table("playwright.imsdb_scripts")

scripts_list = df_scripts.select("script_name", "text").collect()

all_beats_data = []
for row in scripts_list:
    try:
        beats = process_script_to_beats(row['text'], row['script_name'])
        all_beats_data.extend(beats)
        print(f"Processed {row['script_name']}: {len(beats)} beats")
    except Exception as e:
        print(f"Error processing {row['script_name']}: {e}")

print(f"\nTotal beats extracted: {len(all_beats_data)}")

# COMMAND ----------

beats_schema = StructType([
    StructField("global_beat_id", IntegerType(), True),
    StructField("script_id", StringType(), True),
    StructField("beat_id", IntegerType(), True),
    StructField("scene_id", IntegerType(), True),
    StructField("scene_heading", StringType(), True),
    StructField("start_line", IntegerType(), True),
    StructField("end_line", IntegerType(), True),
    StructField("full_text", StringType(), True),
    StructField("action_text", StringType(), True),
    StructField("dialogue_text", StringType(), True),
    StructField("characters", ArrayType(StringType()), True),
    StructField("mood", StringType(), True),
    StructField("suggested_camera", StringType(), True),
    StructField("visual_description", StringType(), True),
    StructField("element_count", IntegerType(), True),
    StructField("has_dialogue", BooleanType(), True),
    StructField("has_action", BooleanType(), True),
])

df_beats = spark.createDataFrame(all_beats_data, schema=beats_schema)
df_beats.write.mode("overwrite").saveAsTable("playwright.training_beats")

print(f"Saved {df_beats.count()} beats to playwright.training_beats")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Create Sequence Labeling Dataset

# COMMAND ----------

def create_sequence_labels(script_text: str) -> List[Dict]:
    """Create BIO-tagged sequence labels for training."""
    parser = ScreenplayParser()
    segmenter = BeatSegmenter()
    
    parser.parse(script_text)
    scenes = parser.extract_scenes()
    
    labeled_sequences = []
    
    for scene in scenes:
        scene_beats = segmenter.segment_scene(scene)
        
        for beat_idx, beat in enumerate(scene_beats):
            elements = scene['elements'][beat['start_line']:beat['end_line']+1] if scene['elements'] else []
            
            for elem_idx, elem in enumerate(elements):
                if elem_idx == 0:
                    label = 'B-BEAT'
                else:
                    label = 'I-BEAT'
                
                labeled_sequences.append({
                    'text': elem['text'],
                    'element_type': elem['type'],
                    'label': label,
                    'beat_id': beat_idx,
                    'scene_id': scene['scene_id'],
                    'mood': beat['mood'],
                    'camera': beat['suggested_camera']
                })
    
    return labeled_sequences

# COMMAND ----------

all_sequences = []
for row in scripts_list[:50]:
    try:
        sequences = create_sequence_labels(row['text'])
        for seq in sequences:
            seq['script_id'] = row['script_name']
        all_sequences.extend(sequences)
    except Exception as e:
        print(f"Error: {e}")

print(f"Total labeled sequences: {len(all_sequences)}")

# COMMAND ----------

seq_schema = StructType([
    StructField("script_id", StringType(), True),
    StructField("text", StringType(), True),
    StructField("element_type", StringType(), True),
    StructField("label", StringType(), True),
    StructField("beat_id", IntegerType(), True),
    StructField("scene_id", IntegerType(), True),
    StructField("mood", StringType(), True),
    StructField("camera", StringType(), True),
])

df_sequences = spark.createDataFrame(all_sequences, schema=seq_schema)
df_sequences.write.mode("overwrite").saveAsTable("playwright.sequence_labels")

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT label, COUNT(*) as count 
# MAGIC FROM playwright.sequence_labels 
# MAGIC GROUP BY label

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT mood, COUNT(*) as count 
# MAGIC FROM playwright.training_beats 
# MAGIC GROUP BY mood 
# MAGIC ORDER BY count DESC

# COMMAND ----------

# MAGIC %md
# MAGIC ## Next Steps
# MAGIC 
# MAGIC Training data created:
# MAGIC - `playwright.training_beats` - Beat-level data with features
# MAGIC - `playwright.sequence_labels` - BIO-tagged sequences for training
# MAGIC 
# MAGIC Proceed to **03_model_training** to train the segmentation model.
