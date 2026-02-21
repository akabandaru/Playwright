import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

import httpx
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


def sample_beat(beat_number: int = 1) -> Dict[str, Any]:
    return {
        "beat_number": beat_number,
        "visual_description": "Massive, consuming flames lick across the screen, then slowly recede to reveal the iconic Bat-Symbol, dark and ominous, growing larger until it fills the frame and transitions to absolute blackness.",
        "camera_angle": "wide shot",
        "mood": "ominous",
        "lighting": "firelight",
        "characters_present": [],
        "narrator_line": "Some symbols are born in fire, forged in the very chaos they seek to quell. A promise. A warning.",
        "music_style": "dark, percussive, building crescendo",
        "width": 832,
        "height": 464,
        "steps": 8,
        "guidance_scale": 3.0,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def maybe_download_file(client: httpx.Client, api_base: str, file_url: str, output_path: Path) -> None:
    file_url = file_url.strip()
    if not file_url:
        return

    if file_url.startswith("http://") or file_url.startswith("https://"):
        url = file_url
    else:
        url = f"{api_base.rstrip('/')}/{file_url.lstrip('/')}"

    response = client.get(url)
    response.raise_for_status()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(response.content)


def test_generate_frame(api_base: str, timeout: float, save_response: Path, download_image: Path) -> None:
    payload = sample_beat()
    payload["return_base64"] = False
    payload["save_to_disk"] = True

    with httpx.Client(timeout=timeout) as client:
        response = client.post(f"{api_base.rstrip('/')}/api/generate-frame", json=payload)
        response.raise_for_status()
        data = response.json()

        write_json(save_response, data)
        print(f"Saved frame response JSON -> {save_response}")

        file_url = data.get("fileUrl")
        if file_url:
            maybe_download_file(client, api_base, file_url, download_image)
            print(f"Downloaded generated image -> {download_image}")
        else:
            print("No fileUrl in response; skipping image download.")


def test_generate_images_batch(api_base: str, timeout: float, save_response: Path) -> None:
    beats: List[Dict[str, Any]] = [sample_beat(1), sample_beat(2)]
    beats[1]["visual_description"] = "A storm-black sky splits with lightning as Gotham skyline appears under heavy rain, neon reflections shimmering on wet rooftops."

    payload = {"beats": beats}

    with httpx.Client(timeout=timeout) as client:
        response = client.post(f"{api_base.rstrip('/')}/api/generate-images", json=payload)
        response.raise_for_status()
        data = response.json()

    write_json(save_response, data)
    print(f"Saved batch response JSON -> {save_response}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test PLAYWRIGHT image generation backend endpoints.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000", help="Base URL for PLAYWRIGHT backend API")
    parser.add_argument("--timeout", type=float, default=360.0, help="Request timeout seconds")
    parser.add_argument(
        "--mode",
        choices=["frame", "batch"],
        default="frame",
        help="Test single-frame endpoint or batch endpoint",
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT_DIR / "backend" / "outputs" / "api_test"),
        help="Directory to store response files",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)

    try:
        if args.mode == "frame":
            test_generate_frame(
                api_base=args.api_base,
                timeout=args.timeout,
                save_response=output_dir / "generate_frame_response.json",
                download_image=output_dir / "generate_frame_image.png",
            )
        else:
            test_generate_images_batch(
                api_base=args.api_base,
                timeout=args.timeout,
                save_response=output_dir / "generate_images_response.json",
            )
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text if exc.response is not None else str(exc)
        print(f"HTTP error {exc.response.status_code if exc.response else 'unknown'}: {detail}")
        raise
    except Exception as exc:
        print(f"Request failed: {exc}")
        raise


if __name__ == "__main__":
    main()
