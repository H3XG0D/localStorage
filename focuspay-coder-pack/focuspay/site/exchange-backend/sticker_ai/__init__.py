"""FocusPay Sticker AI — isolated from Ops AI.

Scaffold only: not mounted in main.py. See docs/sticker-ai-architecture.md.
"""
from __future__ import annotations

from sticker_ai.constants import QUEUE_EDIT, QUEUE_GENERATE, QUEUE_PUBLISH, STATUSES
from sticker_ai.service import StickerAiService

__all__ = [
    "QUEUE_EDIT",
    "QUEUE_GENERATE",
    "QUEUE_PUBLISH",
    "STATUSES",
    "StickerAiService",
]
