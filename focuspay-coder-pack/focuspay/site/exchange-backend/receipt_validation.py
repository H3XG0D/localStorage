"""Проверка magic bytes загруженных чеков."""
from pathlib import Path

PDF_MAGIC = b"%PDF"
VIDEO_FTYP = b"ftyp"
EBML_MAGIC = b"\x1a\x45\xdf\xa3"
RIFF_MAGIC = b"RIFF"
AVI_MAGIC = b"AVI "
VIDEO_HEADER_BYTES = 4096

ALLOWED_VIDEO_EXTENSIONS = frozenset({"mp4", "mov", "avi", "webm", "mkv"})
MAX_RECEIPT_PDF_BYTES = 5 * 1024 * 1024
MAX_RECEIPT_VIDEO_BYTES = 20 * 1024 * 1024


def is_valid_pdf_bytes(content: bytes) -> bool:
    return len(content) >= 4 and content[:4] == PDF_MAGIC


def is_valid_video_bytes(content: bytes) -> bool:
    head = content[:VIDEO_HEADER_BYTES]
    if len(head) >= 8 and head[4:8] == VIDEO_FTYP:
        return True
    if head.startswith(EBML_MAGIC):
        lowered = head.lower()
        return b"webm" in lowered or b"matroska" in lowered
    return len(head) >= 12 and head[:4] == RIFF_MAGIC and head[8:12] == AVI_MAGIC


def is_valid_pdf_file(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            head = fh.read(4)
    except OSError:
        return False
    return head == PDF_MAGIC


def is_valid_video_file(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            head = fh.read(VIDEO_HEADER_BYTES)
    except OSError:
        return False
    return is_valid_video_bytes(head)

