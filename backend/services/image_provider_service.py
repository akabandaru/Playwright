import asyncio
import base64
import logging
import os
import random
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx

from services.image_provider_models import (
    GeneratedBeatImage,
    ImageProviderBeatPayload,
    ImageProviderErrorResponse,
    ImageProviderGenerateResponse,
)


logger = logging.getLogger(__name__)

DEFAULT_WIDTH = 832
DEFAULT_HEIGHT = 464
DEFAULT_STEPS = 8
DEFAULT_GUIDANCE_SCALE = 3.0

DEFAULT_HEALTH_TIMEOUT_SECONDS = 20.0
DEFAULT_GENERATE_TIMEOUT_SECONDS = 300.0
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF_SECONDS = 0.75


class ImageProviderClientError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _normalize_base_url(url: str) -> str:
    return (url or "").strip().rstrip("/")


def _provider_base_url() -> str:
    value = _normalize_base_url(os.getenv("IMAGE_PROVIDER_URL", ""))
    if not value:
        raise ImageProviderClientError(
            "IMAGE_PROVIDER_URL is not configured.",
            status_code=500,
        )
    return value


def _provider_host() -> str:
    return urlparse(_provider_base_url()).netloc


def _to_multiple_of_16(value: Optional[int], default: int) -> int:
    source = default if value is None else max(16, int(value))
    return max(16, int(round(source / 16.0) * 16))


def random_seed() -> int:
    return random.randint(1, 2_147_483_647)


def normalize_beat_payload(beat: ImageProviderBeatPayload) -> Dict[str, Any]:
    width = _to_multiple_of_16(beat.width, DEFAULT_WIDTH)
    height = _to_multiple_of_16(beat.height, DEFAULT_HEIGHT)

    payload = beat.model_dump(exclude_none=True)
    payload["width"] = width
    payload["height"] = height
    payload["steps"] = int(payload.get("steps", DEFAULT_STEPS))
    payload["guidance_scale"] = float(payload.get("guidance_scale", DEFAULT_GUIDANCE_SCALE))

    if payload.get("seed") is None:
        payload.pop("seed", None)

    return payload


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        parsed = ImageProviderErrorResponse.model_validate(response.json())
        if parsed.detail is not None:
            return str(parsed.detail)
    except Exception:
        pass

    text = response.text.strip()
    if text:
        return text
    return f"Provider request failed with status {response.status_code}."


def _is_retryable_status(code: int) -> bool:
    return code in {502, 503, 504}


def _is_retryable_request_error(exc: Exception) -> bool:
    return isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError))


async def _request_with_retry(
    method: str,
    path: str,
    *,
    json_body: Optional[Dict[str, Any]] = None,
    timeout_seconds: float,
    retries: int = DEFAULT_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
) -> httpx.Response:
    base_url = _provider_base_url()
    url = f"{base_url}/{path.lstrip('/')}"

    last_error: Optional[Exception] = None

    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.request(method, url, json=json_body)

            if _is_retryable_status(response.status_code) and attempt < retries:
                await asyncio.sleep(backoff_seconds * (2 ** attempt))
                continue

            return response

        except Exception as exc:
            last_error = exc
            if _is_retryable_request_error(exc) and attempt < retries:
                await asyncio.sleep(backoff_seconds * (2 ** attempt))
                continue
            break

    host = _provider_host()
    if last_error is not None:
        raise ImageProviderClientError(
            f"Image provider unreachable (host={host}). Tunnel may be down or not ready yet. {last_error}",
            status_code=503,
        ) from last_error

    raise ImageProviderClientError(
        f"Image provider request failed (host={host}).",
        status_code=503,
    )


async def check_image_provider_health() -> Dict[str, Any]:
    timeout = float(os.getenv("IMAGE_PROVIDER_HEALTH_TIMEOUT_SECONDS", DEFAULT_HEALTH_TIMEOUT_SECONDS))
    host = _provider_host()

    try:
        response = await _request_with_retry(
            "GET",
            "/health",
            timeout_seconds=timeout,
            retries=1,
            backoff_seconds=0.5,
        )
    except ImageProviderClientError as exc:
        logger.warning("Image provider health unreachable host=%s detail=%s", host, str(exc))
        raise

    if response.status_code >= 400:
        detail = _extract_error_detail(response)
        logger.warning(
            "Image provider health failed host=%s status=%s detail=%s",
            host,
            response.status_code,
            detail,
        )
        raise ImageProviderClientError(
            f"Image provider health check failed: {detail}",
            status_code=502,
        )

    data: Dict[str, Any]
    try:
        data = response.json()
    except Exception:
        data = {"raw": response.text}

    data["provider_host"] = host
    return data


async def generate_beat_image(beat: ImageProviderBeatPayload) -> GeneratedBeatImage:
    payload = normalize_beat_payload(beat)
    host = _provider_host()
    timeout = float(os.getenv("IMAGE_PROVIDER_GENERATE_TIMEOUT_SECONDS", DEFAULT_GENERATE_TIMEOUT_SECONDS))

    logger.info(
        "Image provider request host=%s beat=%s width=%s height=%s seed=%s",
        host,
        payload.get("beat_number"),
        payload.get("width"),
        payload.get("height"),
        payload.get("seed"),
    )

    response = await _request_with_retry(
        "POST",
        "/generate",
        json_body=payload,
        timeout_seconds=timeout,
    )

    if response.status_code >= 400:
        detail = _extract_error_detail(response)
        logger.error(
            "Image provider generate failed host=%s status=%s detail=%s",
            host,
            response.status_code,
            detail,
        )
        raise ImageProviderClientError(
            f"Image provider error: {detail}",
            status_code=502 if response.status_code >= 500 else response.status_code,
        )

    try:
        parsed = ImageProviderGenerateResponse.model_validate(response.json())
    except Exception as exc:
        raise ImageProviderClientError(
            "Image provider returned an unexpected response format.",
            status_code=502,
        ) from exc

    if not parsed.image_b64:
        raise ImageProviderClientError(
            "Image provider response missing image_b64.",
            status_code=502,
        )

    try:
        image_bytes = base64.b64decode(parsed.image_b64, validate=True)
    except Exception as exc:
        raise ImageProviderClientError(
            "Image provider returned invalid base64 image data.",
            status_code=502,
        ) from exc

    prompt_used = (parsed.prompt_used or "")
    prompt_short = (prompt_used[:180] + "...") if len(prompt_used) > 180 else prompt_used

    logger.info(
        "Image provider success host=%s request_id=%s seed=%s seconds=%s prompt=%s",
        host,
        parsed.request_id,
        parsed.seed_used,
        parsed.seconds,
        prompt_short,
    )

    return GeneratedBeatImage(
        metadata=parsed.model_dump(exclude_none=True),
        image_bytes=image_bytes,
        image_b64=parsed.image_b64,
    )


def save_generated_image(image_bytes: bytes, filename_hint: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in filename_hint)
    filename = f"{safe_name}.png"
    file_path = output_dir / filename
    file_path.write_bytes(image_bytes)
    return file_path
