"""Unit tests for Ops AI done-notify HTML formatting."""
from __future__ import annotations

import ops_ai_service as svc


def test_format_done_notify_html_bullets(monkeypatch):
    monkeypatch.setattr(svc.settings, "public_site_url", "https://focuspay.org")
    html = svc.format_done_notify_html(
        {"id": 42, "title": "Captcha fix", "summary": "old"},
        note="- Larger captcha\n- Deployed panel\n",
    )
    assert "Ops AI · готово #42" in html
    assert "Captcha fix" in html
    assert "Larger captcha" in html
    assert "https://focuspay.org/x8/ai-tasks?id=42" in html
    assert "&lt;" not in html


def test_format_done_notify_escapes_html(monkeypatch):
    monkeypatch.setattr(svc.settings, "public_site_url", "")
    html = svc.format_done_notify_html(
        {"id": 1, "title": "A <b>x</b>", "request_text": "use <script>"},
        note=None,
    )
    assert "<b>x</b>" not in html or "&lt;b&gt;" in html
    assert "&lt;script&gt;" in html or "script" in html
