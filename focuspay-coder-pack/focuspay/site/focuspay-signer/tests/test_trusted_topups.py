"""Доверенные пополнения: какие неподтверждённые выходы можно тратить и когда."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import store
import wallet_rpc
from config import settings
from wallet_rpc import (
    RpcError,
    fit_topups,
    group_incoming_unconfirmed,
    pick_fast_utxos,
    presend_reject_reason,
    unconfirmed_is_spendable,
)

TOPUP = "aa" * 32
OURS = "bb" * 32
FOREIGN = "cc" * 32


def _u(txid, vout=0, amount=0.01, safe=False, confirmations=0, spendable=True, label=""):
    row = {"txid": txid, "vout": vout, "amount": amount, "safe": safe,
           "confirmations": confirmations, "spendable": spendable}
    if label:
        row["label"] = label
    return row


class PickFastUtxoTests(unittest.TestCase):
    def test_only_allowlisted_unsafe_outputs(self):
        unspent = [_u(TOPUP), _u(OURS, 1), _u(FOREIGN)]
        picked = pick_fast_utxos(unspent, {TOPUP, OURS})
        self.assertEqual([u["txid"] for u in picked], [TOPUP, OURS])

    def test_safe_and_confirmed_are_left_to_the_wallet(self):
        unspent = [_u(TOPUP, safe=True), _u(TOPUP, 1, confirmations=1), _u(TOPUP, 2, spendable=False)]
        self.assertEqual(pick_fast_utxos(unspent, {TOPUP}), [])


class IncomingTopupTests(unittest.TestCase):
    def test_groups_only_unsafe_unconfirmed(self):
        unspent = [
            _u(TOPUP, amount=0.02),
            _u(TOPUP, vout=1, amount=0.01),
            _u(OURS, safe=True, amount=0.5),
            _u(FOREIGN, confirmations=1, amount=1),
        ]
        self.assertEqual(group_incoming_unconfirmed(unspent), [(TOPUP, 0.03)])

    def test_casino_deposit_label_is_not_spendable_early(self):
        from wallet_rpc import CASINO_DEPOSIT_LABEL

        unspent = [
            _u(TOPUP, amount=0.02, label=CASINO_DEPOSIT_LABEL),
            _u(FOREIGN, amount=0.01),
        ]
        self.assertEqual(group_incoming_unconfirmed(unspent), [(FOREIGN, 0.01)])
        self.assertEqual(pick_fast_utxos(unspent, {TOPUP, FOREIGN}), [_u(FOREIGN, amount=0.01)])

    def test_cap_skips_what_does_not_fit(self):
        groups = [(TOPUP, 0.04), (FOREIGN, 0.02)]
        self.assertEqual(
            fit_topups(groups, waiting=0.02, cap=0.05, already=set()),
            [(FOREIGN, 0.02)],
        )
        self.assertEqual(fit_topups(groups, waiting=0.0, cap=0.05, already={TOPUP}), [(FOREIGN, 0.02)])

    def test_only_explicit_non_rbf_is_spendable(self):
        pending = {"status": "pending"}
        self.assertTrue(unconfirmed_is_spendable({**pending, "bip125": "no"}))
        self.assertFalse(unconfirmed_is_spendable({**pending, "bip125": "yes"}))
        self.assertFalse(unconfirmed_is_spendable({**pending, "bip125": "unknown"}))
        self.assertFalse(unconfirmed_is_spendable(pending))
        self.assertFalse(unconfirmed_is_spendable({"status": "confirmed", "bip125": "no"}))


class PresendReasonTests(unittest.TestCase):
    def test_long_chain_is_definite(self):
        self.assertEqual(
            presend_reject_reason(RuntimeError("too-long-mempool-chain, too many unconfirmed ancestors")),
            "mempool_chain_limit",
        )
        self.assertEqual(
            presend_reject_reason(
                RuntimeError("Unconfirmed UTXOs are available, but spending them creates a chain of transactions that will be rejected by the mempool")
            ),
            "mempool_chain_limit",
        )

    def test_incomplete_send_is_definite(self):
        self.assertEqual(presend_reject_reason(RpcError("send_incomplete")), "send_incomplete")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._audit = patch.object(settings, "audit_path", str(Path(self._tmp.name) / "audit.log"))
        self._audit.start()
        self._backup = patch.object(store, "restore_empty_tables_from_backup", return_value={"deposits": 0, "payouts": 0})
        self._backup.start()
        store._conn = None
        store.init()

    def tearDown(self):
        store._conn.close()
        store._conn = None
        self._backup.stop()
        self._audit.stop()
        self._tmp.cleanup()

    def test_topup_and_our_payouts_are_fast_spendable(self):
        self.assertTrue(store.add_trusted_topup("btc", TOPUP.upper(), 0.02, "owner"))
        self.assertFalse(store.add_trusted_topup("btc", TOPUP, 0.02))
        store.reserve("order:1", "btc", "bc1q", 0.001)
        store.finish("order:1", store.STATUS_SENT, txid=OURS)
        store.reserve("order:2", "btc", "bc1q", 0.001)
        store.finish("order:2", store.STATUS_REJECTED, reason="insufficient_funds")
        self.assertEqual(store.fast_spend_txids("btc"), {TOPUP, OURS})
        self.assertEqual(store.fast_spend_txids("ltc"), set())


class SendPayoutTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._p = [
            patch.object(settings, "dry_run", False),
            patch.object(settings, "btc_rpc_user", "u"),
            patch.object(settings, "trusted_topups_enabled", True),
        ]
        for p in self._p:
            p.start()

    async def asyncTearDown(self):
        for p in self._p:
            p.stop()

    async def test_confirmed_funds_use_plain_send(self):
        with patch.object(wallet_rpc, "send_to_address", new=AsyncMock(return_value="t1")), patch.object(
            wallet_rpc, "send_with_fast_inputs", new=AsyncMock()
        ) as fast:
            self.assertEqual(await wallet_rpc.send_payout("btc", "bc1q", 0.001), "t1")
        fast.assert_not_awaited()

    async def test_short_of_confirmed_funds_spends_trusted_inputs(self):
        calls = []

        async def rpc(coin, method, params=None, **kw):
            calls.append((method, params))
            if method == "listunspent":
                return [_u(TOPUP, amount=0.02), _u(FOREIGN, amount=1.0)]
            if method == "gettransaction":
                return {"confirmations": 0, "amount": 0.02, "bip125-replaceable": "no"}
            if method == "getmempoolentry":
                return {}
            if method == "send":
                return {"complete": True, "txid": "t2"}
            if method == "estimatesmartfee":
                return {"feerate": 0.000003}
            raise AssertionError(method)

        with patch.object(
            wallet_rpc, "send_to_address", new=AsyncMock(side_effect=RpcError("Insufficient funds"))
        ), patch.object(wallet_rpc, "adopt_incoming_topups", new=AsyncMock(return_value=[])), patch.object(
            wallet_rpc, "_rpc", new=rpc
        ), patch(
            "store.fast_spend_txids", return_value={TOPUP}
        ):
            self.assertEqual(await wallet_rpc.send_payout("btc", "bc1q", 0.01), "t2")
        send = [p for m, p in calls if m == "send"][0]
        options = send[4]
        self.assertEqual(options["inputs"], [{"txid": TOPUP, "vout": 0}])
        self.assertTrue(options["add_inputs"])
        self.assertFalse(options["replaceable"])
        self.assertNotIn("include_unsafe", options)
        self.assertEqual(send[1:4], [None, "unset", 1.5])

    async def test_replaceable_unconfirmed_is_not_spent(self):
        calls = []

        async def rpc(coin, method, params=None, **kw):
            calls.append((method, params))
            if method == "listunspent":
                return [_u(TOPUP, amount=0.02)]
            if method == "gettransaction":
                return {"confirmations": 0, "amount": 0.02, "bip125-replaceable": "yes"}
            if method == "getmempoolentry":
                return {}
            if method == "send":
                return {"complete": True, "txid": "t2"}
            raise AssertionError(method)

        with patch.object(
            wallet_rpc, "send_to_address", new=AsyncMock(side_effect=RpcError("Insufficient funds"))
        ), patch.object(wallet_rpc, "adopt_incoming_topups", new=AsyncMock(return_value=[])), patch.object(
            wallet_rpc, "_rpc", new=rpc
        ), patch(
            "store.fast_spend_txids", return_value={TOPUP}
        ):
            with self.assertRaises(RpcError):
                await wallet_rpc.send_payout("btc", "bc1q", 0.01)
        self.assertFalse(any(method == "send" for method, _params in calls))

    async def test_disabled_keeps_plain_insufficient_funds(self):
        with patch.object(settings, "trusted_topups_enabled", False), patch.object(
            wallet_rpc, "send_to_address", new=AsyncMock(side_effect=RpcError("Insufficient funds"))
        ), patch.object(wallet_rpc, "send_with_fast_inputs", new=AsyncMock()) as fast:
            with self.assertRaises(RpcError):
                await wallet_rpc.send_payout("btc", "bc1q", 0.01)
        fast.assert_not_awaited()

    async def test_ltc_never_spends_unconfirmed(self):
        self.assertFalse(wallet_rpc.fast_spend_enabled("ltc"))

    async def test_timeout_is_not_retried_with_other_inputs(self):
        with patch.object(
            wallet_rpc, "send_to_address", new=AsyncMock(side_effect=TimeoutError("timed out"))
        ), patch.object(wallet_rpc, "send_with_fast_inputs", new=AsyncMock()) as fast:
            with self.assertRaises(TimeoutError):
                await wallet_rpc.send_payout("btc", "bc1q", 0.01)
        fast.assert_not_awaited()


class FeeFloorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._p = [patch.object(settings, "dry_run", False), patch.object(settings, "btc_rpc_user", "u")]
        for p in self._p:
            p.start()

    async def asyncTearDown(self):
        for p in self._p:
            p.stop()

    def _rpc(self, feerate_kvb, calls):
        async def rpc(coin, method, params=None, **kw):
            calls.append((method, params))
            if method == "estimatesmartfee":
                return {"feerate": feerate_kvb}
            if method == "sendtoaddress":
                return "t1"
            raise AssertionError(method)

        return rpc

    async def test_low_estimate_is_raised_to_floor(self):
        with patch.object(wallet_rpc, "_rpc", new=self._rpc(0.000003, [])):
            est = await wallet_rpc.estimate_fee("btc")
        self.assertEqual(est["feerate_sat_vb"], 1.5)
        self.assertAlmostEqual(est["fee"], 1.5 * wallet_rpc.TYPICAL_VSIZE / 1e8, places=8)

    async def test_high_estimate_is_kept(self):
        with patch.object(wallet_rpc, "_rpc", new=self._rpc(0.00004, [])):
            self.assertEqual((await wallet_rpc.estimate_fee("btc"))["feerate_sat_vb"], 4.0)

    async def test_btc_asks_node_for_next_block(self):
        calls: list = []
        with patch.object(wallet_rpc, "_rpc", new=self._rpc(0.00004, calls)):
            est = await wallet_rpc.estimate_fee("btc")
        self.assertEqual(
            [p for m, p in calls if m == "estimatesmartfee"][0], [1, "conservative"]
        )
        self.assertEqual(est["conf_target"], 1)
        self.assertEqual(est["mode"], "conservative")

    async def test_absurd_estimate_is_capped(self):
        with patch.object(wallet_rpc, "_rpc", new=self._rpc(0.01, [])):
            self.assertEqual(
                (await wallet_rpc.estimate_fee("btc"))["feerate_sat_vb"], 10.0
            )

    async def test_last_good_estimate_beats_the_floor(self):
        wallet_rpc._LAST_ESTIMATED_KVB.clear()
        try:
            with patch.object(wallet_rpc, "_rpc", new=self._rpc(0.00004, [])):
                await wallet_rpc.estimate_fee("btc")

            async def rpc(coin, method, params=None, **kw):
                if method == "estimatesmartfee":
                    return {}
                if method == "getnetworkinfo":
                    return {"relayfee": 0.00001}
                raise AssertionError(method)

            with patch.object(wallet_rpc, "_rpc", new=rpc):
                est = await wallet_rpc.estimate_fee("btc")
            self.assertEqual(est["feerate_sat_vb"], 4.0)
            self.assertFalse(est["estimated"])
        finally:
            wallet_rpc._LAST_ESTIMATED_KVB.clear()

    async def test_btc_send_pays_the_shown_rate(self):
        calls: list = []
        with patch.object(wallet_rpc, "_rpc", new=self._rpc(0.000003, calls)):
            await wallet_rpc.send_to_address("btc", "bc1q", 0.001)
        params = [p for m, p in calls if m == "sendtoaddress"][0]
        self.assertEqual(params[4:], [False, True, None, "unset", None, 1.5])


class TopupStatusTests(unittest.IsolatedAsyncioTestCase):
    async def _status(self, confirmations, in_mempool=True):
        async def rpc(coin, method, params=None, **kw):
            if method == "gettransaction":
                return {"confirmations": confirmations, "amount": 0.02}
            if method == "getmempoolentry":
                if in_mempool:
                    return {}
                raise RpcError("Transaction not in mempool")
            raise AssertionError(method)

        with patch.object(wallet_rpc, "_rpc", new=rpc):
            return (await wallet_rpc.topup_status("btc", TOPUP))["status"]

    async def test_statuses(self):
        self.assertEqual(await self._status(0), "pending")
        self.assertEqual(await self._status(0, in_mempool=False), "dropped")
        self.assertEqual(await self._status(2), "confirmed")
        self.assertEqual(await self._status(-1), "conflicted")


class AdoptReplaceableTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._p = [
            patch.object(settings, "audit_path", str(Path(self._tmp.name) / "audit.log")),
            patch.object(settings, "trusted_topups_enabled", True),
            patch.object(settings, "btc_rpc_user", "u"),
            patch.object(settings, "trusted_topup_max_btc", 1.0),
            patch.object(store, "restore_empty_tables_from_backup", return_value={"deposits": 0, "payouts": 0}),
        ]
        for p in self._p:
            p.start()
        store._conn = None
        store.init()
        wallet_rpc._logged_unspendable.clear()

    async def asyncTearDown(self):
        store._conn.close()
        store._conn = None
        for p in self._p:
            p.stop()
        self._tmp.cleanup()

    def _rpc(self, flags: dict[str, str | None]):
        async def rpc(coin, method, params=None, **kw):
            if method == "listunspent":
                return [_u(txid, amount=0.01) for txid in flags]
            if method == "gettransaction":
                flag = flags[params[0]]
                tx = {"confirmations": 0, "amount": 0.01}
                if flag is not None:
                    tx["bip125-replaceable"] = flag
                return tx
            if method == "getmempoolentry":
                return {}
            raise AssertionError(method)

        return rpc

    async def test_only_non_replaceable_topup_is_adopted(self):
        flags = {TOPUP: "yes", FOREIGN: "no", OURS: None}
        with patch.object(wallet_rpc, "_rpc", new=self._rpc(flags)):
            added = await wallet_rpc.adopt_incoming_topups("btc")
        self.assertEqual(added, [FOREIGN])
        self.assertEqual(
            [row["txid"] for row in store.trusted_topups("btc")],
            [FOREIGN],
        )


class ManualTrustTests(unittest.IsolatedAsyncioTestCase):
    async def _post(self, live: dict):
        import main

        class Request:
            async def body(self):
                return ('{"coin":"btc","txid":"%s"}' % TOPUP).encode()

        with patch.object(main, "_verify_hmac"), patch.object(
            main, "fast_spend_enabled", return_value=True
        ), patch.object(main, "topup_status", new=AsyncMock(return_value=live)), patch.object(
            main, "_audit"
        ), patch.object(main.store, "trusted_topups", return_value=[]), patch.object(
            main.store, "add_trusted_topup", return_value=True
        ) as add:
            result = await main.trust_topup(Request())
        return result, add

    async def test_replaceable_and_unknown_are_rejected(self):
        for bip125 in ("yes", "unknown", ""):
            result, add = await self._post(
                {"found": True, "status": "pending", "amount": 0.01, "bip125": bip125}
            )
            self.assertEqual(result["reason"], "replaceable", bip125)
            add.assert_not_called()

    async def test_non_replaceable_is_accepted(self):
        result, add = await self._post(
            {"found": True, "status": "pending", "amount": 0.01, "bip125": "no"}
        )
        self.assertTrue(result["ok"])
        add.assert_called_once()


if __name__ == "__main__":
    unittest.main()
