import unittest
from unittest.mock import patch

from services.ux_copy import txt_site


class OnionSiteCopyTests(unittest.TestCase):
    def test_txt_site_never_shows_onion_to_buyers(self):
        onion = "http://" + ("b" * 56) + ".onion"
        doliv = "http://" + ("c" * 56) + ".onion"
        with patch("services.config_rates.PUBLIC_ONION_URL", onion), patch(
            "services.config_rates.DOLIV_ONION_URL", doliv
        ):
            text = txt_site()
        self.assertIn("focuspay.org", text)
        self.assertNotIn(".onion", text)
        self.assertNotIn("Tor", text)


if __name__ == "__main__":
    unittest.main()
