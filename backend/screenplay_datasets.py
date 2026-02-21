"""
screenplay_datasets.py

Downloads and prepares two screenplay/dialogue datasets for use with the
Playwright pipeline and Databricks MLflow logging:

  1. IMSDB Scripts  — mattismegevand/IMSDb on Hugging Face
     ~1,000 full movie scripts with title, writers, genres, ratings, and
     full script text.

  2. Cornell Movie-Dialogs Corpus — cornell-movie-dialog/cornell_movie_dialog
     on Hugging Face.  220 k+ conversational exchanges from 617 movies,
     including character metadata and IMDB ratings.

Usage
-----
    python datasets.py                  # download both, save to ./data/
    python datasets.py --dataset imsdb  # only IMSDB
    python datasets.py --dataset cornell

The saved files are:
    data/imsdb_scripts.jsonl
    data/cornell_dialogs.jsonl

Each line is a JSON object so the files can be streamed line-by-line without
loading everything into memory.
"""

import argparse
import json
import os
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


# ---------------------------------------------------------------------------
# IMSDB
# ---------------------------------------------------------------------------

def download_imsdb(output_path: Path) -> int:
    """
    Download the pre-scraped IMSDB dataset (data.jsonl) from the
    Hugging Face Hub (mattismegevand/IMSDb).  The file is stored in Git LFS
    so we use the HF Hub resolve URL which handles LFS transparently.
    Each record contains:
        title, writers, genres, script_date, movie_date,
        imsdb_rating, user_rating, script (full text), poster_url
    Returns the number of records written.
    """
    import requests as _requests

    HF_LFS_URL = (
        "https://huggingface.co/datasets/mattismegevand/IMSDb/"
        "resolve/main/data.jsonl"
    )

    print("Downloading IMSDB Scripts from Hugging Face Hub …")
    with _requests.get(HF_LFS_URL, timeout=300, stream=True) as response:
        response.raise_for_status()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        buffer = b""
        with output_path.open("w", encoding="utf-8") as fh:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                buffer += chunk
                lines = buffer.split(b"\n")
                buffer = lines[-1]
                for line in lines[:-1]:
                    line = line.strip()
                    if not line:
                        continue
                    fh.write(line.decode("utf-8", errors="replace") + "\n")
                    count += 1
            if buffer.strip():
                fh.write(buffer.strip().decode("utf-8", errors="replace") + "\n")
                count += 1

    print(f"  Saved {count:,} IMSDB scripts → {output_path}")
    return count


# ---------------------------------------------------------------------------
# Cornell Movie-Dialogs Corpus
# ---------------------------------------------------------------------------

def download_cornell(output_path: Path) -> int:
    """
    Pull the Cornell Movie-Dialogs Corpus from the spawn99/CornellMovieDialogCorpus
    Hugging Face dataset (Parquet-based, no legacy loading script required).
    Each record contains utterance lines with character and movie metadata.
    Returns the number of records written.
    """
    try:
        from datasets import load_dataset  # type: ignore
    except ImportError:
        raise ImportError(
            "The 'datasets' package is required.  "
            "Install it with:  pip install datasets"
        )

    print("Downloading Cornell Movie-Dialogs Corpus from Hugging Face …")
    ds = load_dataset("spawn99/CornellMovieDialogCorpus", split="movie_lines")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w", encoding="utf-8") as fh:
        for record in ds:
            clean = {
                k: v for k, v in record.items()
                if isinstance(v, (str, int, float, bool, list, dict, type(None)))
            }
            fh.write(json.dumps(clean, ensure_ascii=False) + "\n")
            count += 1

    print(f"  Saved {count:,} Cornell dialog lines → {output_path}")
    return count


# ---------------------------------------------------------------------------
# Helpers for the rest of the app
# ---------------------------------------------------------------------------

def load_imsdb(limit: int = 0):
    """
    Lazy generator that yields IMSDB script dicts from the local JSONL file.
    Downloads the file first if it doesn't exist.
    Pass limit > 0 to cap the number of records returned.
    """
    path = DATA_DIR / "imsdb_scripts.jsonl"
    if not path.exists():
        download_imsdb(path)
    with path.open("r", encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if limit and i >= limit:
                break
            yield json.loads(line)


def load_cornell(limit: int = 0):
    """
    Lazy generator that yields Cornell dialog dicts from the local JSONL file.
    Downloads the file first if it doesn't exist.
    Pass limit > 0 to cap the number of records returned.
    """
    path = DATA_DIR / "cornell_dialogs.jsonl"
    if not path.exists():
        download_cornell(path)
    with path.open("r", encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if limit and i >= limit:
                break
            yield json.loads(line)


def sample_scripts(n: int = 10):
    """Return a list of n IMSDB script dicts (title + first 500 chars of text)."""
    results = []
    for record in load_imsdb(limit=n):
        results.append(
            {
                "title": record.get("title", ""),
                "genres": record.get("genres", []),
                "writers": record.get("writers", []),
                "preview": (record.get("script", "") or "")[:500],
            }
        )
    return results


def sample_dialogs(n: int = 10):
    """Return a list of n Cornell conversation dicts."""
    results = []
    for record in load_cornell(limit=n):
        results.append(record)
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Download screenplay datasets for Playwright"
    )
    parser.add_argument(
        "--dataset",
        choices=["imsdb", "cornell", "both"],
        default="both",
        help="Which dataset to download (default: both)",
    )
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if args.dataset in ("imsdb", "both"):
        download_imsdb(DATA_DIR / "imsdb_scripts.jsonl")

    if args.dataset in ("cornell", "both"):
        download_cornell(DATA_DIR / "cornell_dialogs.jsonl")

    print("\nDone.  Files are in:", DATA_DIR.resolve())


if __name__ == "__main__":
    main()
