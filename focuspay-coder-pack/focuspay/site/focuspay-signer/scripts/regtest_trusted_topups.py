"""Регтест доверенных пополнений на живом bitcoind.

Запуск: BITCOIND=/path/to/bitcoind python scripts/regtest_trusted_topups.py

Поднимает bitcoind -regtest во временной папке, кошельки owner (ваш внешний)
и hot (горячий), и гоняет HTTP API подписанта с настоящей HMAC-подписью:
отказ без доверия, доверие, цепочка выплат, лимит, замена пополнения.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRET = "regtest-secret"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Node:
    def __init__(self, bitcoind: str, datadir: Path) -> None:
        datadir.mkdir(parents=True, exist_ok=True)
        self.rpc_port = _free_port()
        self.url = f"http://127.0.0.1:{self.rpc_port}"
        self.proc = subprocess.Popen(
            [
                bitcoind,
                "-regtest",
                f"-datadir={datadir}",
                f"-rpcport={self.rpc_port}",
                f"-port={_free_port()}",
                "-rpcuser=u",
                "-rpcpassword=p",
                "-fallbackfee=0.0002",
                "-listen=0",
                "-server=1",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(100):
            try:
                self.call("getblockchaininfo")
                return
            except Exception:
                time.sleep(0.2)
        raise RuntimeError("bitcoind did not start")

    def call(self, method: str, *params, wallet: str | None = None):
        url = f"{self.url}/wallet/{wallet}" if wallet else self.url
        body = json.dumps({"jsonrpc": "1.0", "id": method, "method": method, "params": list(params)})
        req = urllib.request.Request(url, data=body.encode(), headers={"Content-Type": "application/json"})
        req.add_header("Authorization", "Basic " + base64.b64encode(b"u:p").decode())
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            data = json.loads(exc.read())
        if data.get("error"):
            raise RuntimeError(data["error"])
        return data["result"]

    def stop(self) -> None:
        try:
            self.call("stop")
            self.proc.wait(timeout=30)
        except Exception:
            self.proc.kill()


def main() -> int:
    bitcoind = os.environ.get("BITCOIND") or shutil.which("bitcoind")
    if not bitcoind:
        print("set BITCOIND=/path/to/bitcoind")
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="signer-regtest-"))
    node = Node(bitcoind, tmp / "node")
    try:
        return _scenario(node, tmp)
    finally:
        node.stop()
        shutil.rmtree(tmp, ignore_errors=True)


def _scenario(node: Node, tmp: Path) -> int:
    os.environ.update(
        {
            "SIGNER_SECRET_KEY": SECRET,
            "DRY_RUN": "false",
            "AUDIT_PATH": str(tmp / "state" / "audit.log"),
            "BTC_RPC_URL": node.url,
            "BTC_RPC_USER": "u",
            "BTC_RPC_PASSWORD": "p",
            "BTC_RPC_WALLET": "hot",
            "TRUSTED_TOPUPS_ENABLED": "true",
            "TRUSTED_TOPUP_MAX_BTC": "0.06",
            # Выше fallback-ставки regtest (2 sat/vB), чтобы проверить именно порог.
            "BTC_MIN_FEE_RATE_SAT_VB": "3",
            "MAX_TX_BTC": "0.05",
            "DAILY_CAP_BTC": "1",
        }
    )
    sys.path.insert(0, str(ROOT))
    import store

    store.restore_empty_tables_from_backup = lambda *a, **k: {"deposits": 0, "payouts": 0}
    from fastapi.testclient import TestClient

    import main as signer
    from policy import PolicyDecision

    # Политика пропускает только mainnet-адреса, в regtest они bcrt1…
    signer.validate_address = lambda coin, address: PolicyDecision(address.startswith("bcrt1"))
    logging.getLogger("wallet_rpc").setLevel(logging.ERROR)

    client = TestClient(signer.app)
    client.__enter__()

    def api(method: str, path: str, body: dict | None = None) -> dict:
        raw = json.dumps(body, separators=(",", ":")) if body is not None else ""
        ts = str(int(time.time()))
        sig = hmac.new(SECRET.encode(), ts.encode() + raw.encode(), hashlib.sha256).hexdigest()
        headers = {"X-API-Key": "focuspay-main", "X-Timestamp": ts, "X-Signature": sig,
                   "Content-Type": "application/json"}
        resp = client.request(method, path, content=raw.encode(), headers=headers)
        time.sleep(0.01)
        return resp.json()

    failures: list[str] = []

    def check(name: str, ok: bool, detail: object = "") -> None:
        print(("PASS " if ok else "FAIL ") + name + ("" if ok else f" -> {detail}"))
        if not ok:
            failures.append(name)

    node.call("createwallet", "owner")
    node.call("createwallet", "hot")
    node.call("createwallet", "client")
    mine_to = node.call("getnewaddress", wallet="owner")
    node.call("generatetoaddress", 101, mine_to)
    hot_addr = node.call("getnewaddress", "", "bech32", wallet="hot")
    payee = node.call("getnewaddress", wallet="client")

    def payout(rid: str, amount: float) -> dict:
        return api("POST", "/v1/payouts", {"request_id": rid, "coin": "btc", "address": payee, "amount": amount})

    def btc_balance() -> dict:
        return api("GET", "/v1/balance")["coins"]["btc"]

    def in_mempool(txid: str) -> bool:
        try:
            node.call("getmempoolentry", txid)
            return True
        except RuntimeError:
            return False

    # 1. Пополнение с 0 подтверждений без доверия: подписант не тратит.
    top_a = node.call("sendtoaddress", hot_addr, 0.05, wallet="owner")
    r = payout("order:t1", 0.01)
    check("untrusted topup is not spent", r.get("status") == "rejected" and r.get("reason") == "insufficient_funds", r)
    bal = btc_balance()
    check("balance shows pending topup", bal["spendable"] == 0 and abs(bal["unconfirmed"] - 0.05) < 1e-8, bal)
    check("no fast balance before trust", bal["spendable_fast"] == 0, bal)

    # 2. Доверие и выплаты сразу.
    r = api("POST", "/v1/topups/trust", {"coin": "btc", "txid": top_a, "note": "regtest"})
    check("trust topup", r.get("ok") is True and abs(r.get("amount", 0) - 0.05) < 1e-8, r)
    bal = btc_balance()
    check("fast balance after trust", abs(bal["spendable_fast"] - 0.05) < 1e-8, bal)
    sent = []
    for rid in ("order:t2", "order:t3", "order:t4"):
        r = payout(rid, 0.01)
        check(f"{rid} sent before confirmation", r.get("status") == "accepted" and in_mempool(r.get("txid", "")), r)
        sent.append(r.get("txid"))
    if not all(sent):
        print("\nFAILED: payouts did not go out, stopping")
        return 1
    first = node.call("getrawtransaction", sent[0], True)
    check("first payout spends the topup", any(v["txid"] == top_a for v in first["vin"]), first["vin"])
    second = node.call("getrawtransaction", sent[1], True)
    check("next payout chains from our change", any(v["txid"] == sent[0] for v in second["vin"]), second["vin"])
    pkg = node.call("getmempoolentry", top_a)
    check("payouts pay for the topup (CPFP package)", pkg.get("descendantcount", 0) >= 4, pkg)
    shown = api("GET", "/v1/fee-estimate?coin=btc").get("feerate_sat_vb")
    entry = node.call("getmempoolentry", sent[1])
    paid = entry["fees"]["base"] * 1e8 / entry["vsize"]
    check("payout pays the shown fee rate", shown and abs(paid - float(shown)) < 0.1, {"shown": shown, "paid": paid})

    # 3. Лимит неподтверждённых доверенных пополнений.
    top_b = node.call("sendtoaddress", hot_addr, 0.02, wallet="owner")
    r = api("POST", "/v1/topups/trust", {"coin": "btc", "txid": top_b})
    check("cap on pending trusted topups", r.get("ok") is False and r.get("reason") == "cap_exceeded", r)
    r = api("POST", "/v1/topups/trust", {"coin": "btc", "txid": "ab" * 32})
    check("unknown txid rejected", r.get("reason") == "not_in_wallet", r)

    # 4. Блок: всё подтверждено.
    node.call("generatetoaddress", 1, mine_to)
    items = {i["txid"]: i for i in api("GET", "/v1/topups?coin=btc")["items"]}
    check("topup confirmed", items.get(top_a, {}).get("status") == "confirmed", items)
    r = api("POST", "/v1/topups/trust", {"coin": "btc", "txid": top_a})
    check("confirmed topup needs no trust", r.get("reason") == "already_confirmed", r)
    tx = node.call("gettransaction", sent[-1], wallet="hot")
    check("payouts confirmed", tx["confirmations"] == 1, tx["confirmations"])

    # 5. Пополнение заменили: выплата из него пропадает, статус виден.
    spendable = btc_balance()["spendable"]
    top_c = node.call("sendtoaddress", hot_addr, 0.03, wallet="owner")
    r = api("POST", "/v1/topups/trust", {"coin": "btc", "txid": top_c})
    check("trust second topup", r.get("ok") is True, r)
    amount = round(spendable + 0.01, 8)
    r = payout("order:t5", amount)
    child = r.get("txid", "")
    check("payout bigger than confirmed balance goes out", r.get("status") == "accepted" and in_mempool(child), r)
    try:
        node.call("bumpfee", top_c, {"fee_rate": 80}, wallet="owner")
        check("core refuses to bump a topup with payouts on top", False, "bumpfee went through")
    except RuntimeError as exc:
        check("core refuses to bump a topup with payouts on top", "descendants" in str(exc), exc)
    # Замена в обход кошелька: те же входы, всё себе, комиссия выше всего пакета.
    parent = node.call("getrawtransaction", top_c, True)
    total = 0.0
    for vin in parent["vin"]:
        prev = node.call("gettransaction", vin["txid"], True, True, wallet="owner")
        total += prev["decoded"]["vout"][vin["vout"]]["value"]
    back = node.call("getnewaddress", wallet="owner")
    raw = node.call(
        "createrawtransaction",
        [{"txid": v["txid"], "vout": v["vout"]} for v in parent["vin"]],
        [{back: round(total - 0.002, 8)}],
    )
    signed = node.call("signrawtransactionwithwallet", raw, wallet="owner")
    node.call("sendrawtransaction", signed["hex"])
    items = {i["txid"]: i for i in api("GET", "/v1/topups?coin=btc")["items"]}
    check("replaced topup reported", items.get(top_c, {}).get("status") in ("dropped", "conflicted"), items.get(top_c))
    check("child payout evicted with its parent", not in_mempool(child), child)
    node.call("generatetoaddress", 1, mine_to)
    items = {i["txid"]: i for i in api("GET", "/v1/topups?coin=btc")["items"]}
    check("replaced topup conflicted after block", items.get(top_c, {}).get("status") == "conflicted", items.get(top_c))

    # 6. Длинная очередь из одного неподтверждённого пополнения: где упираемся в лимит mempool.
    top_d = node.call("sendtoaddress", hot_addr, 0.05, wallet="owner")
    r = api("POST", "/v1/topups/trust", {"coin": "btc", "txid": top_d})
    check("trust third topup", r.get("ok") is True, r)
    statuses: list[dict] = []
    for i in range(80):
        r = payout(f"order:chain{i}", 0.0005)
        statuses.append(r)
        if r.get("status") != "accepted":
            break
    went = sum(1 for r in statuses if r.get("status") == "accepted")
    last = statuses[-1]
    print(f"      chain: {went} payouts before the limit, then {last.get('status')} / {last.get('reason')}")
    check(
        "chain limit is a definite reject, not unknown",
        last.get("status") == "accepted" or last.get("reason") in ("mempool_chain_limit", "insufficient_funds"),
        last,
    )

    client.__exit__(None, None, None)
    print(f"\n{'OK' if not failures else 'FAILED'}: {len(failures)} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
