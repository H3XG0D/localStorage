"""Asset storage with quarantine (in-memory for MVP tests)."""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Protocol

from image_validation import detect_image_content_type
from sticker_ai.constants import QUARANTINE_PREFIX, STORAGE_PREFIX
from sticker_ai.limits import DEFAULT_LIMITS, StickerLimits, validate_image_size

logger = logging.getLogger("sticker_ai.storage")


class StorageError(RuntimeError):
    pass


class AssetStore(Protocol):
    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> str: ...
    def get(self, key: str) -> bytes | None: ...
    def quarantine(self, data: bytes, *, reason: str) -> str: ...


@dataclass
class InMemoryAssetStore:
    limits: StickerLimits = DEFAULT_LIMITS
    tenant_id: str = "focuspay"
    _objects: dict[str, bytes] = field(default_factory=dict)
    _meta: dict[str, dict] = field(default_factory=dict)

    def _reject_unsafe_key(self, key: str) -> None:
        k = key or ""
        if not k.strip():
            raise StorageError("empty_key")
        if ".." in k or k.startswith("/") or "\\" in k or "\x00" in k:
            raise StorageError("unsafe_key")
        if any(part == ".." for part in k.replace("\\", "/").split("/")):
            raise StorageError("unsafe_key")

    def _full_key(self, key: str) -> str:
        self._reject_unsafe_key(key)
        k = (key or "").lstrip("/")
        if k.startswith(STORAGE_PREFIX + "/") or k.startswith(QUARANTINE_PREFIX):
            # Enforce tenant segment when present: sticker_ai/{tenant}/...
            parts = k.split("/")
            if len(parts) >= 2 and parts[0] == STORAGE_PREFIX and parts[1] != "_quarantine":
                if parts[1] != self.tenant_id:
                    raise StorageError("tenant_mismatch")
            return k
        return f"{STORAGE_PREFIX}/{self.tenant_id}/{k}"

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        self._reject_unsafe_key(key)
        validate_image_size(data, limits=self.limits)
        detected = detect_image_content_type(data)
        if not detected:
            q = self.quarantine(data, reason="bad_magic")
            # Never log blob contents — only reason + quarantine key suffix.
            logger.info("sticker_asset_quarantined reason=bad_magic key_suffix=%s", q[-16:])
            raise StorageError(f"quarantined:{q}")
        full = self._full_key(key)
        self._objects[full] = data
        self._meta[full] = {
            "content_type": detected,
            "declared": content_type,
            "tenant_id": self.tenant_id,
            "size": len(data),
        }
        return full

    def get(self, key: str) -> bytes | None:
        try:
            return self._objects.get(self._full_key(key))
        except StorageError:
            return None

    def has(self, key: str) -> bool:
        try:
            return self._full_key(key) in self._objects
        except StorageError:
            return False

    def meta(self, key: str) -> dict | None:
        try:
            return self._meta.get(self._full_key(key))
        except StorageError:
            return None

    def quarantine(self, data: bytes, *, reason: str) -> str:
        digest = hashlib.sha256(data or b"").hexdigest()
        key = f"{QUARANTINE_PREFIX}/{self.tenant_id}/{digest}"
        self._objects[key] = data
        self._meta[key] = {"reason": reason, "tenant_id": self.tenant_id}
        return key

    def keys_for_prefix(self, prefix: str) -> list[str]:
        """List keys under prefix (tests / isolation checks)."""
        try:
            full = self._full_key(prefix) if not prefix.startswith(STORAGE_PREFIX) else prefix
        except StorageError:
            return []
        return [k for k in self._objects if k.startswith(full)]
