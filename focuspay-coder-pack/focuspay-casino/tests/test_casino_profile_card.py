from datetime import datetime
from io import BytesIO
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from PIL import Image

from casino_profile_card import _browser_env, _build_html, _work_dir, render_profile_card


class CasinoProfileCardTests(unittest.TestCase):
    def test_profile_card_renders_supplied_layout_with_avatar(self):
        avatar = BytesIO()
        Image.new("RGB", (32, 32), "#44aa88").save(avatar, format="PNG")

        image_bytes = render_profile_card(
            {
                "name": "Анна",
                "username": "anna",
                "balance_rub": "1250.50",
                "weekly_bet_turnover_rub": "5000",
                "weekly_eligible_loss_rub": "700",
                "cashback_level": "7%",
                "cashback_percent": "7",
                "next_cashback_level": "9%",
                "expected_cashback_rub": "49",
                "rollover_remaining_rub": "100",
                "progress_to_next_level": 50,
            },
            avatar_bytes=avatar.getvalue(),
        )

        self.assertTrue(image_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(BytesIO(image_bytes)) as image:
            self.assertEqual(image.size, (2000, 1280))

    def test_card_html_escapes_identity_and_uses_avatar_fallback(self):
        html = _build_html(
            {"name": "<Анна>", "username": "<anna>"},
            None,
            None,
        )

        self.assertIn("&lt;Анна&gt;", html)
        self.assertIn("Нужно поставить", html)
        self.assertNotIn("Осталось отыграть", html)
        self.assertIn("avatar-fallback", html)
        self.assertNotIn("<Анна>", html)

    def test_work_dir_honors_configured_writable_directory(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"CASINO_CARD_WORKDIR": directory}
        ):
            self.assertEqual(_work_dir(), Path(directory))

    def test_renderer_disables_dev_shm_and_uses_configured_workdir(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"CASINO_CARD_WORKDIR": directory}
        ), patch("casino_profile_card._find_browser", return_value="chromium"), patch(
            "casino_profile_card.subprocess.run"
        ) as run:
            def create_png(command, **_kwargs):
                screenshot = next(value for value in command if value.startswith("--screenshot="))
                Image.new("RGB", (2000, 1280)).save(screenshot.split("=", 1)[1], format="PNG")
                return type("Result", (), {"returncode": 0, "stderr": b""})()

            run.side_effect = create_png
            result = render_profile_card({"name": "Анна"})

            command = run.call_args.args[0]
            self.assertTrue(result.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertIn("--disable-dev-shm-usage", command)
            self.assertTrue(any(value.startswith(f"--user-data-dir={directory}/") for value in command))
            self.assertTrue(any(value.startswith(f"--screenshot={directory}/") for value in command))
            self.assertIn("/usr/bin", run.call_args.kwargs["env"]["PATH"].split(":"))

    def test_browser_env_appends_coreutils_when_systemd_path_is_venv_only(self):
        env = _browser_env("/tmp/card-home", {"PATH": "/opt/focuspay-casino/venv/bin", "LANG": "C"})
        parts = env["PATH"].split(":")
        self.assertEqual(env["HOME"], "/tmp/card-home")
        self.assertEqual(parts[0], "/opt/focuspay-casino/venv/bin")
        self.assertIn("/usr/bin", parts)
        self.assertIn("/bin", parts)
        self.assertEqual(env["LANG"], "C")


if __name__ == "__main__":
    unittest.main()
