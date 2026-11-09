"""Лексический RAG по whitelist путям проекта (без .env / секретов)."""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from config import settings

logger = logging.getLogger("ops_ai_rag")

_DENY_NAME_RE = re.compile(
    r"(^|/)\.env($|\.)|(^|/)secrets?(/|$)|credential|private[_\-]?key|\.pem$",
    re.I,
)

_ALLOWED_SUFFIXES = {".md", ".txt", ".py", ".ts", ".tsx", ".sql", ".yml", ".yaml", ".json"}

_FREEZE_HINTS = (
    "order_financial",
    "financial_guards",
    "buy_payout",
    "payfast",
    "merchant_",
    "webhook_security",
    "service_profit",
    "user_cashback",
    "user_referral_commission",
    "FROZEN",
)

_INDEX_TTL_SEC = 300
_index_cache: dict[str, tuple[float, list["DocChunk"]]] = {}


@dataclass
class DocChunk:
    path: str
    title: str
    text: str
    score: float = 0.0


def _repo_root() -> Path:
    # site/exchange-backend/ops_ai_rag.py → focuspay/
    return Path(__file__).resolve().parents[2]


def _cite_path(path: Path) -> str:
    """Стабильный путь для промпта: bot/tg_bot_btc/..., не code/handlers/..."""
    resolved = path.resolve()
    try:
        rel = resolved.relative_to(_repo_root())
        return str(rel).replace("\\", "/")
    except ValueError:
        pass
    for prefix, label in (
        (Path("/opt/tg_bot_btc"), "bot/tg_bot_btc"),
        (Path("/opt/exchange-backend"), "site/exchange-backend"),
        (Path("/home/qwe/Desktop/tg_bot_btc"), "bot/tg_bot_btc"),
        (Path("/home/qwe/Desktop/exchange/backend"), "site/exchange-backend"),
    ):
        try:
            if prefix.is_dir():
                rel = resolved.relative_to(prefix.resolve())
            else:
                rel = resolved.relative_to(prefix)
            return f"{label}/{rel}".replace("\\", "/")
        except ValueError:
            continue
    return f"code/{path.parent.name}/{path.name}"


def _knowledge_roots() -> list[Path]:
    raw = (settings.ops_ai_knowledge_roots or "").strip()
    roots: list[Path] = []
    if raw:
        for part in raw.split(","):
            p = Path(part.strip()).expanduser()
            if p.is_dir():
                roots.append(p)
    # Sensible defaults for local + prod layouts
    for candidate in (
        Path("/opt/tg_bot_btc/docs"),
        Path("/home/qwe/Desktop/tg_bot_btc/docs"),
        _repo_root() / "bot" / "tg_bot_btc" / "docs",
        Path(__file__).resolve().parents[2] / "tg_bot_btc" / "docs",
        Path(__file__).resolve().parent / "ops_ai_knowledge",
    ):
        if candidate.is_dir() and candidate not in roots:
            roots.append(candidate)
    return roots


def _is_denied(path: Path) -> bool:
    s = str(path)
    if _DENY_NAME_RE.search(s):
        return True
    try:
        if path.is_symlink():
            return True
    except OSError:
        return True
    return False


def _iter_files(root: Path) -> list[Path]:
    out: list[Path] = []
    if not root.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d
            for d in dirnames
            if d not in {".git", "node_modules", ".venv", "venv", "__pycache__", "dist"}
        ]
        for name in filenames:
            p = Path(dirpath) / name
            if p.suffix.lower() not in _ALLOWED_SUFFIXES:
                continue
            if _is_denied(p):
                continue
            out.append(p)
    return out


def _chunk_text(path: Path, text: str, max_chars: int = 1800) -> list[DocChunk]:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []
    rel = str(path)
    title = path.name
    chunks: list[DocChunk] = []
    if len(text) <= max_chars:
        chunks.append(DocChunk(path=rel, title=title, text=text))
        return chunks
    parts = re.split(r"\n(?=#{1,3}\s)", text) if path.suffix.lower() == ".md" else [text]
    buf = ""
    for part in parts:
        if len(buf) + len(part) + 1 <= max_chars:
            buf = f"{buf}\n{part}".strip() if buf else part
        else:
            if buf:
                chunks.append(DocChunk(path=rel, title=title, text=buf))
            buf = part[:max_chars]
    if buf:
        chunks.append(DocChunk(path=rel, title=title, text=buf[:max_chars]))
    return chunks


_EXTRA_FILE_GLOBS = (
    "buy_crypto_amount.py",
    "commission.py",
    "crypto_network_fee.py",
    "runtime_settings.py",
    "payment_methods_display.py",
    "service_profit.py",
    "auth.py",
    "ip_blocklist.py",
    "login_rate_limit.py",
    "access_log_middleware.py",
    "ops_ai_service.py",
    "ops_ai_llm.py",
    "rates_api.py",
    "exchange_flow.py",
    "ops_ai_surface.py",
    "ops_ai_ui_context.py",
)

# Каталоги кода (ограниченный walk) для multi-agent RAG
_CODE_WALK_ROOTS = (
    Path("/opt/exchange-backend/routers"),
    Path("/opt/tg_bot_btc/handlers"),
    Path("/opt/tg_bot_btc/services"),
    Path("/home/qwe/Desktop/exchange/backend/routers"),
    Path("/home/qwe/Desktop/tg_bot_btc/handlers"),
    Path("/home/qwe/Desktop/tg_bot_btc/services"),
    _repo_root() / "bot" / "tg_bot_btc" / "handlers",
    _repo_root() / "bot" / "tg_bot_btc" / "services",
    _repo_root() / "focussite" / "frontend" / "src" / "panel" / "operator",
    _repo_root() / "focussite" / "frontend" / "src" / "panel" / "admin",
    Path("/home/qwe/Desktop/focuspay/focussite/frontend/src/panel/operator"),
    Path("/home/qwe/Desktop/focuspay/focussite/frontend/src/panel/admin"),
)


def _extra_project_files() -> list[Path]:
    roots = [
        Path(__file__).resolve().parent,
        Path("/opt/exchange-backend"),
        Path("/opt/tg_bot_btc/services"),
        Path("/opt/tg_bot_btc/handlers"),
        Path("/home/qwe/Desktop/exchange/backend"),
        Path("/home/qwe/Desktop/tg_bot_btc/services"),
        Path("/home/qwe/Desktop/tg_bot_btc/handlers"),
        _repo_root() / "bot" / "tg_bot_btc" / "services",
        _repo_root() / "bot" / "tg_bot_btc" / "handlers",
    ]
    out: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for name in _EXTRA_FILE_GLOBS:
            p = root / name
            if not p.is_file() or _is_denied(p):
                continue
            key = str(p.resolve())
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
    # limited walk of routers/handlers/panel
    for walk_root in _CODE_WALK_ROOTS:
        if not walk_root.is_dir():
            continue
        count = 0
        for path in _iter_files(walk_root):
            if count >= 80:
                break
            if path.suffix.lower() not in {".py", ".ts", ".tsx"}:
                continue
            if path.stat().st_size > 200_000:
                continue
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            out.append(path)
            count += 1
    return out


def rebuild_index(*, force: bool = False) -> list[DocChunk]:
    cache_key = "default"
    now = time.time()
    if not force and cache_key in _index_cache:
        ts, docs = _index_cache[cache_key]
        if now - ts < _INDEX_TTL_SEC:
            return docs

    docs: list[DocChunk] = []
    for root in _knowledge_roots():
        for path in _iter_files(root):
            try:
                if path.stat().st_size > 400_000:
                    continue
                raw = path.read_text(encoding="utf-8", errors="ignore")
            except OSError as e:
                logger.debug("skip %s: %s", path, e)
                continue
            # Prefer relative-to-root path for citations
            try:
                rel = str(path.relative_to(root))
            except ValueError:
                rel = str(path)
            for ch in _chunk_text(path, raw):
                ch.path = f"{root.name}/{rel}" if root.name else rel
                docs.append(ch)

    for path in _extra_project_files():
        try:
            if path.stat().st_size > 400_000:
                continue
            raw = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for ch in _chunk_text(path, raw):
            try:
                ch.path = _cite_path(path)
            except Exception:
                ch.path = f"code/{path.name}"
            docs.append(ch)

    # Always inject freeze reminder
    docs.append(
        DocChunk(
            path="rules/FROZEN_INLINE",
            title="Freeze",
            text=(
                "Жёсткий freeze: финансы (order_financial, buy_payout, cashback/referral ledger) "
                "и Payfast/merchant/webhook HMAC. Менять только после явной фразы "
                "«можно трогать финансы / Payfast». Секреты (.env) в ответы не включать."
            ),
        )
    )
    _index_cache[cache_key] = (now, docs)
    logger.info("ops_ai RAG index: %s chunks from %s roots", len(docs), len(_knowledge_roots()))
    return docs


def _tokenize(query: str) -> set[str]:
    words = re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9_/.-]{3,}", query.lower())
    return set(words)


def retrieve(query: str, *, limit: int = 8) -> list[DocChunk]:
    docs = rebuild_index()
    tokens = _tokenize(query)
    if not tokens:
        return docs[:limit]

    qlow = query.lower()
    bot_query = any(
        k in qlow
        for k in ("бот", "телеграм", "telegram", "tg_bot", "rates_api", "курсы недоступ")
    )
    scored: list[DocChunk] = []
    for doc in docs:
        hay = f"{doc.path}\n{doc.title}\n{doc.text}".lower()
        score = 0.0
        for t in tokens:
            if t in hay:
                score += 1.0 + (2.0 if t in doc.path.lower() else 0.0)
        if any(h.lower() in hay for h in _FREEZE_HINTS if h.lower() in tokens or "freeze" in tokens or "финанс" in query.lower()):
            score += 0.5
        if bot_query and "tg_bot_btc" in doc.path.lower():
            score += 3.0
        if bot_query and ("rates_api" in doc.path.lower() or "exchange_flow" in doc.path.lower()):
            score += 2.0
        if score > 0:
            scored.append(DocChunk(path=doc.path, title=doc.title, text=doc.text, score=score))

    scored.sort(key=lambda d: d.score, reverse=True)
    return scored[:limit]


def detect_freeze_hit(text: str, file_hints: list[str] | None = None) -> bool:
    blob = f"{text}\n{' '.join(file_hints or [])}".lower()
    return any(h.lower() in blob for h in _FREEZE_HINTS)


def format_context(chunks: list[DocChunk], *, max_chars: int = 12000) -> str:
    parts: list[str] = []
    used = 0
    for ch in chunks:
        block = f"### {ch.path}\n{ch.text.strip()}\n"
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    return "\n".join(parts)
