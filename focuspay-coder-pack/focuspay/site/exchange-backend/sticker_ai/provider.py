"""Image model provider abstraction — no mandatory vendor, no secrets in code."""
from __future__ import annotations

import hashlib
import struct
import zlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from sticker_ai.brand_preset import BrandPreset, DEFAULT_BRAND, build_generation_prompt
from sticker_ai.limits import DEFAULT_LIMITS, StickerLimits
from sticker_ai.redaction import sanitize_prompt
from sticker_ai.schemas import parse_edit_response, parse_generate_response


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class GenerateRequest:
    idea: str
    tenant_id: str
    task_id: str
    n_variants: int = 2
    brand: BrandPreset = DEFAULT_BRAND
    reference_asset_key: str | None = None


@dataclass(frozen=True)
class EditRequest:
    prompt: str
    tenant_id: str
    task_id: str
    source_asset_key: str
    mask_asset_key: str | None = None
    brand: BrandPreset = DEFAULT_BRAND


class ImageProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    async def generate(self, req: GenerateRequest) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def edit(self, req: EditRequest) -> dict[str, Any]:
        raise NotImplementedError


class NullProvider(ImageProvider):
    """Fail closed when no worker is configured."""

    name = "null"

    async def generate(self, req: GenerateRequest) -> dict[str, Any]:
        raise ProviderError("sticker_ai_provider_not_configured")

    async def edit(self, req: EditRequest) -> dict[str, Any]:
        raise ProviderError("sticker_ai_provider_not_configured")


def _png_bytes(width: int, height: int, rgba: tuple[int, int, int, int]) -> bytes:
    """Minimal PNG encoder (no Pillow dependency) for offline mock assets."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(rgba) * width for _ in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


class OfflineMockProvider(ImageProvider):
    """Deterministic placeholder PNGs for tests/CI — no model weights."""

    name = "offline_mock"

    def __init__(self, *, limits: StickerLimits = DEFAULT_LIMITS) -> None:
        self.limits = limits

    async def generate(self, req: GenerateRequest) -> dict[str, Any]:
        idea, _ = sanitize_prompt(req.idea, max_len=self.limits.max_idea_chars)
        _ = build_generation_prompt(idea, brand=req.brand)
        n = max(1, min(int(req.n_variants), self.limits.max_variants))
        variants = []
        for i in range(n):
            seed = int(hashlib.sha256(f"{req.task_id}:{idea}:{i}".encode()).hexdigest()[:8], 16)
            key = f"{req.tenant_id}/{req.task_id}/v0/var_{i}.png"
            variants.append(
                {
                    "asset_key": key,
                    "width": req.brand.canvas_px,
                    "height": req.brand.canvas_px,
                    "seed": seed,
                    "_bytes": _png_bytes(64, 64, (20, 20, 22, 255)),
                }
            )
        raw = {"model_id": self.name, "variants": [{k: v for k, v in x.items() if k != "_bytes"} for x in variants]}
        parsed = parse_generate_response(raw, max_variants=self.limits.max_variants)
        parsed["_assets"] = {v["asset_key"]: variants[i]["_bytes"] for i, v in enumerate(parsed["variants"])}
        return parsed

    async def edit(self, req: EditRequest) -> dict[str, Any]:
        prompt, _ = sanitize_prompt(req.prompt, max_len=self.limits.max_prompt_chars)
        digest = hashlib.sha256(f"{req.source_asset_key}:{prompt}".encode()).hexdigest()[:12]
        key = f"{req.tenant_id}/{req.task_id}/edit_{digest}.png"
        raw = {
            "model_id": self.name,
            "asset_key": key,
            "width": req.brand.canvas_px,
            "height": req.brand.canvas_px,
        }
        parsed = parse_edit_response(raw)
        parsed["_assets"] = {key: _png_bytes(64, 64, (30, 30, 34, 255))}
        return parsed


class HttpWorkerProvider(ImageProvider):
    """Stub for a future isolated GPU worker. Secrets must come from env/secret manager."""

    name = "http_worker"

    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        limits: StickerLimits = DEFAULT_LIMITS,
        session_factory: Any = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self._api_token = api_token or ""
        self.limits = limits
        self._session_factory = session_factory
        if not self.base_url:
            raise ProviderError("worker_base_url_required")
        if not self._api_token:
            raise ProviderError("worker_token_required")

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        import aiohttp

        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=self.limits.provider_timeout_sec)
        factory = self._session_factory or aiohttp.ClientSession
        async with factory(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                raw = await resp.read()
                if len(raw) > self.limits.max_response_bytes:
                    raise ProviderError("response_too_large")
                if resp.status >= 400:
                    raise ProviderError(f"worker_http_{resp.status}")
                import json

                try:
                    data = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as e:
                    raise ProviderError("worker_invalid_json") from e
                if not isinstance(data, dict):
                    raise ProviderError("worker_json_not_object")
                return data

    async def generate(self, req: GenerateRequest) -> dict[str, Any]:
        idea, _ = sanitize_prompt(req.idea, max_len=self.limits.max_idea_chars)
        prompt = build_generation_prompt(idea, brand=req.brand)
        prompt, _ = sanitize_prompt(prompt)
        data = await self._post(
            "/v1/generate",
            {
                "prompt": prompt,
                "negative_prompt": req.brand.negative_prompt,
                "n": max(1, min(req.n_variants, self.limits.max_variants)),
                "size": req.brand.canvas_px,
                "task_id": req.task_id,
                "reference_asset_key": req.reference_asset_key,
            },
        )
        return parse_generate_response(data, max_variants=self.limits.max_variants)

    async def edit(self, req: EditRequest) -> dict[str, Any]:
        prompt, _ = sanitize_prompt(req.prompt, max_len=self.limits.max_prompt_chars)
        data = await self._post(
            "/v1/edit",
            {
                "prompt": prompt,
                "negative_prompt": req.brand.negative_prompt,
                "source_asset_key": req.source_asset_key,
                "mask_asset_key": req.mask_asset_key,
                "task_id": req.task_id,
            },
        )
        return parse_edit_response(data)


class LelouchImageProvider(ImageProvider):
    """OpenAI-compatible /images/generations via existing Lelouch gateway.

    Credentials come from env/secret manager at runtime. Never log the token.
    """

    name = "lelouch"

    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        model: str = "gpt-image-2",
        limits: StickerLimits = DEFAULT_LIMITS,
        session_factory: Any = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self._api_token = api_token or ""
        self.model = (model or "gpt-image-2").strip() or "gpt-image-2"
        self.limits = limits
        self._session_factory = session_factory
        if not self.base_url:
            raise ProviderError("lelouch_base_url_required")
        if not self._api_token:
            raise ProviderError("lelouch_token_required")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 FocusPayStickerAI/1.0",
            "HTTP-Referer": "https://focuspay.org",
            "X-Title": "FocusPay Sticker AI",
        }

    async def _post_image(self, prompt: str) -> bytes:
        import base64
        import json

        import aiohttp

        from image_validation import detect_image_content_type

        url = f"{self.base_url}/images/generations"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "n": 1,
            "size": "512x512",
            "response_format": "b64_json",
        }
        timeout = aiohttp.ClientTimeout(total=self.limits.provider_timeout_sec)
        factory = self._session_factory or aiohttp.ClientSession
        async with factory(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=self._headers()) as resp:
                raw = await resp.read()
                if len(raw) > self.limits.max_response_bytes:
                    raise ProviderError("response_too_large")
                if resp.status >= 400:
                    raise ProviderError(f"lelouch_http_{resp.status}")
                try:
                    data = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as e:
                    raise ProviderError("lelouch_invalid_json") from e
                items = data.get("data") if isinstance(data, dict) else None
                if not isinstance(items, list) or not items or not isinstance(items[0], dict):
                    raise ProviderError("lelouch_empty_image")
                b64 = items[0].get("b64_json")
                if not isinstance(b64, str) or not b64.strip():
                    raise ProviderError("lelouch_missing_b64")
                try:
                    blob = base64.b64decode(b64, validate=False)
                except Exception as e:
                    raise ProviderError("lelouch_bad_b64") from e
                if not detect_image_content_type(blob):
                    raise ProviderError("lelouch_not_image")
                return blob

    async def generate(self, req: GenerateRequest) -> dict[str, Any]:
        from image_validation import detect_image_content_type

        idea, _ = sanitize_prompt(req.idea, max_len=self.limits.max_idea_chars)
        prompt, _ = sanitize_prompt(build_generation_prompt(idea, brand=req.brand))
        n = max(1, min(int(req.n_variants), self.limits.max_variants))
        variants: list[dict[str, Any]] = []
        assets: dict[str, bytes] = {}
        for i in range(n):
            blob = await self._post_image(prompt)
            ctype = detect_image_content_type(blob) or "image/png"
            ext = "jpg" if ctype == "image/jpeg" else "webp" if ctype == "image/webp" else "png"
            key = f"{req.tenant_id}/{req.task_id}/v0/var_{i}.{ext}"
            variants.append(
                {
                    "asset_key": key,
                    "width": req.brand.canvas_px,
                    "height": req.brand.canvas_px,
                    "seed": None,
                }
            )
            assets[key] = blob
        parsed = parse_generate_response(
            {"model_id": f"lelouch:{self.model}", "variants": variants},
            max_variants=self.limits.max_variants,
        )
        parsed["_assets"] = assets
        return parsed

    async def edit(self, req: EditRequest) -> dict[str, Any]:
        from image_validation import detect_image_content_type

        prompt, _ = sanitize_prompt(req.prompt, max_len=self.limits.max_prompt_chars)
        full, _ = sanitize_prompt(
            f"{req.brand.style_prompt}. Revise existing FocusPay sticker. Change: {prompt}."
        )
        blob = await self._post_image(full)
        ctype = detect_image_content_type(blob) or "image/png"
        ext = "jpg" if ctype == "image/jpeg" else "webp" if ctype == "image/webp" else "png"
        digest = hashlib.sha256(f"{req.source_asset_key}:{prompt}".encode()).hexdigest()[:12]
        key = f"{req.tenant_id}/{req.task_id}/edit_{digest}.{ext}"
        parsed = parse_edit_response(
            {
                "model_id": f"lelouch:{self.model}",
                "asset_key": key,
                "width": req.brand.canvas_px,
                "height": req.brand.canvas_px,
            }
        )
        parsed["_assets"] = {key: blob}
        return parsed


def build_provider(kind: str | None, **kwargs: Any) -> ImageProvider:
    k = (kind or "null").strip().lower()
    if k in ("null", "", "none"):
        return NullProvider()
    if k in ("offline", "offline_mock", "mock"):
        return OfflineMockProvider(limits=kwargs.get("limits", DEFAULT_LIMITS))
    if k in ("lelouch", "openai", "openai_images"):
        return LelouchImageProvider(
            base_url=str(kwargs.get("base_url") or ""),
            api_token=str(kwargs.get("api_token") or ""),
            model=str(kwargs.get("model") or "gpt-image-2"),
            limits=kwargs.get("limits", DEFAULT_LIMITS),
            session_factory=kwargs.get("session_factory"),
        )
    if k in ("http", "http_worker", "worker"):
        return HttpWorkerProvider(
            base_url=str(kwargs.get("base_url") or ""),
            api_token=str(kwargs.get("api_token") or ""),
            limits=kwargs.get("limits", DEFAULT_LIMITS),
            session_factory=kwargs.get("session_factory"),
        )
    raise ProviderError(f"unknown_provider:{k}")
