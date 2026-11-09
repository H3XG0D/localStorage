"""Campaign referral survives captcha and loss of in-memory user_data."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from services import user_referral_attribution as refs
from services import promo_attribution

TOKEN = '8kl399pqltfsr440a7'

class PartnerCaptchaTests(unittest.IsolatedAsyncioTestCase):
    async def test_campaign_token_survives_until_after_captcha(self):
        conn = AsyncMock()
        pending = None
        async def fetchval(sql, *args):
            if 'SELECT pending_ref_token' in sql:
                return pending
            if 'SELECT user_id FROM bot_users' in sql:
                return None
            return False
        async def execute(sql, *args):
            nonlocal pending
            if 'SET pending_ref_token = $2' in sql:
                pending = args[1]
            elif 'SET pending_ref_token = NULL' in sql:
                pending = None
            return 'UPDATE 1'
        conn.fetchval.side_effect = fetchval
        conn.execute.side_effect = execute
        conn.fetchrow.return_value = None
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.object(refs, 'get_pool', AsyncMock(return_value=pool)),
            patch('services.db.get_active_promo_campaign_by_ref_token', AsyncMock(return_value={'code': 'PRXORKTA', 'campaign_kind': 'partner'})),
            patch('services.promo_attribution.get_active_promo_campaign_by_ref_token', AsyncMock(return_value={'code': 'PRXORKTA', 'campaign_kind': 'partner'})),
            patch('services.promo_attribution.assign_promo_to_user_if_first', AsyncMock(return_value=True)) as assign,
        ):
            self.assertTrue(await refs.stash_pending_ref_token_from_payload(900575493, 'ref_' + TOKEN))
            self.assertEqual(pending, TOKEN)
            # No Telegram context survives here: reload solely from database.
            self.assertEqual(await refs.apply_pending_ref_token_if_any(900575493), 'applied')
            assign.assert_awaited_once_with(900575493, 'PRXORKTA')
            self.assertIsNone(pending)

    async def test_locked_pending_does_not_apply_campaign(self):
        conn = AsyncMock()
        conn.fetchval.return_value = TOKEN
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.object(refs, 'get_pool', AsyncMock(return_value=pool)),
            patch.object(refs, 'assign_referrer_by_token', AsyncMock(return_value='locked')),
            patch('services.promo_attribution.apply_promo_from_start_payload', AsyncMock()) as apply,
        ):
            self.assertEqual(await refs.apply_pending_ref_token_if_any(42), 'locked')
            apply.assert_not_awaited()
