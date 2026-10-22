"""Thin async client for Clef-omni (Cloudflare Workers AI or a self-hosted SystemOne endpoint).

Clef-omni is a decision model: it takes a `state`, optional `images`, and a schema of typed
`questions`, and returns a calibrated probability per option. No text generation.
"""
from __future__ import annotations

import base64
import io
from typing import Any

import httpx
from PIL import Image

from .config import settings


class ClefError(RuntimeError):
    pass


def image_to_data_url(raw: bytes, max_side: int | None = None) -> str:
    """Normalize any image to a downscaled JPEG data URL. Keeps latency and payload predictable."""
    max_side = max_side or settings.max_image_side_px
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as exc:  # noqa: BLE001
        raise ClefError("Unreadable image file. Please upload a valid PNG, JPEG or WebP.") from exc
    img = img.convert("RGB")
    w, h = img.size
    scale = min(1.0, max_side / max(w, h))
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    # JPEG: fast to encode and ~20x smaller than PNG on noisy photos; q=90 keeps small text crisp.
    img.save(buf, format="JPEG", quality=90, optimize=False)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


class ClefClient:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "ClefClient":
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=settings.request_timeout_s)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def decide(
        self,
        state: dict[str, Any] | str,
        questions: dict[str, dict[str, Any]],
        images: list[str] | None = None,
        instructions: str | None = None,
    ) -> dict[str, Any]:
        """Return the `answers` mapping keyed by question id."""
        if not settings.clef_base_url and not (
            settings.cloudflare_account_id and settings.cloudflare_api_token
        ):
            raise ClefError("Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN, or CLEF_BASE_URL.")
        assert self._client is not None, "use `async with ClefClient()`"

        body: dict[str, Any] = {"model": "clef-omni", "state": state, "questions": questions}
        if images:
            body["images"] = images
        if instructions:
            body["instructions"] = instructions

        headers = {"Content-Type": "application/json"}
        if not settings.clef_base_url:
            headers["Authorization"] = f"Bearer {settings.cloudflare_api_token}"

        try:
            resp = await self._client.post(settings.endpoint, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise ClefError(f"Network error reaching Clef: {exc}") from exc
        if resp.status_code >= 400:
            raise ClefError(f"Clef HTTP {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        # Workers AI wraps the payload in {"result": ..., "success": ...}; self-host returns it bare.
        payload = data.get("result", data)
        answers = payload.get("answers")
        if not isinstance(answers, dict):
            raise ClefError(f"Unexpected Clef response shape: {str(payload)[:300]}")
        return answers
