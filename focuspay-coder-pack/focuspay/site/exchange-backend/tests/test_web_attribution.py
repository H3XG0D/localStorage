"""Unit tests for web attribution track validation."""
from __future__ import annotations

import asyncio
import unittest

from web_attribution import track_ref_visit


class WebAttributionTrackTests(unittest.TestCase):
    def test_track_invalid_kind(self):
        result = asyncio.run(
            track_ref_visit(
                ref_kind="invalid",  # type: ignore[arg-type]
                ref_token="abc12345",
                guest_session="00000000-0000-4000-8000-000000000001",
            )
        )
        self.assertFalse(result["ok"])

    def test_track_empty_token(self):
        result = asyncio.run(
            track_ref_visit(
                ref_kind="promo",
                ref_token="",
                guest_session="00000000-0000-4000-8000-000000000001",
            )
        )
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
