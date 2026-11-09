"""Tests for file upload validation and path traversal guard."""
import io
import os
import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.services.files import _build_allowed_mime, validate_receipt_path


def _fake_jpg() -> bytes:
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xd9"
    )


# ──────────────────────────────────────────────────────────────────────────────
# _build_allowed_mime
# ──────────────────────────────────────────────────────────────────────────────

def test_build_allowed_mime_jpg_png():
    result = _build_allowed_mime(["JPG", "PNG"])
    assert "image/jpeg" in result
    assert "image/png" in result
    assert "application/pdf" not in result


def test_build_allowed_mime_unknown_falls_back():
    result = _build_allowed_mime(["XYZ"])
    assert result == {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf"}


def test_build_allowed_mime_all_formats():
    result = _build_allowed_mime(["JPG", "PNG", "PDF"])
    assert len(result) == 3


# ──────────────────────────────────────────────────────────────────────────────
# validate_receipt_path – path traversal guard
# ──────────────────────────────────────────────────────────────────────────────

def test_validate_path_inside_upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    valid_file = tmp_path / "receipts" / "1" / "file.jpg"
    valid_file.parent.mkdir(parents=True)
    valid_file.write_bytes(_fake_jpg())
    validate_receipt_path(str(valid_file))  # should not raise


def test_validate_path_outside_upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    outside = tmp_path.parent / "etc_passwd_simulation"
    outside.write_text("root:x:0:0")
    with pytest.raises(HTTPException) as exc:
        validate_receipt_path(str(outside))
    assert exc.value.status_code == 403


def test_validate_path_traversal_sequence(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    traversal = str(tmp_path / "receipts" / ".." / ".." / "etc" / "passwd")
    with pytest.raises(HTTPException) as exc:
        validate_receipt_path(traversal)
    assert exc.value.status_code in (403, 404)


def test_validate_path_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    missing = tmp_path / "receipts" / "99" / "nonexistent.jpg"
    with pytest.raises(HTTPException) as exc:
        validate_receipt_path(str(missing))
    assert exc.value.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# save_receipt integration
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_receipt_valid(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    from unittest.mock import AsyncMock, MagicMock
    from app.services.files import save_receipt

    file = MagicMock()
    file.content_type = "image/jpeg"
    file.read = AsyncMock(return_value=_fake_jpg())

    path = await save_receipt(42, file)
    assert Path(path).exists()
    assert "receipts/42" in path.replace("\\", "/")


@pytest.mark.asyncio
async def test_save_receipt_invalid_type(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    from unittest.mock import AsyncMock, MagicMock
    from app.services.files import save_receipt

    file = MagicMock()
    file.content_type = "application/zip"
    file.read = AsyncMock(return_value=b"PK...")

    with pytest.raises(HTTPException) as exc:
        await save_receipt(42, file)
    assert exc.value.status_code == 400
    assert "Invalid file type" in exc.value.detail or "формат" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_save_receipt_too_large(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    from unittest.mock import AsyncMock, MagicMock
    from app.services.files import save_receipt

    file = MagicMock()
    file.content_type = "image/jpeg"
    big_content = b"\xff\xd8" + b"\x00" * (2 * 1024 * 1024)
    file.read = AsyncMock(return_value=big_content)

    with pytest.raises(HTTPException) as exc:
        await save_receipt(42, file, max_size_bytes=1024 * 1024)
    assert exc.value.status_code == 400
    assert "too large" in exc.value.detail.lower() or "большой" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_save_receipt_respects_allowed_formats(tmp_path, monkeypatch):
    """When only PDF is allowed, jpeg upload must be rejected."""
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    from unittest.mock import AsyncMock, MagicMock
    from app.services.files import save_receipt

    file = MagicMock()
    file.content_type = "image/jpeg"
    file.read = AsyncMock(return_value=_fake_jpg())

    with pytest.raises(HTTPException) as exc:
        await save_receipt(42, file, allowed_formats=["PDF"])
    assert exc.value.status_code == 400


# ──────────────────────────────────────────────────────────────────────────────
# Magic bytes validation
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_receipt_rejects_spoofed_content_type(tmp_path, monkeypatch):
    """File with JPEG content-type but non-JPEG bytes must be rejected."""
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    from unittest.mock import AsyncMock, MagicMock
    from app.services.files import save_receipt

    file = MagicMock()
    file.content_type = "image/jpeg"
    file.read = AsyncMock(return_value=b"This is not a JPEG at all")

    with pytest.raises(HTTPException) as exc:
        await save_receipt(42, file)
    assert exc.value.status_code == 400
    assert "content does not match" in exc.value.detail.lower() or "не соответствует" in exc.value.detail.lower()


def test_magic_bytes_helper():
    from app.services.files import _check_magic_bytes

    assert _check_magic_bytes(_fake_jpg(), "image/jpeg") is True
    assert _check_magic_bytes(b"This is text", "image/jpeg") is False
    assert _check_magic_bytes(b"\x89PNG\r\n\x1a\nFAKE", "image/png") is True
    assert _check_magic_bytes(b"%PDFfake", "application/pdf") is True
    assert _check_magic_bytes(b"WRONG", "application/pdf") is False
