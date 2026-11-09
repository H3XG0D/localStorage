"""Хранение скриншотов Ops AI (не публичная раздача)."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from image_validation import validate_image_bytes

OPS_AI_UPLOAD_ROOT = Path(os.getenv("OPS_AI_UPLOAD_DIR", "/var/lib/focuspay/ops_ai"))
MAX_IMAGES = 3
MAX_BYTES = 4 * 1024 * 1024

_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def ensure_root() -> Path:
    OPS_AI_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    return OPS_AI_UPLOAD_ROOT


def save_images(session_id: int, files: list[tuple[bytes, str | None]]) -> list[dict]:
    """Сохраняет до MAX_IMAGES файлов. Возвращает meta [{path, content_type, size, name}]."""
    ensure_root()
    out: list[dict] = []
    dest_dir = OPS_AI_UPLOAD_ROOT / str(int(session_id))
    dest_dir.mkdir(parents=True, exist_ok=True)
    for raw, declared in files[:MAX_IMAGES]:
        if not raw:
            continue
        if len(raw) > MAX_BYTES:
            raise ValueError(f"Файл больше {MAX_BYTES // (1024 * 1024)} МБ")
        ctype = validate_image_bytes(raw, declared)
        ext = _EXT.get(ctype, ".bin")
        name = f"{uuid.uuid4().hex}{ext}"
        path = dest_dir / name
        path.write_bytes(raw)
        out.append(
            {
                "path": str(path),
                "rel": f"{int(session_id)}/{name}",
                "content_type": ctype,
                "size": len(raw),
                "name": name,
            }
        )
    return out


def read_attachment(meta: dict) -> tuple[Path, str]:
    path = Path(str(meta.get("path") or ""))
    root = OPS_AI_UPLOAD_ROOT.resolve()
    try:
        resolved = path.resolve()
    except OSError as e:
        raise FileNotFoundError(str(e)) from e
    if root not in resolved.parents and resolved != root:
        # allow file directly under root/session/
        if not str(resolved).startswith(str(root) + os.sep):
            raise FileNotFoundError("invalid path")
    if not resolved.is_file():
        raise FileNotFoundError("missing")
    ctype = str(meta.get("content_type") or "application/octet-stream")
    return resolved, ctype


def to_data_url(path: Path, content_type: str) -> str:
    import base64

    raw = path.read_bytes()
    b64 = base64.standard_b64encode(raw).decode("ascii")
    return f"data:{content_type};base64,{b64}"
