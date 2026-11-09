"""Cookie flags for HTTP/HTTPS deployments."""
from unittest.mock import MagicMock

from app.core.cookies import cookie_secure_for_request


def _request(proto: str | None = None, scheme: str = "http"):
    req = MagicMock()
    req.headers.get.return_value = proto
    req.url.scheme = scheme
    return req


def test_cookie_not_secure_on_http():
    assert cookie_secure_for_request(_request(proto="http")) is False


def test_cookie_not_secure_without_forwarded_proto():
    assert cookie_secure_for_request(_request(proto=None, scheme="http")) is False


def test_cookie_secure_only_on_https_when_enabled(monkeypatch):
    monkeypatch.setattr("app.core.cookies.settings.COOKIE_SECURE", True)
    assert cookie_secure_for_request(_request(proto="https")) is True


def test_cookie_not_secure_on_http_even_when_enabled(monkeypatch):
    monkeypatch.setattr("app.core.cookies.settings.COOKIE_SECURE", True)
    assert cookie_secure_for_request(_request(proto="http")) is False
