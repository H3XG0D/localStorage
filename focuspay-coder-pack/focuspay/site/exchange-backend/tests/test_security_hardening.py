"""Тесты усиления безопасности."""
import time
import unittest
from unittest.mock import MagicMock

from auth import resolve_client_user_id, validate_username
from client_ip import get_client_ip
from fastapi import HTTPException
from totp_auth import generate_totp_secret, verify_totp_code, _hotp


class ClientIpTests(unittest.TestCase):
    def test_cf_connecting_ip_first(self):
        req = MagicMock()
        req.headers = {
            "cf-connecting-ip": "203.0.113.10",
            "x-real-ip": "198.51.100.1",
            "x-forwarded-for": "203.0.113.1",
        }
        req.client = MagicMock(host="127.0.0.1")
        self.assertEqual(get_client_ip(req), "203.0.113.10")

    def test_real_ip_fallback(self):
        req = MagicMock()
        req.headers = {"x-real-ip": "198.51.100.2"}
        req.client = MagicMock(host="127.0.0.1")
        self.assertEqual(get_client_ip(req), "198.51.100.2")


class TotpTests(unittest.TestCase):
    def test_generate_and_verify(self):
        secret = generate_totp_secret()
        step = int(time.time()) // 30
        code = str(_hotp(secret, step)).zfill(6)
        self.assertTrue(verify_totp_code(secret, code))
        self.assertFalse(verify_totp_code(secret, "000000"))


class ResolveClientUserIdTests(unittest.TestCase):
    def test_telegram_id_priority(self):
        uid = resolve_client_user_id(
            {"telegram_user_id": 123, "client_user_id": -456}
        )
        self.assertEqual(uid, 123)

    def test_client_user_id_fallback(self):
        uid = resolve_client_user_id({"client_user_id": -789})
        self.assertEqual(uid, -789)

    def test_missing_raises(self):
        with self.assertRaises(HTTPException):
            resolve_client_user_id({})


class UsernameValidationTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(validate_username("focus_user123"), "focus_user123")

    def test_rejects_short(self):
        with self.assertRaises(ValueError):
            validate_username("ab")
