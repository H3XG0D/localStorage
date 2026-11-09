"""Проверка содержимого загруженных чеков (magic bytes)."""
from pathlib import Path

PDF_MAGIC = b"%PDF"
VIDEO_FTYP = b"ftyp"


def file_starts_with(path: Path, magic: bytes) -> bool:
    try:
        with path.open("rb") as fh:
            head = fh.read(max(len(magic), 12))
    except OSError:
        return False
    return head.startswith(magic)


def is_valid_pdf_file(path: Path) -> bool:
    return file_starts_with(path, PDF_MAGIC)


def is_valid_video_file(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            head = fh.read(12)
    except OSError:
        return False
    if len(head) < 8:
        return False
    return head[4:8] == VIDEO_FTYP
