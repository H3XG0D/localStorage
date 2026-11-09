import unittest

from services.referral_links import (
    extract_any_ref_token,
    extract_referral_token_from_text,
    extract_user_referral_token,
    parse_user_referral_payload,
    strip_ref_prefixes,
)


class ReferralLinkExtractTests(unittest.TestCase):
    def test_uref_payload(self):
        self.assertEqual(parse_user_referral_payload("uref_abc123xyz789012345"), "abc123xyz789012345")

    def test_bare_token(self):
        self.assertEqual(extract_user_referral_token("abc123xyz789012345"), "abc123xyz789012345")

    def test_rejects_partner_ref(self):
        self.assertIsNone(extract_user_referral_token("ref_abc123xyz789012345"))

    def test_tme_link_in_chat(self):
        url = "https://t.me/focuspay1_bot?start=uref_abc123xyz789012345"
        self.assertEqual(extract_referral_token_from_text(url), "abc123xyz789012345")

    def test_tme_link_bare_start(self):
        url = "https://t.me/focuspay1_bot?start=abc123xyz789012345"
        self.assertEqual(extract_referral_token_from_text(url), "abc123xyz789012345")

    def test_start_command_text(self):
        self.assertEqual(
            extract_referral_token_from_text("/start uref_abc123xyz789012345"),
            "abc123xyz789012345",
        )

    def test_tg_resolve_link(self):
        url = "tg://resolve?domain=focuspay1_bot&start=uref_abc123xyz789012345"
        self.assertEqual(extract_referral_token_from_text(url), "abc123xyz789012345")

    def test_web_invite_path(self):
        self.assertEqual(
            extract_referral_token_from_text("https://focuspay.org/invite/abc123xyz789012345"),
            "abc123xyz789012345",
        )

    def test_ignores_partner_tme(self):
        # Unified: ref_ share links are accepted from chat paste too.
        url = "https://t.me/focuspay1_bot?start=ref_partner123456789"
        self.assertEqual(extract_referral_token_from_text(url), "partner123456789")

    def test_ref_start_command(self):
        self.assertEqual(
            extract_referral_token_from_text("/start ref_abc123xyz789012345"),
            "abc123xyz789012345",
        )

    def test_ref_path(self):
        self.assertEqual(
            extract_referral_token_from_text("https://focuspay.org/ref/abc123xyz789012345"),
            "abc123xyz789012345",
        )

    def test_bare_text_not_token(self):
        self.assertIsNone(extract_referral_token_from_text("just some chat message"))


class UnifiedRefTokenTests(unittest.TestCase):
    TOKEN = "abc123xyz789012345"

    def test_strip_ref_prefix(self):
        self.assertEqual(strip_ref_prefixes(f"ref_{self.TOKEN}"), self.TOKEN)

    def test_strip_uref_prefix(self):
        self.assertEqual(strip_ref_prefixes(f"uref_{self.TOKEN}"), self.TOKEN)

    def test_strip_bare(self):
        self.assertEqual(strip_ref_prefixes(self.TOKEN), self.TOKEN)

    def test_strip_rejects_promo(self):
        self.assertIsNone(strip_ref_prefixes("promo_SUMMER"))

    def test_any_ref_prefix(self):
        self.assertEqual(extract_any_ref_token(f"ref_{self.TOKEN}"), self.TOKEN)

    def test_any_uref_prefix(self):
        self.assertEqual(extract_any_ref_token(f"uref_{self.TOKEN}"), self.TOKEN)

    def test_any_ref_path(self):
        self.assertEqual(
            extract_any_ref_token(f"https://focuspay.org/ref/{self.TOKEN}"), self.TOKEN
        )

    def test_any_invite_path(self):
        self.assertEqual(
            extract_any_ref_token(f"https://focuspay.org/invite/{self.TOKEN}"), self.TOKEN
        )

    def test_any_tme_ref_start(self):
        url = f"https://t.me/focuspay1_bot?start=ref_{self.TOKEN}"
        self.assertEqual(extract_any_ref_token(url), self.TOKEN)

    def test_any_tme_uref_start(self):
        url = f"https://t.me/focuspay1_bot?start=uref_{self.TOKEN}"
        self.assertEqual(extract_any_ref_token(url), self.TOKEN)

    def test_any_start_command(self):
        self.assertEqual(
            extract_any_ref_token(f"/start ref_{self.TOKEN}"), self.TOKEN
        )

    def test_any_empty(self):
        self.assertIsNone(extract_any_ref_token(""))


if __name__ == "__main__":
    unittest.main()
