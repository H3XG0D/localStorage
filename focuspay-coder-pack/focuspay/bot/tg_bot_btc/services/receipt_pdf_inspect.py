"""Мягкий разбор PDF-чека: Producer/MediaBox/CreationDate/hash без hard-ban банков."""
from __future__ import annotations

import hashlib
import logging
import re
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("receipt_pdf_inspect")

BANKISH_PRODUCER_SUBSTR = (
    "jasperreports",
    "openpdf",
    "jaspersoft",
    "itext",
    "openhtmltopdf",
    "1t3xt",
    "apryse",
)

WATCH_PRODUCER_SUBSTR = (
    "oracle bi publisher",
    "oracle bipublisher",
    "ios version",
)

CONSUMER_PRODUCER_SUBSTR = (
    "microsoft",
    "word",
    "photoshop",
    "canva",
    "jspdf",
    "reportlab",
    "cairo",
    "print to pdf",
    "acrobat distiller",
    "quartz pdfcontext",
)

CHROME_SKIA_SUBSTR = (
    "skia/pdf",
    "chrome",
    "chromium",
)

# CreationDate заметно раньше выдачи реквизитов (сек).
STALE_CREATION_DRIFT_SEC = 300


def _extract_paren_field(raw: bytes, key: bytes) -> str | None:
    i = raw.find(key)
    if i < 0:
        return None
    chunk = raw[i : i + 160].decode("latin-1", errors="replace")
    m = re.search(r"/\w+\s*\(([^)]{0,120})", chunk)
    if m:
        return m.group(1).replace("\\", "").strip()
    # hex string Title <FEFF...>
    m2 = re.search(r"/\w+\s*<([0-9A-Fa-f]{0,80})", chunk)
    if m2:
        return m2.group(1)[:40]
    return None


def _mediabox(raw: bytes) -> tuple[float, float, float, float] | None:
    m = re.search(
        br"/MediaBox\s*\[\s*([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s*\]",
        raw,
    )
    if not m:
        return None
    return tuple(float(x) for x in m.groups())  # type: ignore[return-value]


def _page_kind(box: tuple[float, float, float, float] | None) -> str | None:
    if not box:
        return None
    w = abs(box[2] - box[0])
    h = abs(box[3] - box[1])
    if w > 500 and h > 750:
        return "A4"
    if w < 350:
        return "narrow"
    return "other"


def parse_pdf_date(value: str | None) -> datetime | None:
    """PDF-даты: 'D:YYYYMMDDHHmmSS...' или уже ISO."""
    if not value:
        return None
    raw = str(value).strip()
    m = re.match(
        r"D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?",
        raw,
    )
    if m:
        y, mo, d, hh, mm, ss = m.groups()
        try:
            return datetime(
                int(y),
                int(mo),
                int(d),
                int(hh or 0),
                int(mm or 0),
                int(ss or 0),
                tzinfo=timezone.utc,
            )
        except ValueError:
            return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def amount_present_in_text(text: str | None, amount: float | None) -> bool | None:
    """Грубая проверка, что сумма заявки встречается в тексте чека."""
    if not text or amount is None:
        return None
    try:
        whole = int(float(amount))
    except (TypeError, ValueError):
        return None
    if whole <= 0:
        return None
    patterns = [
        str(whole),
        f"{whole:,}".replace(",", " "),
        f"{whole:,}".replace(",", "\u00a0"),
        f"{whole:,}",
    ]
    return any(p in text for p in patterns)


def _heuristic_pdf_text(raw: bytes, *, limit: int = 8000) -> str | None:
    """Достаёт читаемые куски без pypdf (грубо, для поиска суммы)."""
    try:
        decoded = raw.decode("latin-1", errors="ignore")
    except Exception:
        return None
    # последовательности печатных символов длиной >=4
    chunks = re.findall(r"[\x20-\x7e\u0400-\u04ff]{4,}", decoded)
    if not chunks:
        return None
    text = " ".join(chunks)
    return text[:limit] if text else None


# Обрывки синтаксиса PDF в «тексте» — признак того, что мы читаем не текст,
# а latin-1 мусор из сжатых потоков.
_PDF_SYNTAX_MARKERS = (
    "endstream",
    "/FlateDecode",
    "/MediaBox",
    "/XObject",
    " obj <<",
    "%PDF-",
)

_OBJ_RE = re.compile(rb"(\d+)\s+\d+\s+obj\b(.*?)\bendobj", re.S)
_STREAM_START_RE = re.compile(rb"stream\r?\n")
_STRING_ESCAPES = {
    b"n": b"\n",
    b"r": b"\r",
    b"t": b"\t",
    b"b": b"\b",
    b"f": b"\f",
    b"(": b"(",
    b")": b")",
    b"\\": b"\\",
}
# Либо выбор шрифта (`/F1 9 Tf`), либо строковый литерал, либо hex-строка.
_CONTENT_TOKEN_RE = re.compile(
    rb"/([A-Za-z0-9#]+)\s+[-\d.]+\s+Tf|\(((?:[^()\\]|\\.)*)\)|<([0-9A-Fa-f\s]+)>"
)


def looks_like_extracted_text(text: str | None) -> bool:
    """True, если строка похожа на живой текст чека, а не на распакованный мусор."""
    if not text or len(text) < 8:
        return False
    if any(marker in text for marker in _PDF_SYNTAX_MARKERS):
        return False
    readable = sum(1 for ch in text if ch.isalnum() or ch.isspace() or ch in ",.:-+*()/₽%№")
    return readable / len(text) >= 0.75


def _unescape_pdf_string(body: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(body):
        ch = body[i : i + 1]
        if ch != b"\\":
            out += ch
            i += 1
            continue
        nxt = body[i + 1 : i + 2]
        if not nxt:
            break
        if nxt in _STRING_ESCAPES:
            out += _STRING_ESCAPES[nxt]
            i += 2
            continue
        if nxt in (b"\n", b"\r"):  # перенос строки внутри литерала
            i += 2
            continue
        m = re.match(rb"[0-7]{1,3}", body[i + 1 : i + 4])
        if m:
            out.append(int(m.group(0), 8) & 0xFF)
            i += 1 + len(m.group(0))
            continue
        out += nxt
        i += 2
    return bytes(out)


def _pdf_objects(raw: bytes) -> dict[int, bytes]:
    return {int(m.group(1)): m.group(2) for m in _OBJ_RE.finditer(raw)}


def _object_stream_data(body: bytes) -> bytes | None:
    start = _STREAM_START_RE.search(body)
    if not start:
        return None
    end = body.rfind(b"endstream")
    if end <= start.end():
        return None
    payload = body[start.end() : end]
    if b"/FlateDecode" not in body[: start.start()]:
        return payload
    try:
        return zlib.decompress(payload)
    except zlib.error:
        try:  # усечённые/битые хвосты потоков
            return zlib.decompressobj().decompress(payload)
        except zlib.error:
            return None


def _hex_to_unicode(chunk: bytes) -> str:
    try:
        data = bytes.fromhex(chunk.decode("ascii"))
    except ValueError:
        return ""
    if len(data) % 2:
        data += b"\x00"
    return data.decode("utf-16-be", errors="replace")


def _parse_tounicode_cmap(data: bytes) -> dict[int, str]:
    """Разбирает ToUnicode CMap: bfchar-пары и bfrange (диапазон и массив)."""
    cmap: dict[int, str] = {}
    for block in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
        for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", block):
            cmap[int(src, 16)] = _hex_to_unicode(dst)
    for block in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
        for lo, hi, dst in re.findall(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block
        ):
            lo_i, hi_i, base = int(lo, 16), int(hi, 16), int(dst, 16)
            if hi_i < lo_i or hi_i - lo_i > 0xFFFF:
                continue
            for offset in range(hi_i - lo_i + 1):
                cmap[lo_i + offset] = chr(base + offset)
        for lo, _hi, arr in re.findall(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]", block, re.S
        ):
            lo_i = int(lo, 16)
            for offset, item in enumerate(re.findall(rb"<([0-9A-Fa-f]*)>", arr)):
                cmap[lo_i + offset] = _hex_to_unicode(item)
    return cmap


def _collect_font_cmaps(
    objs: dict[int, bytes],
) -> tuple[dict[int, dict[int, str]], dict[bytes, int]]:
    """Карты ToUnicode по номеру объекта шрифта + разрешение имён из /Font <<…>>."""
    cmap_by_font: dict[int, dict[int, str]] = {}
    for num, body in objs.items():
        m = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", body)
        if not m:
            continue
        target = objs.get(int(m.group(1)))
        if target is None:
            continue
        data = _object_stream_data(target)
        if not data:
            continue
        cmap = _parse_tounicode_cmap(data)
        if cmap:
            cmap_by_font[num] = cmap
    name_to_font: dict[bytes, int] = {}
    for body in objs.values():
        m = re.search(rb"/Font\s*<<(.*?)>>", body, re.S)
        if not m:
            continue
        for name, ref in re.findall(rb"/([A-Za-z0-9#]+)\s+(\d+)\s+\d+\s+R", m.group(1)):
            name_to_font[name] = int(ref)
    return cmap_by_font, name_to_font


def _decode_with_cmap(data: bytes, cmap: dict[int, str], width: int) -> str:
    out: list[str] = []
    if width == 2:
        for i in range(0, len(data) - 1, 2):
            out.append(cmap.get((data[i] << 8) | data[i + 1], ""))
    else:
        for byte in data:
            out.append(cmap.get(byte, ""))
    return "".join(out)


def _cmap_pdf_text(raw: bytes, *, limit: int = 8000) -> str | None:
    """Читает текст через ToUnicode шрифтов — банковские чеки на Identity-H сабсетах.

    Без этого текст возвращается глиф-айдишниками (`\\x02H\\x02i…`), и любая
    проверка суммы промахивается на каждом настоящем чеке Сбера/Т-Банка.
    """
    objs = _pdf_objects(raw)
    if not objs:
        return None
    cmap_by_font, name_to_font = _collect_font_cmaps(objs)
    if not cmap_by_font:
        return None
    widths = {
        font: 2 if (max(cmap) if cmap else 0) > 0xFF else 1
        for font, cmap in cmap_by_font.items()
    }
    fallback = next(iter(cmap_by_font)) if len(cmap_by_font) == 1 else None

    lines: list[str] = []
    for body in objs.values():
        data = _object_stream_data(body)
        if not data or (b"Tj" not in data and b"TJ" not in data):
            continue
        current = fallback
        parts: list[str] = []
        for token in _CONTENT_TOKEN_RE.finditer(data):
            font_name, literal, hex_str = token.groups()
            if font_name is not None:
                resolved = name_to_font.get(font_name)
                if resolved is not None or name_to_font:
                    # Шрифт без своей ToUnicode читать нечем — его строки
                    # пропускаем, иначе декодируем чужой картой и получаем мусор.
                    current = resolved if resolved in cmap_by_font else None
                continue
            if current is None:
                continue
            if literal is not None:
                payload = _unescape_pdf_string(literal)
            else:
                cleaned = re.sub(rb"\s", b"", hex_str or b"")
                if len(cleaned) % 2:
                    cleaned += b"0"
                try:
                    payload = bytes.fromhex(cleaned.decode("ascii"))
                except (ValueError, UnicodeDecodeError):
                    continue
            parts.append(_decode_with_cmap(payload, cmap_by_font[current], widths[current]))
        chunk = " ".join(p.strip() for p in parts if p.strip())
        if chunk:
            lines.append(chunk)
    text = "\n".join(lines).strip()
    return text[:limit] if text else None


_STREAM_BLOCK_RE = re.compile(rb"stream\r?\n.*?endstream", re.S)
# Литерал строки; группа 1 непуста, если это значение поля метаданных (/Producer (…)).
_PLAIN_LITERAL_RE = re.compile(rb"(?:/([A-Za-z0-9]+)\s*)?\(((?:[^()\\]|\\.)*)\)")


def _plain_pdf_text(raw: bytes, *, limit: int = 8000) -> str | None:
    """Текст незапакованных PDF: литералы вне потоков, без полей метаданных."""
    outside = _STREAM_BLOCK_RE.sub(b" ", raw)
    parts: list[str] = []
    for m in _PLAIN_LITERAL_RE.finditer(outside):
        if m.group(1):  # /Producer, /Creator, /CreationDate — это не текст чека
            continue
        chunk = _unescape_pdf_string(m.group(2)).decode("latin-1", errors="replace").strip()
        if chunk:
            parts.append(chunk)
    text = " ".join(parts).strip()
    return text[:limit] if text else None


def _extract_pdf_text(raw: bytes, pypdf_text: str | None) -> tuple[str | None, str | None]:
    """Возвращает (текст, источник). Источник None — текст прочитать не удалось."""
    if looks_like_extracted_text(pypdf_text):
        return pypdf_text, "pypdf"
    for source, reader in (("cmap", _cmap_pdf_text), ("plain", _plain_pdf_text)):
        try:
            value = reader(raw)
        except Exception as e:  # разбор чужого PDF не должен ронять приём чека
            logger.debug("pdf text via %s failed: %s", source, e, exc_info=True)
            continue
        if looks_like_extracted_text(value):
            return value, source
    return None, None


def _pypdf_text_and_dates(
    raw: bytes, *, text_limit: int = 2000
) -> tuple[str | None, datetime | None, datetime | None]:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        return None, None, None
    import io

    try:
        reader = PdfReader(io.BytesIO(raw))
        meta = reader.metadata or {}
        creation = parse_pdf_date(meta.get("/CreationDate"))
        mod = parse_pdf_date(meta.get("/ModDate"))
        chunks: list[str] = []
        for page in reader.pages[:3]:
            try:
                chunks.append(page.extract_text() or "")
            except Exception:
                logger.debug("pdf page extract failed", exc_info=True)
        text = "\n".join(chunks).strip()
        return (text[:text_limit] if text else None), creation, mod
    except Exception as e:
        logger.debug("pypdf inspect failed: %s", e)
        return None, None, None


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def read_receipt_markup(raw: bytes) -> tuple[str, str, str]:
    """Текст чека, Producer и Creator. Пустой текст, если PDF не прочитался.

    Лимит больше, чем у карточки риска: подпись банка часто внизу страницы.
    """
    producer = _extract_paren_field(raw, b"/Producer") or ""
    creator = _extract_paren_field(raw, b"/Creator") or ""
    pypdf_text, _, _ = _pypdf_text_and_dates(raw, text_limit=8000)
    text, source = _extract_pdf_text(raw, pypdf_text)
    if source is None:
        return "", producer, creator
    return (text or "")[:8000], producer, creator


def inspect_pdf_bytes(
    raw: bytes,
    *,
    fiat_amount: float | None = None,
    details_issued_at: datetime | None = None,
) -> dict[str, Any]:
    producer = _extract_paren_field(raw, b"/Producer")
    creator = _extract_paren_field(raw, b"/Creator")
    creation_raw = _extract_paren_field(raw, b"/CreationDate")
    mod_raw = _extract_paren_field(raw, b"/ModDate")
    creation_dt = parse_pdf_date(creation_raw)
    mod_dt = parse_pdf_date(mod_raw)
    box = _mediabox(raw)
    kind = _page_kind(box)
    sha = hashlib.sha256(raw).hexdigest()
    flags: list[str] = []

    blob = f"{producer or ''} {creator or ''}".lower()
    if any(s in blob for s in BANKISH_PRODUCER_SUBSTR):
        flags.append("pdf_bankish_producer")
    if any(s in blob for s in WATCH_PRODUCER_SUBSTR):
        flags.append("pdf_watch_producer")
    if any(s in blob for s in CONSUMER_PRODUCER_SUBSTR):
        flags.append("pdf_consumer_producer")
    if any(s in blob for s in CHROME_SKIA_SUBSTR):
        flags.append("pdf_chrome_skia")
    if kind == "A4":
        flags.append("pdf_a4_page")

    pypdf_text, pypdf_creation, pypdf_mod = _pypdf_text_and_dates(raw)
    if creation_dt is None and pypdf_creation is not None:
        creation_dt = pypdf_creation
        if creation_raw is None:
            creation_raw = pypdf_creation.isoformat()
    if mod_dt is None and pypdf_mod is not None:
        mod_dt = pypdf_mod
    text_excerpt, text_source = _extract_pdf_text(raw, pypdf_text)
    if text_source is None:
        # Только для глаз оператора: сумму по этой каше проверять нельзя.
        text_excerpt = _heuristic_pdf_text(raw)

    issued = _as_utc(details_issued_at)
    if creation_dt is not None and issued is not None:
        drift = (issued - creation_dt).total_seconds()
        if drift > STALE_CREATION_DRIFT_SEC:
            flags.append("pdf_stale_creation")

    if text_source is None:
        amount_present = None
        if fiat_amount is not None:
            flags.append("pdf_text_unreadable")
    else:
        amount_present = amount_present_in_text(text_excerpt, fiat_amount)
        if amount_present is False:
            flags.append("pdf_amount_missing")

    return {
        "producer": producer,
        "creator": creator,
        "creation_date": creation_raw,
        "creation_date_iso": creation_dt.isoformat() if creation_dt else None,
        "mod_date": mod_raw,
        "mediabox": list(box) if box else None,
        "page_kind": kind,
        "sha256": sha,
        "size": len(raw),
        "flags": flags,
        "text_excerpt": text_excerpt[:500] if text_excerpt else None,
        "text_source": text_source,
        "amount_present": amount_present,
    }


def inspect_pdf_file(
    path: Path,
    *,
    fiat_amount: float | None = None,
    details_issued_at: datetime | None = None,
) -> dict[str, Any] | None:
    try:
        raw = path.read_bytes()
    except OSError as e:
        logger.warning("pdf inspect read failed path=%s: %s", path, e)
        return None
    if not raw.startswith(b"%PDF"):
        return {"flags": ["pdf_not_pdf"], "sha256": hashlib.sha256(raw).hexdigest()}
    return inspect_pdf_bytes(
        raw,
        fiat_amount=fiat_amount,
        details_issued_at=details_issued_at,
    )
