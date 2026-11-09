import asyncio
import io
import os
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image
from pypdf import PdfReader, PdfWriter

from app.core.config import settings
from app.models import Doliv, Requisite

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

ALLOWED_MIME: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "application/pdf": ".pdf",
}

# Phone cameras often send these; we convert to JPEG before storage.
_CONVERTIBLE_IMAGE_MIME = frozenset({
    "image/heic",
    "image/heif",
    "image/webp",
    "image/heic-sequence",
})

_MAGIC: dict[str, bytes] = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "application/pdf": b"%PDF",
    "image/webp": b"RIFF",
}

_MAX_PDF_PAGES = 50
_MAX_IMAGE_PIXELS = 25_000_000

_INVALID_TYPE_MSG = (
    "Неподдерживаемый формат файла. Используйте JPG, PNG или PDF, "
    "либо сделайте скриншот чека и прикрепите его."
)


def _check_magic_bytes(content: bytes, mime: str) -> bool:
    magic = _MAGIC.get(mime)
    if magic is None:
        return mime in _CONVERTIBLE_IMAGE_MIME
    if mime == "image/webp":
        return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    return content[: len(magic)] == magic


_MIME_BY_FORMAT: dict[str, str] = {
    "JPG": "image/jpeg",
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "PDF": "application/pdf",
}


def _build_allowed_mime(formats: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for fmt in formats:
        mime = _MIME_BY_FORMAT.get(fmt.strip().upper())
        if mime and mime in ALLOWED_MIME:
            result[mime] = ALLOWED_MIME[mime]
    return result or ALLOWED_MIME


def _convert_image_to_jpeg(content: bytes) -> bytes:
    """Convert HEIC/WebP/other raster uploads from mobile cameras to JPEG."""
    try:
        Image.MAX_IMAGE_PIXELS = _MAX_IMAGE_PIXELS
        with Image.open(io.BytesIO(content)) as img:
            rgb = img.convert("RGB")
            out = io.BytesIO()
            rgb.save(out, format="JPEG", quality=92)
            return out.getvalue()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=_INVALID_TYPE_MSG) from exc


def validate_receipt_path(path: str) -> None:
    """Raise 403 if path escapes UPLOAD_DIR; raise 404 if file is missing."""
    upload_dir = Path(settings.UPLOAD_DIR).resolve()
    file_path = Path(path).resolve()
    try:
        file_path.relative_to(upload_dir)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")


def safe_file_response(path: str, filename: str | None = None) -> FileResponse:
    """Return FileResponse only for files that are inside UPLOAD_DIR."""
    validate_receipt_path(path)
    kwargs: dict = {"path": str(Path(path).resolve())}
    if filename:
        kwargs["filename"] = filename
    return FileResponse(**kwargs)


def safe_remove_receipt(path: str) -> None:
    """Remove a receipt file only if it is inside UPLOAD_DIR."""
    validate_receipt_path(path)
    try:
        os.remove(path)
    except OSError:
        pass


async def save_receipt(
    requisite_id: int,
    file: UploadFile,
    *,
    max_size_bytes: int | None = None,
    allowed_formats: list[str] | None = None,
) -> str:
    limit = max_size_bytes if max_size_bytes is not None else settings.MAX_UPLOAD_SIZE
    allowed = _build_allowed_mime(allowed_formats) if allowed_formats else ALLOWED_MIME

    content_type = (file.content_type or "").split(";")[0].strip().lower() or "application/octet-stream"
    content = await file.read()
    limit_mb = limit // (1024 * 1024)
    if len(content) > limit:
        raise HTTPException(status_code=400, detail=f"Файл слишком большой (макс. {limit_mb} МБ)")

    store_mime = content_type
    if content_type in _CONVERTIBLE_IMAGE_MIME:
        content = _convert_image_to_jpeg(content)
        store_mime = "image/jpeg"
    elif content_type not in allowed:
        fmt_names = ", ".join(sorted({v.lstrip(".").upper() for v in allowed.values()}))
        raise HTTPException(
            status_code=400,
            detail=f"{_INVALID_TYPE_MSG} Разрешены: {fmt_names}.",
        )
    elif not _check_magic_bytes(content, content_type):
        raise HTTPException(status_code=400, detail="Содержимое файла не соответствует заявленному типу")

    ext = allowed[store_mime]
    upload_dir = Path(settings.UPLOAD_DIR) / "receipts" / str(requisite_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid.uuid4()}{ext}"
    filepath = upload_dir / filename
    filepath.write_bytes(content)

    return str(filepath)


async def merge_receipts_to_pdf_async(requisite: Requisite, doliv: Doliv | None, output_path: str) -> str:
    """Async wrapper: runs the blocking PDF merge in a thread pool."""
    return await asyncio.to_thread(merge_receipts_to_pdf, requisite, doliv, output_path)


def merge_receipts_to_pdf(requisite: Requisite, doliv: Doliv | None, output_path: str) -> str:
    writer = PdfWriter()
    zalivs_sorted = sorted(requisite.zalivs, key=lambda z: z.created_at)
    paths: list[str] = [z.receipt_path for z in zalivs_sorted]
    if doliv:
        paths.append(doliv.receipt_path)

    upload_dir = Path(settings.UPLOAD_DIR).resolve()

    for path in paths:
        file_path = Path(path).resolve()
        try:
            file_path.relative_to(upload_dir)
        except ValueError:
            continue
        if not file_path.exists():
            continue
        tmp_pdf: str | None = None
        try:
            if str(file_path).lower().endswith(".pdf"):
                reader = PdfReader(str(file_path))
                if len(reader.pages) > _MAX_PDF_PAGES:
                    continue
                for page in reader.pages[:_MAX_PDF_PAGES]:
                    writer.add_page(page)
            else:
                Image.MAX_IMAGE_PIXELS = _MAX_IMAGE_PIXELS
                img = Image.open(str(file_path)).convert("RGB")
                tmp_pdf = str(file_path) + ".tmp.pdf"
                img.save(tmp_pdf, "PDF")
                reader = PdfReader(tmp_pdf)
                for page in reader.pages:
                    writer.add_page(page)
        except Exception:
            continue
        finally:
            if tmp_pdf and os.path.exists(tmp_pdf):
                os.remove(tmp_pdf)

    out_dir = Path(settings.UPLOAD_DIR) / "merged"
    out_dir.mkdir(parents=True, exist_ok=True)
    final_path = out_dir / f"requisite_{requisite.id}.pdf"
    with open(final_path, "wb") as f:
        writer.write(f)
    return str(final_path)
