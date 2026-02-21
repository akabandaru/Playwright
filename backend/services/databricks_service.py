import csv
import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

try:
    import mlflow
    from databricks.sdk import WorkspaceClient
    DATABRICKS_AVAILABLE = True
except ImportError:
    DATABRICKS_AVAILABLE = False

try:
    from databricks import sql as databricks_sql
    DATABRICKS_SQL_AVAILABLE = True
except ImportError:
    DATABRICKS_SQL_AVAILABLE = False

_FEW_SHOT_CSV = Path(__file__).parent.parent / "data" / "few_shot_examples.csv"

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
        mlflow.set_tracking_uri("databricks")
        os.environ["DATABRICKS_HOST"] = host
        os.environ["DATABRICKS_TOKEN"] = token

        if experiment_id:
            # Numeric ID takes priority if set
            mlflow.set_experiment(experiment_id=experiment_id)
        else:
            # Fall back to a named experiment — Databricks creates it if missing
            experiment_name = os.getenv("DATABRICKS_MLFLOW_EXPERIMENT_NAME", "/playwright/runs")
            mlflow.set_experiment(experiment_name)

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

def log_dataset_stats(dataset_name: str, record_count: int, sample_titles: Optional[List[str]] = None):
    """Log dataset metadata to the current MLflow run."""
    if _inference_logs:
        _inference_logs[-1].setdefault("datasets", {})[dataset_name] = {
            "record_count": record_count,
            "sample_titles": sample_titles or [],
        }

    if not DATABRICKS_AVAILABLE or not _current_run:
        return

    if isinstance(_current_run, dict) and _current_run.get("local"):
        return

    try:
        mlflow.log_param(f"dataset_{dataset_name}_count", record_count)
        if sample_titles:
            mlflow.log_param(f"dataset_{dataset_name}_samples", ", ".join(sample_titles[:5]))
    except Exception as e:
        print(f"Failed to log dataset stats: {e}")


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

def get_few_shot_examples(limit: int = 3) -> List[Dict[str, Any]]:
    """
    Fetch few-shot examples for the scene decomposer prompt.

    Primary path: Databricks SQL warehouse
        SELECT genre, scene_text, beat_breakdown
        FROM few_shot_examples LIMIT <limit>

    Fallback: read from the local CSV at data/few_shot_examples.csv
    so the app works even without a live Databricks connection.

    Returns a list of dicts with keys: genre, scene, beats
    """
    rows = _fetch_few_shot_from_databricks(limit)
    if rows is None:
        rows = _fetch_few_shot_from_csv(limit)
    return rows


def _fetch_few_shot_from_databricks(limit: int) -> Optional[List[Dict[str, Any]]]:
    """Query the Databricks SQL warehouse. Returns None if unavailable."""
    if not DATABRICKS_SQL_AVAILABLE:
        return None

    host = os.getenv("DATABRICKS_HOST")
    token = os.getenv("DATABRICKS_TOKEN")
    http_path = os.getenv("DATABRICKS_HTTP_PATH")

    if not all([host, token, http_path]):
        return None

    try:
        with databricks_sql.connect(
            server_hostname=host.replace("https://", ""),
            http_path=http_path,
            access_token=token,
        ) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT genre, scene_text, beat_breakdown "
                    f"FROM few_shot_examples LIMIT {int(limit)}"
                )
                rows = cursor.fetchall()
                columns = [d[0] for d in cursor.description]

        results = []
        for row in rows:
            record = dict(zip(columns, row))
            results.append({
                "genre": record.get("genre", ""),
                "scene": record.get("scene_text", ""),
                "beats": json.loads(record.get("beat_breakdown") or "[]"),
            })
        return results

    except Exception as e:
        print(f"Databricks SQL fetch failed, falling back to CSV: {e}")
        return None


def _fetch_few_shot_from_csv(limit: int) -> List[Dict[str, Any]]:
    """Read few-shot examples from the local CSV fallback."""
    if not _FEW_SHOT_CSV.exists():
        print(f"Warning: few_shot_examples.csv not found at {_FEW_SHOT_CSV}")
        return []

    results = []
    with _FEW_SHOT_CSV.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader):
            if i >= limit:
                break
            results.append({
                "genre": row.get("genre", ""),
                "scene": row.get("scene_text", ""),
                "beats": json.loads(row.get("beat_breakdown") or "[]"),
            })
    return results


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
