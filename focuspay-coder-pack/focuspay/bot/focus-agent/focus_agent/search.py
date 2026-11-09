"""Public web search from the bot host. The chat log is not the query."""

from __future__ import annotations

import re
from collections.abc import Callable

from focus_agent.redact import redact

_UNRELATED = re.compile(r"brawl|бравл|fandom\.com", re.IGNORECASE)

SearchFn = Callable[[str], list[dict]]


def _ddgs(query: str) -> list[dict]:
    from ddgs import DDGS

    with DDGS() as client:
        rows = client.text(query, max_results=3)
    return list(rows or [])


def about_us(hit: dict, question: str) -> bool:
    """A game wiki for the word «бот» is not an answer about Focus."""
    blob = f"{hit.get('title', '')} {hit.get('snippet', '')} {hit.get('url', '')}"
    if _UNRELATED.search(blob) and not _UNRELATED.search(question or ""):
        return False
    return True


def search_web(question: str, searcher: SearchFn | None = None) -> list[dict]:
    query = redact(question).strip()
    if not query or query == "[REDACTED]":
        return []
    fn = searcher or _ddgs
    try:
        raw = fn(query[:300])
    except Exception:
        return []
    hits: list[dict] = []
    for item in list(raw)[:8]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("href") or item.get("url") or "").strip()
        if not url.startswith("https://"):
            continue
        hit = {
            "title": redact(str(item.get("title") or ""))[:180],
            "url": url[:300],
            "snippet": redact(str(item.get("body") or item.get("snippet") or ""))[:400],
        }
        if not about_us(hit, question):
            continue
        hits.append(hit)
        if len(hits) == 3:
            break
    return hits


def format_hits(hits: list[dict]) -> str:
    if not hits:
        return ""
    lines = ["# Интернет"]
    for hit in hits[:3]:
        lines.append(f"- {hit['title']} — {hit['url']}\n  {hit['snippet']}")
    return "\n".join(lines)
