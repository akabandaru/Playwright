import os
import time
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List
from contextlib import contextmanager

try:
    import mlflow
    from databricks.sdk import WorkspaceClient
    DATABRICKS_AVAILABLE = True
except ImportError:
    DATABRICKS_AVAILABLE = False

_current_run = None
_inference_logs: List[Dict[str, Any]] = []

def init_databricks():
    """Initialize Databricks and MLflow connection."""
    if not DATABRICKS_AVAILABLE:
        return False
    
    host = os.getenv("DATABRICKS_HOST")
    token = os.getenv("DATABRICKS_TOKEN")
    experiment_id = os.getenv("DATABRICKS_MLFLOW_EXPERIMENT_ID")
    
    if not all([host, token]):
        return False
    
    try:
        mlflow.set_tracking_uri(f"databricks")
        os.environ["DATABRICKS_HOST"] = host
        os.environ["DATABRICKS_TOKEN"] = token
        
        if experiment_id:
            mlflow.set_experiment(experiment_id=experiment_id)
        
        return True
    except Exception as e:
        print(f"Failed to initialize Databricks: {e}")
        return False

def start_run(script: str) -> Optional[str]:
    """Start a new MLflow run for pipeline tracking."""
    global _current_run
    
    run_id = str(uuid.uuid4())
    
    log_entry = {
        "run_id": run_id,
        "script_preview": script[:200] if script else "",
        "start_time": datetime.now().isoformat(),
        "status": "started",
        "metrics": {},
    }
    _inference_logs.append(log_entry)
    
    if not DATABRICKS_AVAILABLE or not init_databricks():
        _current_run = {"run_id": run_id, "local": True}
        return run_id
    
    try:
        _current_run = mlflow.start_run()
        mlflow.log_param("script_length", len(script))
        mlflow.log_param("script_preview", script[:100])
        return _current_run.info.run_id
    except Exception as e:
        print(f"Failed to start MLflow run: {e}")
        _current_run = {"run_id": run_id, "local": True}
        return run_id

def log_metric(key: str, value: float):
    """Log a metric to the current run."""
    global _current_run, _inference_logs
    
    if _inference_logs:
        _inference_logs[-1]["metrics"][key] = value
    
    if not DATABRICKS_AVAILABLE or not _current_run:
        return
    
    if isinstance(_current_run, dict) and _current_run.get("local"):
        return
    
    try:
        mlflow.log_metric(key, value)
    except Exception as e:
        print(f"Failed to log metric: {e}")

def log_params(params: Dict[str, Any]):
    """Log parameters to the current run."""
    if not DATABRICKS_AVAILABLE or not _current_run:
        return
    
    if isinstance(_current_run, dict) and _current_run.get("local"):
        return
    
    try:
        mlflow.log_params(params)
    except Exception as e:
        print(f"Failed to log params: {e}")

def end_run(status: str = "FINISHED"):
    """End the current MLflow run."""
    global _current_run, _inference_logs
    
    if _inference_logs:
        _inference_logs[-1]["status"] = status
        _inference_logs[-1]["end_time"] = datetime.now().isoformat()
    
    if not DATABRICKS_AVAILABLE or not _current_run:
        _current_run = None
        return
    
    if isinstance(_current_run, dict) and _current_run.get("local"):
        _current_run = None
        return
    
    try:
        mlflow.end_run(status=status)
    except Exception as e:
        print(f"Failed to end run: {e}")
    finally:
        _current_run = None

def log_inference(
    script: str,
    beats_count: int,
    moods: List[str],
    camera_angles: List[str],
    pipeline_latency: float,
):
    """Log inference data to the inference_logs table."""
    global _inference_logs
    
    log_entry = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "script_preview": script[:200] if script else "",
        "beats_count": beats_count,
        "moods": moods,
        "camera_angles": camera_angles,
        "pipeline_latency": pipeline_latency,
    }
    
    _inference_logs.append(log_entry)
    
    if len(_inference_logs) > 1000:
        _inference_logs = _inference_logs[-500:]

def get_dashboard_stats() -> Dict[str, Any]:
    """Get aggregated stats from inference logs."""
    global _inference_logs
    
    if not _inference_logs:
        return {
            "totalScenes": 0,
            "avgPipelineTime": 0,
            "mostUsedMood": None,
            "mostUsedCamera": None,
        }
    
    completed_runs = [
        log for log in _inference_logs 
        if log.get("status") == "FINISHED" or log.get("beats_count")
    ]
    
    total_scenes = len(completed_runs)
    
    latencies = [
        log.get("pipeline_latency", 0) 
        for log in completed_runs 
        if log.get("pipeline_latency")
    ]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    
    all_moods = []
    all_cameras = []
    for log in completed_runs:
        all_moods.extend(log.get("moods", []))
        all_cameras.extend(log.get("camera_angles", []))
    
    most_used_mood = max(set(all_moods), key=all_moods.count) if all_moods else None
    most_used_camera = max(set(all_cameras), key=all_cameras.count) if all_cameras else None
    
    return {
        "totalScenes": total_scenes,
        "avgPipelineTime": round(avg_latency, 2),
        "mostUsedMood": most_used_mood,
        "mostUsedCamera": most_used_camera,
    }
