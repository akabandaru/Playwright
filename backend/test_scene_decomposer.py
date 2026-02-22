"""
Comprehensive test for scene_decomposer + Databricks connectivity.
Run from the backend/ folder:

    source venv/bin/activate
    python test_scene_decomposer.py
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
sys.path.insert(0, str(Path(__file__).parent))

# ── Colours ───────────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def ok(msg):   print(f"  {GREEN}✓{RESET}  {msg}")
def fail(msg): print(f"  {RED}✗{RESET}  {msg}")
def warn(msg): print(f"  {YELLOW}⚠{RESET}  {msg}")
def section(title): print(f"\n{BOLD}{CYAN}── {title} {'─' * (50 - len(title))}{RESET}")

# ── Test scene ────────────────────────────────────────────────────────────────
TEST_SCENE = """
INT. PARKING GARAGE - NIGHT
Fluorescent lights flicker overhead, casting stuttering shadows.
DETECTIVE SARAH COLE (40s, sharp eyes, rumpled grey coat) moves
between parked cars, hand on her holster.
A FIGURE steps out from behind a concrete pillar.
FIGURE
You shouldn't have come alone.
Sarah doesn't flinch.
SARAH
Neither should you.
"""

# ─────────────────────────────────────────────────────────────────────────────
# 1. Databricks SQL connection
# ─────────────────────────────────────────────────────────────────────────────
def test_databricks_sql():
    section("Databricks SQL Warehouse")
    host  = os.getenv("DATABRICKS_HOST", "")
    token = os.getenv("DATABRICKS_TOKEN", "")
    path  = os.getenv("DATABRICKS_HTTP_PATH", "")

    if not all([host, token, path]):
        fail(f"Missing env vars  host={'SET' if host else 'MISSING'}  "
             f"token={'SET' if token else 'MISSING'}  path={'SET' if path else 'MISSING'}")
        return False

    ok(f"Env vars present  host={host}")

    try:
        from databricks import sql as databricks_sql
    except ImportError:
        fail("databricks-sql-connector not installed — run: pip install databricks-sql-connector")
        return False

    try:
        t0 = time.time()
        with databricks_sql.connect(
            server_hostname=host.replace("https://", ""),
            http_path=path,
            access_token=token,
        ) as conn:
            with conn.cursor() as cursor:
                # Ping
                cursor.execute("SELECT 1 AS ping")
                assert cursor.fetchone()[0] == 1
                ok(f"Warehouse ping OK  ({(time.time()-t0)*1000:.0f} ms)")

                # Table exists
                cursor.execute("SHOW TABLES")
                tables = [r[1] for r in cursor.fetchall()]
                if "few_shot_examples" in tables:
                    ok(f"Table few_shot_examples found  (all tables: {tables})")
                else:
                    fail(f"Table few_shot_examples NOT found  (tables: {tables})")
                    return False

                # Row count
                cursor.execute("SELECT COUNT(*) FROM few_shot_examples")
                count = cursor.fetchone()[0]
                ok(f"Row count: {count}")
                if count == 0:
                    warn("Table is empty — few-shot examples will not be used")

                # Schema check
                cursor.execute("DESCRIBE few_shot_examples")
                cols = {r[0] for r in cursor.fetchall()}
                required = {"genre", "scene_text", "beat_breakdown"}
                missing = required - cols
                if missing:
                    fail(f"Missing columns: {missing}  (found: {cols})")
                    return False
                ok(f"Schema OK  columns: {sorted(cols)}")

                # Sample fetch
                cursor.execute("SELECT genre, scene_text, beat_breakdown FROM few_shot_examples LIMIT 2")
                rows = cursor.fetchall()
                ok(f"Sample fetch: {len(rows)} row(s)")
                for row in rows:
                    genre, scene_text, beat_breakdown = row
                    beats = json.loads(beat_breakdown or "[]")
                    print(f"     genre={genre!r}  beats={len(beats)}  "
                          f"scene={scene_text[:50]!r}…")

        return True

    except Exception as e:
        fail(f"SQL connection failed: {type(e).__name__}: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 2. MLflow / Databricks tracking
# ─────────────────────────────────────────────────────────────────────────────
def test_mlflow():
    section("MLflow Tracking (Databricks)")
    try:
        import mlflow
    except ImportError:
        fail("mlflow not installed — run: pip install mlflow")
        return False

    host  = os.getenv("DATABRICKS_HOST", "")
    token = os.getenv("DATABRICKS_TOKEN", "")
    if not all([host, token]):
        fail("DATABRICKS_HOST / DATABRICKS_TOKEN not set")
        return False

    try:
        mlflow.set_tracking_uri("databricks")
        exp_name = os.getenv("DATABRICKS_MLFLOW_EXPERIMENT_NAME", "/playwright-runs")
        mlflow.set_experiment(exp_name)
        ok(f"Experiment set: {exp_name}")

        with mlflow.start_run() as run:
            mlflow.log_param("test_param", "ping")
            mlflow.log_metric("test_metric", 1.0)
            run_id = run.info.run_id

        ok(f"MLflow run logged  run_id={run_id}")
        return True

    except Exception as e:
        fail(f"MLflow error: {type(e).__name__}: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 3. get_few_shot_examples (service layer)
# ─────────────────────────────────────────────────────────────────────────────
def test_few_shot_service():
    section("get_few_shot_examples (service layer)")
    from services.databricks_service import get_few_shot_examples, _fetch_few_shot_from_databricks, _fetch_few_shot_from_csv

    # Direct Databricks fetch
    rows = _fetch_few_shot_from_databricks(limit=2)
    if rows:
        ok(f"_fetch_few_shot_from_databricks returned {len(rows)} row(s)")
        for r in rows:
            print(f"     genre={r['genre']!r}  beats={len(r['beats'])}  "
                  f"scene={r['scene'][:50]!r}…")
    else:
        fail("_fetch_few_shot_from_databricks returned None/empty")

    # CSV fallback
    csv_rows = _fetch_few_shot_from_csv(limit=2)
    if csv_rows:
        ok(f"_fetch_few_shot_from_csv returned {len(csv_rows)} row(s)")
    else:
        warn("CSV fallback returned no rows — check data/few_shot_examples.csv")

    # Combined service call
    examples = get_few_shot_examples(limit=2)
    if examples:
        ok(f"get_few_shot_examples returned {len(examples)} example(s)")
        source = "Databricks" if rows else "CSV"
        ok(f"Source: {source}")
        return True
    else:
        fail("get_few_shot_examples returned empty list")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 4. Full decompose_scene pipeline
# ─────────────────────────────────────────────────────────────────────────────
async def test_decompose_scene():
    section("decompose_scene (full pipeline)")
    from services.scene_decomposer import decompose_scene, close_client

    try:
        print(f"  Scene: {TEST_SCENE.strip()[:80]}…\n")
        t0 = time.time()
        result = await decompose_scene(TEST_SCENE)
        elapsed = time.time() - t0

        ok(f"decompose_scene completed in {elapsed:.2f}s")
        ok(f"run_id:          {result['run_id']}")
        ok(f"beats_extracted: {result['beats_extracted']}")
        ok(f"tokens_used:     {result['tokens_used']}")

        beats = result["beats"]
        sc    = result.get("scene_context", {})
        bible = result.get("character_bible", [])

        if sc:
            ok(f"scene_context:   genre={sc.get('genre')!r}  "
               f"visual_style={sc.get('visual_style')!r}")
        else:
            warn("scene_context is empty")

        if bible:
            ok(f"character_bible: {len(bible)} character(s)")
            for c in bible:
                print(f"     {c.get('name')}: {c.get('description','')[:80]}…")
        else:
            warn("character_bible is empty")

        print()
        for beat in beats:
            print(f"  Beat {beat.get('beat_number')} | {beat.get('camera_angle')} | "
                  f"{beat.get('mood')} | {beat.get('lighting','')[:40]}")
            print(f"    Visual:   {beat.get('visual_description','')[:90]}…")
            print(f"    Narrator: \"{beat.get('narrator_line','')[:70]}\"")
            print()

        print("Full beats JSON:")
        print(json.dumps(beats, indent=2))

        return True

    except Exception as e:
        import traceback
        fail(f"decompose_scene raised: {type(e).__name__}: {e}")
        traceback.print_exc()
        return False
    finally:
        await close_client()


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────
async def main():
    print(f"\n{BOLD}PLAYWRIGHT — Databricks + Scene Decomposer Tests{RESET}")
    print("=" * 55)

    results = {}
    results["databricks_sql"] = test_databricks_sql()
    results["mlflow"]         = test_mlflow()
    results["few_shot"]       = test_few_shot_service()
    results["decompose"]      = await test_decompose_scene()

    section("Summary")
    all_passed = True
    for name, passed in results.items():
        if passed:
            ok(name)
        else:
            fail(name)
            all_passed = False

    print()
    if all_passed:
        print(f"{GREEN}{BOLD}All tests passed.{RESET}\n")
    else:
        print(f"{RED}{BOLD}Some tests failed — see output above.{RESET}\n")
        sys.exit(1)


asyncio.run(main())
