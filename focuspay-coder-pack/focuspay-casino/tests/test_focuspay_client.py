import json
import unittest

import httpx

import focuspay_client
from focuspay_client import FocusPayClient


class FocusPayClientSettlementTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_base_url_uses_canonical_public_origin(self):
        client = FocusPayClient(http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200))))
        try:
            self.assertEqual(client.base_url, "https://focuspay.org")
        finally:
            await client.close()

    async def test_settle_committed_outcome_request_contract(self):
        captured_request = None

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_request
            captured_request = request
            return httpx.Response(200, json={"success": True, "game": {"status": "finished", "state_version": 7}})

        transport = httpx.MockTransport(handler)
        http_client = httpx.AsyncClient(transport=transport)
        client = FocusPayClient(
            base_url="https://focuspay.test/",
            internal_token="internal-secret",
            http_client=http_client,
        )

        try:
            result = await client.settle_committed_outcome(game_id="pvp-123")
        finally:
            await client.close()

        self.assertEqual(result, {"success": True, "game": {"status": "finished", "state_version": 7}})
        self.assertIsNotNone(captured_request)
        self.assertEqual(
            str(captured_request.url),
            "https://focuspay.test/api/internal/casino/games/settle-committed-outcome",
        )
        self.assertEqual(captured_request.headers["X-Internal-Token"], "internal-secret")
        self.assertEqual(json.loads(captured_request.content), {"game_id": "pvp-123"})
    async def test_game_chat_binding_contracts(self):
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path.endswith("/active"):
                return httpx.Response(200, json={"success": True, "binding": None})
            return httpx.Response(200, json={"success": True, "binding": {"chat_id": -100123}})

        client = FocusPayClient(
            base_url="https://focuspay.test",
            internal_token="internal-secret",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        try:
            self.assertIsNone(await client.get_active_game_chat_binding())
            result = await client.create_pending_game_chat_binding(
                chat_id=-100123,
                chat_type="supergroup",
                chat_title="Games",
                requested_by_telegram_id=7,
            )
        finally:
            await client.close()

        self.assertEqual(result["binding"]["chat_id"], -100123)
        self.assertEqual(
            [request.url.path for request in requests],
            [
                "/api/internal/casino/chat-binding/active",
                "/api/internal/casino/chat-binding/pending",
            ],
        )
        self.assertEqual(
            json.loads(requests[1].content),
            {"chat_id": -100123, "chat_type": "supergroup", "chat_title": "Games", "telegram_url": None, "requested_by_telegram_id": 7},
        )
    async def test_dm_pvp_invitation_contracts(self):
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"success": True, "items": []})

        client = FocusPayClient(
            base_url="https://focuspay.test",
            internal_token="internal-secret",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        try:
            await client.create_pvp_game_from_dm(
                game_id="game-1", game_type="pvp_dice", creator_id=7, stake_rub="12.5", rounds=2,
            )
            await client.claim_pvp_invitations(worker_id="worker", limit=3, lease_seconds=45)
            await client.complete_pvp_invitation(outbox_id=8, claim_token="claim", telegram_message_id=9)
            await client.fail_pvp_invitation(outbox_id=8, claim_token="claim", error="send failed")
        finally:
            await client.close()

        self.assertEqual([request.url.path for request in requests], [
            "/api/internal/casino/games/create-from-dm",
            "/api/internal/casino/pvp-invitations/claim",
            "/api/internal/casino/pvp-invitations/complete",
            "/api/internal/casino/pvp-invitations/fail",
        ])
        self.assertEqual(json.loads(requests[0].content), {
            "game_id": "game-1", "game_type": "pvp_dice", "creator_id": 7,
            "stake_rub": "12.50", "rounds": 2, "publish_to_group": False,
        })
        self.assertEqual(json.loads(requests[1].content), {"worker_id": "worker", "limit": 3, "lease_seconds": 45})
        self.assertEqual(json.loads(requests[2].content), {"outbox_id": 8, "claim_token": "claim", "telegram_message_id": 9})
        self.assertEqual(json.loads(requests[3].content), {"outbox_id": 8, "claim_token": "claim", "error": "send failed"})

    async def test_profile_contract(self):
        captured_request = None

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_request
            captured_request = request
            return httpx.Response(200, json={"telegram_id": 77, "available_rub": "100.00"})

        client = FocusPayClient(
            base_url="https://focuspay.test",
            internal_token="internal-secret",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        try:
            result = await client.get_profile(telegram_id=77)
        finally:
            await client.close()

        self.assertEqual(result["telegram_id"], 77)
        self.assertEqual(captured_request.url.path, "/api/internal/casino/users/77/profile")
        self.assertEqual(captured_request.headers["X-Internal-Token"], "internal-secret")

    async def test_profile_avatar_contract_and_not_found_fallback(self):
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(404) if len(requests) == 1 else httpx.Response(
                200,
                content=b"\x89PNG\r\n\x1a\n" + b"x" * 64,
                headers={"content-type": "image/png"},
            )

        client = FocusPayClient(
            base_url="https://focuspay.test",
            internal_token="internal-secret",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        try:
            self.assertIsNone(await client.get_profile_avatar(telegram_id=77))
            self.assertTrue((await client.get_profile_avatar(telegram_id=77)).startswith(b"\x89PNG"))
        finally:
            await client.close()

        self.assertEqual(
            [request.url.path for request in requests],
            [
                "/api/internal/casino/users/77/avatar",
                "/api/internal/casino/users/77/avatar",
            ],
        )
        self.assertTrue(all(request.headers["X-Internal-Token"] == "internal-secret" for request in requests))

    async def test_prepare_and_play_cub_contracts(self):
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path.endswith("/prepare"):
                return httpx.Response(200, json={"success": True, "game_id": "cub-1", "rng_commit": "a" * 64})
            return httpx.Response(200, json={"success": True, "game_id": "cub-1"})

        client = FocusPayClient(
            base_url="https://focuspay.test",
            internal_token="internal-secret",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        try:
            commitment = await client.prepare_cub(telegram_id=77)
            played = await client.play_cub(game_id=commitment["game_id"], telegram_id=77, stake_rub="12.5")
        finally:
            await client.close()

        self.assertEqual(played["game_id"], "cub-1")
        self.assertEqual([request.url.path for request in requests], [
            "/api/internal/casino/cub/prepare",
            "/api/internal/casino/cub/play",
        ])
        self.assertEqual(json.loads(requests[0].content), {"telegram_id": 77})
        self.assertEqual(json.loads(requests[1].content), {"game_id": "cub-1", "telegram_id": 77, "stake_rub": "12.50"})

    async def test_open_resolve_and_pending_cub_contracts(self):
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path.endswith("/open"):
                return httpx.Response(
                    200,
                    json={"success": True, "game_id": "cub-1", "status": "waiting_player_roll", "already_open": False},
                )
            if request.url.path.endswith("/pending"):
                return httpx.Response(200, json={"success": True, "pending": {"game_id": "cub-1"}})
            return httpx.Response(
                200,
                json={"success": True, "tie": False, "game_id": "cub-1", "payout_rub": "199.00"},
            )

        client = FocusPayClient(
            base_url="https://focuspay.test",
            internal_token="internal-secret",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        try:
            opened = await client.open_cub(telegram_id=77, stake_rub="12.5")
            pending = await client.get_pending_cub(telegram_id=77)
            resolved = await client.resolve_cub(
                game_id=opened["game_id"], telegram_id=77, player_value=6, house_value=5
            )
        finally:
            await client.close()

        self.assertEqual(pending["pending"]["game_id"], "cub-1")
        self.assertEqual(resolved["payout_rub"], "199.00")
        self.assertEqual(
            [request.url.path for request in requests],
            [
                "/api/internal/casino/cub/open",
                "/api/internal/casino/cub/pending",
                "/api/internal/casino/cub/resolve",
            ],
        )
        self.assertEqual(json.loads(requests[0].content), {"telegram_id": 77, "stake_rub": "12.50"})
        self.assertEqual(requests[1].url.params["telegram_id"], "77")
        self.assertEqual(
            json.loads(requests[2].content),
            {"game_id": "cub-1", "telegram_id": 77, "player_value": 6, "house_value": 5},
        )

    async def test_prepare_deal_and_reveal_card_contracts(self):
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            path = request.url.path
            if path.endswith("/cards/prepare"):
                return httpx.Response(200, json={"success": True, "game_id": "baccara-1", "rng_commit": "a" * 64})
            if path.endswith("/cards/deal"):
                return httpx.Response(200, json={"success": True, "cards": ["A♠", "9♥"], "hand_size": 2})
            return httpx.Response(200, json={"success": True, "rng_seed": "ab" * 32, "rng_commit": "a" * 64})

        client = FocusPayClient(
            base_url="https://focuspay.test",
            internal_token="internal-secret",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        try:
            prepared = await client.prepare_cards(game_id="baccara-1", game_type="baccara", telegram_id=11)
            dealt = await client.deal_cards(game_id="baccara-1", telegram_id=11, hand_size=2)
            revealed = await client.reveal_cards(game_id="baccara-1", telegram_id=11)
        finally:
            await client.close()

        self.assertEqual(prepared["rng_commit"], "a" * 64)
        self.assertEqual(dealt["cards"], ["A♠", "9♥"])
        self.assertEqual(revealed["rng_seed"], "ab" * 32)
        self.assertEqual(
            [request.url.path for request in requests],
            [
                "/api/internal/casino/cards/prepare",
                "/api/internal/casino/cards/deal",
                "/api/internal/casino/cards/reveal",
            ],
        )
        self.assertEqual(
            json.loads(requests[0].content),
            {"game_id": "baccara-1", "game_type": "baccara", "telegram_id": 11},
        )
        self.assertEqual(
            json.loads(requests[1].content),
            {"game_id": "baccara-1", "telegram_id": 11, "hand_size": 2},
        )
        self.assertEqual(
            json.loads(requests[2].content),
            {"game_id": "baccara-1", "telegram_id": 11},
        )


class FocusPayClientLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await focuspay_client.close_focuspay_client()

    async def asyncTearDown(self):
        await focuspay_client.close_focuspay_client()

    async def test_close_singleton_closes_and_clears_client(self):
        client = await focuspay_client.get_focuspay_client()

        await focuspay_client.close_focuspay_client()

        self.assertTrue(client.client.is_closed)
        self.assertIsNone(focuspay_client._client)

    async def test_next_singleton_after_close_is_fresh(self):
        first = await focuspay_client.get_focuspay_client()
        await focuspay_client.close_focuspay_client()

        second = await focuspay_client.get_focuspay_client()

        self.assertIsNot(first, second)
        self.assertFalse(second.client.is_closed)


class FocusPayClientDurableLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_durable_lifecycle_and_worker_contracts(self):
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"success": True, "items": []})

        client = FocusPayClient(
            base_url="https://focuspay.test",
            internal_token="internal-secret",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        try:
            await client.create_or_resume_game(
                game_id="game-1", game_type="pvp_dice", creator_id=11, stake_rub="10"
            )
            await client.join_and_hold_game(game_id="game-1", opponent_id=22)
            await client.persist_game_state(
                game_id="game-1", expected_state_version=3, game_state={"phase": "active"}
            )
            await client.record_pvp_dice_roll(game_id="game-1", telegram_id=11, value=6)
            await client.commit_game_outcome(
                game_id="game-1",
                winner_id=11,
                expected_state_version=4,
                outcome={"kind": "winner"},
            )
            await client.settle_committed_outcome(game_id="game-1")
            await client.claim_recovery_jobs(worker_id="worker-1")
            await client.complete_recovery_job(game_id="game-1", claim_token="lease-1")
            await client.claim_outbox_messages(worker_id="worker-1")
            await client.complete_outbox_message(outbox_id=7, claim_token="lease-2")
            await client.fail_outbox_message(outbox_id=7, claim_token="lease-2", error="telegram down")
        finally:
            await client.close()

        self.assertEqual(
            [request.url.path for request in requests],
            [
                "/api/internal/casino/games/create-or-resume",
                "/api/internal/casino/games/join-and-hold",
                "/api/internal/casino/games/persist-state",
                "/api/internal/casino/games/record-roll",
                "/api/internal/casino/games/commit-outcome",
                "/api/internal/casino/games/settle-committed-outcome",
                "/api/internal/casino/recovery/claim",
                "/api/internal/casino/recovery/complete",
                "/api/internal/casino/outbox/claim",
                "/api/internal/casino/outbox/complete",
                "/api/internal/casino/outbox/fail",
            ],
        )
        payloads = [json.loads(request.content) for request in requests]
        self.assertEqual(
            payloads,
            [
                {"game_id": "game-1", "game_type": "pvp_dice", "creator_id": 11, "stake_rub": "10.00"},
                {"game_id": "game-1", "opponent_id": 22},
                {"game_id": "game-1", "expected_state_version": 3, "game_state": {"phase": "active"}},
                {"game_id": "game-1", "telegram_id": 11, "value": 6},
                {"game_id": "game-1", "winner_id": 11, "expected_state_version": 4, "outcome": {"kind": "winner"}},
                {"game_id": "game-1"},
                {"worker_id": "worker-1", "limit": 50, "lease_seconds": 60},
                {"game_id": "game-1", "claim_token": "lease-1"},
                {"worker_id": "worker-1", "limit": 50, "lease_seconds": 60},
                {"outbox_id": 7, "claim_token": "lease-2"},
                {
                    "outbox_id": 7,
                    "claim_token": "lease-2",
                    "error": "telegram down",
                    "error_kind": "temporary",
                    "retry_after_seconds": None,
                },
            ],
        )

    async def test_recovery_snapshot_is_read_only_get(self):
        captured_request = None

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_request
            captured_request = request
            return httpx.Response(200, json={"success": True, "items": []})

        client = FocusPayClient(
            base_url="https://focuspay.test",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        try:
            self.assertEqual(await client.get_recovery_snapshot(), {"success": True, "items": []})
        finally:
            await client.close()



    async def test_roulette_table_internal_contracts(self):
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.method == "GET":
                return httpx.Response(200, json={"success": True, "status": "open", "closes_at": None})
            return httpx.Response(200, json={"success": True, "status": "open", "player_count": 1})

        client = FocusPayClient(
            base_url="https://focuspay.test",
            internal_token="internal-secret",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        try:
            snap = await client.get_roulette_table(telegram_id=77)
            placed = await client.place_roulette_table_bet(
                telegram_id=77,
                notify_chat_id=-1001,
                chips=[{"bet": "1", "amount_rub": "10.00"}, {"bet": "4", "amount_rub": "10.00"}],
            )
        finally:
            await client.close()

        self.assertEqual(snap["status"], "open")
        self.assertEqual(placed["player_count"], 1)
        self.assertEqual(requests[0].url.path, "/api/internal/casino/roulette-table")
        self.assertEqual(requests[0].url.params["telegram_id"], "77")
        self.assertEqual(requests[1].url.path, "/api/internal/casino/roulette-table/bet")
        self.assertEqual(requests[1].headers["X-Internal-Token"], "internal-secret")
        self.assertEqual(
            json.loads(requests[1].content),
            {
                "telegram_id": 77,
                "notify_chat_id": -1001,
                "chips": [{"bet": "1", "amount_rub": "10.00"}, {"bet": "4", "amount_rub": "10.00"}],
            },
        )


    async def test_jackpot_internal_contracts(self):
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.method == "GET":
                return httpx.Response(200, json={"success": True, "status": "open", "pot_rub": 0})
            return httpx.Response(200, json={"success": True, "status": "open", "player_count": 1})

        client = FocusPayClient(
            base_url="https://focuspay.test",
            internal_token="internal-secret",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        try:
            snap = await client.get_jackpot(telegram_id=77)
            placed = await client.place_jackpot_bet(
                telegram_id=77,
                notify_chat_id=-1001,
                amount_rub="100",
            )
        finally:
            await client.close()

        self.assertEqual(snap["status"], "open")
        self.assertEqual(placed["player_count"], 1)
        self.assertEqual(requests[0].url.path, "/api/internal/casino/jackpot")
        self.assertEqual(requests[0].url.params["telegram_id"], "77")
        self.assertEqual(requests[1].url.path, "/api/internal/casino/jackpot/bet")
        self.assertEqual(requests[1].headers["X-Internal-Token"], "internal-secret")
        self.assertEqual(
            json.loads(requests[1].content),
            {
                "telegram_id": 77,
                "notify_chat_id": -1001,
                "amount_rub": "100.00",
            },
        )


    async def test_fixed_rooms_internal_contracts(self):
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.method == "GET" and request.url.path.endswith("/rooms"):
                return httpx.Response(200, json={"success": True, "rooms": []})
            if request.method == "GET":
                return httpx.Response(200, json={"success": True, "room_id": "fr-aabbccddeeff"})
            return httpx.Response(200, json={"success": True, "room_id": "fr-aabbccddeeff", "filled": 1})

        client = FocusPayClient(
            base_url="https://focuspay.test",
            internal_token="internal-secret",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        try:
            listed = await client.list_fixed_rooms(telegram_id=77)
            created = await client.create_fixed_room(
                telegram_id=77, stake_rub="100", seat_count=3
            )
            joined = await client.join_fixed_room("fr-aabbccddeeff", telegram_id=88)
        finally:
            await client.close()

        self.assertEqual(listed["rooms"], [])
        self.assertEqual(created["room_id"], "fr-aabbccddeeff")
        self.assertEqual(joined["filled"], 1)
        self.assertEqual(requests[0].url.path, "/api/internal/casino/rooms")
        self.assertEqual(requests[0].url.params["telegram_id"], "77")
        self.assertEqual(requests[1].url.path, "/api/internal/casino/rooms")
        self.assertEqual(requests[1].headers["X-Internal-Token"], "internal-secret")
        self.assertEqual(
            json.loads(requests[1].content),
            {"telegram_id": 77, "stake_rub": "100.00", "seat_count": 3},
        )
        self.assertEqual(requests[2].url.path, "/api/internal/casino/rooms/fr-aabbccddeeff/join")
        self.assertEqual(json.loads(requests[2].content), {"telegram_id": 88})


if __name__ == "__main__":
    unittest.main()
