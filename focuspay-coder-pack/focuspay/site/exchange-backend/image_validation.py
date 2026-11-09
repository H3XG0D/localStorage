"""Magic-byte проверка изображений."""
from fastapi import HTTPException

_MAGIC = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),
)


def detect_image_content_type(content: bytes) -> str | None:
    if len(content) < 12:
        return None
    if content[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if content[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_image_bytes(content: bytes, declared_type: str | None) -> str:
    """Returns normalized content-type or raises HTTPException."""
    detected = detect_image_content_type(content)
    if not detected:
        raise HTTPException(status_code=400, detail="Файл не является допустимым изображением")
    declared = (declared_type or "").split(";")[0].strip().lower()
    if declared and declared not in ("image/jpg", "image/jpeg", "image/png", "image/gif", "image/webp"):
        raise HTTPException(status_code=400, detail="Недопустимый тип файла")
    if declared in ("image/jpg", "image/jpeg") and detected != "image/jpeg":
        raise HTTPException(status_code=400, detail="Содержимое файла не соответствует JPEG")
    if declared == "image/png" and detected != "image/png":
        raise HTTPException(status_code=400, detail="Содержимое файла не соответствует PNG")
    if declared == "image/gif" and detected != "image/gif":
        raise HTTPException(status_code=400, detail="Содержимое файла не соответствует GIF")
    if declared == "image/webp" and detected != "image/webp":
        raise HTTPException(status_code=400, detail="Содержимое файла не соответствует WEBP")
    return detected
