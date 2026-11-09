"""Выплата с кошелька проекта по ручной заявке: токен окна, 2FA, отправка."""
from __future__ import annotations

import time
import unittest
from unittest.mock import AsyncMock, patch

import project_wallet_payout as pwp
from totp_auth import _hotp, generate_totp_secret


def _token(**kw) -> str:
    args = {
        "operator_id": 7,
        "fp": "fp1",
        "address": "ltc1qaddr",
        "crypto_amount": 0.12345678,
        "amount_rub": 1000,
        "base_rate": 8000.0,
    }
    args.update(kw)
    return pwp.make_preview_token(**args)


class TokenTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(pwp.settings, "secret_key", "test-secret")
        p.start()
        self.addCleanup(p.stop)

    def test_roundtrip(self):
        payload = pwp.read_preview_token(_token(), operator_id=7, fp="fp1")
        self.assertEqual(payload["amt"], "0.12345678")
        self.assertEqual(payload["addr"], "ltc1qaddr")
        self.assertEqual(payload["rate"], 8000.0)

    def test_tampered_signature(self):
        raw, sig = _token().rsplit(".", 1)
        with self.assertRaises(pwp.WalletPayoutError) as cm:
            pwp.read_preview_token(f"{raw}.{'0' * len(sig)}", operator_id=7, fp="fp1")
        self.assertEqual(cm.exception.code, "bad_token")

    def test_other_operator(self):
        with self.assertRaises(pwp.WalletPayoutError) as cm:
            pwp.read_preview_token(_token(), operator_id=8, fp="fp1")
        self.assertEqual(cm.exception.status, 403)

    def test_changed_form(self):
        with self.assertRaises(pwp.WalletPayoutError) as cm:
            pwp.read_preview_token(_token(), operator_id=7, fp="fp2")
        self.assertEqual(cm.exception.code, "data_changed")

    def test_expired(self):
        tok = _token()
        with patch("project_wallet_payout.time.time", return_value=time.time() + pwp.PREVIEW_TTL_SEC + 5):
            with self.assertRaises(pwp.WalletPayoutError) as cm:
                pwp.read_preview_token(tok, operator_id=7, fp="fp1")
        self.assertEqual(cm.exception.code, "token_expired")

    def test_fingerprint_is_order_independent(self):
        self.assertEqual(pwp.fingerprint({"a": 1, "b": 2}), pwp.fingerprint({"b": 2, "a": 1}))
        self.assertNotEqual(pwp.fingerprint({"a": 1}), pwp.fingerprint({"a": 2}))


class AmountTests(unittest.TestCase):
    def test_same_amount(self):
        self.assertTrue(pwp.same_amount(0.1, "0.10000000"))
        self.assertFalse(pwp.same_amount(0.10000001, "0.10000000"))

    def test_rate_close(self):
        self.assertTrue(pwp.rate_close(8050, 8000))
        self.assertFalse(pwp.rate_close(8100, 8000))
        self.assertFalse(pwp.rate_close(8000, 0))


class RequestIdTests(unittest.TestCase):
    def test_first_attempt_uses_the_order_id(self):
        self.assertEqual(pwp.next_project_send_request_id("35528513", []), "order:35528513")

    def test_rejected_autopilot_attempt_gets_a_new_id(self):
        previous = [{"status": "failed", "txid": None, "request_id": "order:35528513"}]
        self.assertEqual(pwp.next_project_send_request_id("35528513", previous), "order:35528513-r1")

    def test_open_send_is_not_retried(self):
        previous = [{"status": "sent", "txid": "abc"}]
        with self.assertRaises(pwp.WalletPayoutError) as cm:
            pwp.next_project_send_request_id("35528513", previous)
        self.assertEqual(cm.exception.code, "already_sent")


class HardCheckTests(unittest.TestCase):
    def test_other_client_address_does_not_block_by_itself(self):
        checks = [
            pwp.Check("address_other_client", False, "адрес другого клиента"),
            pwp.Check("address_operator", True),
        ]
        self.assertEqual(pwp.hard_failures(checks), [])

    def test_own_address_still_blocks(self):
        checks = [pwp.Check("address_own", False, "это наш адрес")]
        self.assertEqual([c.key for c in pwp.hard_failures(checks)], ["address_own"])


class ModeTests(unittest.TestCase):
    def test_project_only_for_btc_ltc(self):
        with patch("project_wallet_payout.manual_payout_wallet", return_value="project"):
            self.assertTrue(pwp.project_mode_for("ltc"))
            self.assertTrue(pwp.project_mode_for("btc"))
            self.assertFalse(pwp.project_mode_for("usdt"))
        with patch("project_wallet_payout.manual_payout_wallet", return_value="operator"):
            self.assertFalse(pwp.project_mode_for("btc"))


class TotpConn:
    def __init__(self, secret: str, last_step: int | None = None):
        self.secret = secret
        self.last_step = last_step

    async def fetchrow(self, _sql, _op_id):
        return {"totp_secret": self.secret, "totp_enabled": True}

    async def fetchval(self, _sql, _op_id, step):
        if self.last_step is None or self.last_step < step:
            self.last_step = step
            return 1
        return None


class TotpTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        pwp._totp_fails.clear()
        self.secret = generate_totp_secret()
        self.code = str(_hotp(self.secret, int(time.time()) // 30)).zfill(6)

    async def test_code_cannot_be_reused(self):
        conn = TotpConn(self.secret)
        await pwp.consume_totp(conn, 1, self.code)
        with self.assertRaises(pwp.WalletPayoutError) as cm:
            await pwp.consume_totp(conn, 1, self.code)
        self.assertEqual(cm.exception.code, "totp_invalid")

    async def test_lock_after_three_failures(self):
        conn = TotpConn(self.secret)
        with patch("project_wallet_payout.notify_admin", new=AsyncMock()) as notify:
            for _ in range(pwp.TOTP_FAIL_LIMIT):
                with self.assertRaises(pwp.WalletPayoutError):
                    await pwp.consume_totp(conn, 2, "000000" if self.code != "000000" else "111111")
            notify.assert_awaited_once()
        with self.assertRaises(pwp.WalletPayoutError) as cm:
            await pwp.consume_totp(conn, 2, self.code)
        self.assertEqual(cm.exception.code, "totp_locked")

    async def test_disabled_2fa(self):
        conn = TotpConn("")
        with self.assertRaises(pwp.WalletPayoutError) as cm:
            await pwp.consume_totp(conn, 3, self.code)
        self.assertEqual(cm.exception.code, "totp_missing")


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class SendConn:
    def __init__(self, prev):
        self.prev = prev
        self.executed: list[tuple] = []

    def transaction(self):
        return _Tx()

    async def fetch(self, _sql, *_a):
        return self.prev

    async def execute(self, sql, *args):
        self.executed.append((sql, args))


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *a):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


class SendTests(unittest.IsolatedAsyncioTestCase):
    async def _send(self, prev, signer_reply):
        conn = SendConn(prev)
        submit = AsyncMock(return_value=signer_reply)
        with (
            patch("db.get_pool", new=AsyncMock(return_value=_Pool(conn))),
            patch("signer_client.submit_signer_payout", new=submit),
            patch("auto_payout_audit_log.audit_payout_event", new=AsyncMock()),
            patch("auto_payout_worker._enqueue_payout_request", new=AsyncMock()) as enqueue,
            patch("auto_payout_worker._mark_request", new=AsyncMock()) as mark,
        ):
            st, resp = await pwp.send_from_project_wallet(
                order_id="OPX",
                user_id=1,
                coin="ltc",
                address="ltc1qaddr",
                crypto_amount=0.1,
                amount_rub=900,
                operator_id=7,
            )
        return st, resp, submit, enqueue, mark

    async def test_open_request_blocks_second_send(self):
        with self.assertRaises(pwp.WalletPayoutError) as cm:
            await self._send([{"request_id": "order:OPX", "status": "queued"}], ("accepted", {}))
        self.assertEqual(cm.exception.code, "already_sent")

    async def test_retry_after_reject_uses_new_request_id(self):
        st, resp, submit, enqueue, _ = await self._send(
            [{"request_id": "order:OPX", "status": "failed"}],
            ("accepted", {"txid": "ab" * 32}),
        )
        self.assertEqual(st, "accepted")
        self.assertEqual(submit.await_args.args[0]["request_id"], "order:OPX-r1")
        self.assertEqual(enqueue.await_args.kwargs["kind"], "manual_buy")
        self.assertEqual(resp["request_id"], "order:OPX-r1")

    async def test_duplicate_without_txid_is_unknown(self):
        st, *_ = await self._send([], ("duplicate", {"prev_status": "unknown"}))
        self.assertEqual(st, "unknown")

    async def test_rejected_marks_failed(self):
        st, _resp, _s, _e, mark = await self._send([], ("rejected", {"reason": "node_not_ready"}))
        self.assertEqual(st, "rejected")
        self.assertEqual(mark.await_args.args[2], "failed")


class ExplorerTests(unittest.IsolatedAsyncioTestCase):
    async def test_mempool_fee(self):
        from network_fees import fetch_explorer_fee

        class Resp:
            status = 200

            async def json(self, content_type=None):
                return {"fee": 1410, "weight": 561}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        class Session:
            def get(self, url):
                self.url = url
                return Resp()

        s = Session()
        status, fee, vsize = await fetch_explorer_fee(s, "ltc", "abc")
        self.assertEqual(status, "ok")
        self.assertAlmostEqual(fee, 0.0000141)
        self.assertEqual(vsize, 141)
        self.assertIn("litecoinspace.org", s.url)

    async def test_falls_back_to_blockchair(self):
        from network_fees import fetch_explorer_fee

        class Resp:
            def __init__(self, status, body):
                self.status, self.body = status, body

            async def json(self, content_type=None):
                return self.body

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        class Session:
            def get(self, url):
                if "blockchair" in url:
                    return Resp(200, {"data": {"tx1": {"transaction": {"fee": 2240, "weight": 896}}}})
                return Resp(503, {})

        status, fee, vsize = await fetch_explorer_fee(Session(), "ltc", "tx1")
        self.assertEqual((status, vsize), ("ok", 224))
        self.assertAlmostEqual(fee, 0.0000224)

    def test_usdt_fee_in_trx(self):
        from network_fees import fee_unit

        self.assertEqual(fee_unit("usdt"), "trx")
        self.assertEqual(fee_unit("btc"), "btc")


if __name__ == "__main__":
    unittest.main()
