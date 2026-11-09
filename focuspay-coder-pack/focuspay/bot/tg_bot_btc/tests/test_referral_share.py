"""Тесты единого резолвера реферальных ссылок и dual-write атрибуции."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.referral_links import (
    telegram_start_payload,
    user_referral_start_payload,
)
from services.referral_share import (
    ensure_promo_attribution_for_partner_referrer,
    resolve_share_links,
)


class ResolveShareLinksTests(unittest.IsolatedAsyncioTestCase):
    async def test_user_gets_ref_link(self):
        """Единая ссылка: обычный пользователь тоже получает ref_ + /ref/."""
        with patch(
            "services.referral_share._partner_share_row",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "services.user_referral_db.get_canonical_ref_token",
            new_callable=AsyncMock,
            return_value="abc123xyz789012345",
        ):
            share = await resolve_share_links(1001)

        self.assertEqual(share["kind"], "user")
        self.assertEqual(share["ref_token"], "abc123xyz789012345")
        self.assertIn("ref_abc123xyz789012345", share["telegram_link"])
        self.assertIn("/ref/abc123xyz789012345", share["web_link"])
        self.assertNotIn("uref_", share["telegram_link"])
        self.assertNotIn("/invite/", share["web_link"])

    async def test_partner_gets_ref_link(self):
        partner_row = {
            "ref_token": "mlfxj60ppldbrlk91a",
            "campaign_code": "PROMO123",
        }
        with patch(
            "services.referral_share._partner_share_row",
            new_callable=AsyncMock,
            return_value=partner_row,
        ), patch(
            "services.user_referral_db.get_canonical_ref_token",
            new_callable=AsyncMock,
            return_value="mlfxj60ppldbrlk91a",
        ):
            share = await resolve_share_links(2002)

        self.assertEqual(share["kind"], "partner")
        self.assertEqual(share["ref_token"], "mlfxj60ppldbrlk91a")
        self.assertIn(
            telegram_start_payload("mlfxj60ppldbrlk91a"),
            share["telegram_link"],
        )
        self.assertIn("/ref/mlfxj60ppldbrlk91a", share["web_link"])
        self.assertNotIn("uref_", share["telegram_link"])


class PartnerPromoAttributionTests(unittest.IsolatedAsyncioTestCase):
    async def test_ensure_promo_attribution_inserts_when_partner(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"promo_code": "PARTNER1"}
        conn.execute.return_value = "INSERT 0 1"

        ok = await ensure_promo_attribution_for_partner_referrer(conn, 3003, 2002)
        self.assertTrue(ok)
        conn.execute.assert_called_once()

    async def test_ensure_promo_attribution_skips_non_partner(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None

        ok = await ensure_promo_attribution_for_partner_referrer(conn, 3003, 2002)
        self.assertFalse(ok)
        conn.execute.assert_not_called()

    async def test_assign_referrer_dual_writes_promo_for_partner(self):
        from services.user_referral_attribution import assign_referrer_by_token

        conn = AsyncMock()
        conn.fetchrow.return_value = {"user_id": 2002}
        conn.fetchval.return_value = False
        conn.execute.return_value = "INSERT 0 1"

        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("services.user_referral_attribution.get_pool", new_callable=AsyncMock, return_value=pool), patch(
            "services.referral_share.ensure_promo_attribution_for_partner_referrer",
            new_callable=AsyncMock,
            return_value=True,
        ) as promo_write, patch(
            "services.partner_auto_upgrade.maybe_auto_upgrade_referrer",
            new_callable=AsyncMock,
        ):
            result = await assign_referrer_by_token(3003, "abc123xyz789012345")

        self.assertEqual(result, "applied")
        promo_write.assert_awaited_once_with(conn, 3003, 2002)


class StashPendingRefTokenTests(unittest.IsolatedAsyncioTestCase):
    async def test_stash_saves_valid_token(self):
        from services.user_referral_attribution import stash_pending_ref_token_from_payload

        conn = AsyncMock()
        conn.fetchval.side_effect = [False, False, 2002]
        conn.execute.return_value = "UPDATE 1"

        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "services.user_referral_attribution.get_pool",
            new_callable=AsyncMock,
            return_value=pool,
        ):
            ok = await stash_pending_ref_token_from_payload(
                3003, "https://t.me/focuspay1_bot?start=uref_abc123xyz789012345"
            )

        self.assertTrue(ok)
        self.assertGreaterEqual(conn.execute.await_count, 1)
        update_call = [
            c for c in conn.execute.await_args_list
            if "pending_ref_token" in str(c.args[0])
        ]
        self.assertEqual(len(update_call), 1)
        self.assertEqual(update_call[0].args[2], "abc123xyz789012345")

    async def test_stash_saves_canonical_ref_prefix(self):
        """Share links use ref_ — stash must accept them (captcha path)."""
        from services.user_referral_attribution import stash_pending_ref_token_from_payload

        conn = AsyncMock()
        conn.fetchval.side_effect = [False, False, 2002]
        conn.execute.return_value = "UPDATE 1"

        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "services.user_referral_attribution.get_pool",
            new_callable=AsyncMock,
            return_value=pool,
        ):
            ok = await stash_pending_ref_token_from_payload(
                3003, "ref_sbfmqtel5mgrlgn2r9"
            )

        self.assertTrue(ok)
        update_call = [
            c for c in conn.execute.await_args_list
            if "pending_ref_token" in str(c.args[0])
        ]
        self.assertEqual(len(update_call), 1)
        self.assertEqual(update_call[0].args[2], "sbfmqtel5mgrlgn2r9")

    async def test_stash_skips_locked_user(self):
        from services.user_referral_attribution import stash_pending_ref_token_from_payload

        with patch(
            "services.user_referral_attribution._is_referral_locked",
            new_callable=AsyncMock,
            return_value=True,
        ):
            ok = await stash_pending_ref_token_from_payload(3003, "uref_abc123xyz789012345")

        self.assertFalse(ok)


class ReferralPayloadPrefixTests(unittest.TestCase):
    def test_prefixes_differ(self):
        token = "testtoken123456789"
        self.assertTrue(user_referral_start_payload(token).startswith("uref_"))
        self.assertTrue(telegram_start_payload(token).startswith("ref_"))


if __name__ == "__main__":
    unittest.main()
