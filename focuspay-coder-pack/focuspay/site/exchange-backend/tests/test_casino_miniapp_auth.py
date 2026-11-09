import hashlib
import hmac
import json
import unittest
from urllib.parse import urlencode

from fastapi import HTTPException
from casino_miniapp_auth import verify_casino_init_data


TOKEN = '123456:isolated-unit-test-token'
NOW = 1800000000


def signed_data(**overrides):
    fields = {'auth_date': str(NOW), 'user': json.dumps({'id': 123, 'first_name': 'QA'})}
    fields.update(overrides)
    check = '\n'.join(f'{k}={v}' for k,v in sorted(fields.items()))
    secret = hmac.new(b'WebAppData', TOKEN.encode(), hashlib.sha256).digest()
    fields['hash'] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class CasinoMiniAppAuthTests(unittest.TestCase):
    def test_signed_user_is_accepted(self):
        self.assertEqual(verify_casino_init_data(signed_data(), TOKEN, now=NOW)['id'], 123)

    def test_wrong_bot_tampering_duplicates_and_stale_data_are_rejected(self):
        cases = [
            (signed_data(), 'wrong-bot'),
            (signed_data() + '&user=%7B%22id%22%3A999%7D', TOKEN),
            (signed_data(auth_date=str(NOW-3601)), TOKEN),
            (signed_data(auth_date=str(NOW+31)), TOKEN),
            (signed_data(user=json.dumps({'id': -1})), TOKEN),
            (signed_data(user=json.dumps({'id': True})), TOKEN),
            ('user=123&auth_date=1800000000', TOKEN),
        ]
        for raw, token in cases:
            with self.subTest(raw=raw), self.assertRaises(HTTPException) as exc:
                verify_casino_init_data(raw, token, now=NOW)
            self.assertEqual(exc.exception.status_code, 401)

    def test_missing_server_token_fails_closed(self):
        with self.assertRaises(HTTPException) as exc:
            verify_casino_init_data(signed_data(), '', now=NOW)
        self.assertEqual(exc.exception.status_code, 503)
