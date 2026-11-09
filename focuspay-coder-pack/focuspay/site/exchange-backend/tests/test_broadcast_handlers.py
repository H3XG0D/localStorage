"""Admin guards, segment validation, and hardened photo upload for broadcast."""
from __future__ import annotations

import io
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from routers import admin_broadcast
from routers import broadcast_handlers as bh
from routers import operator_broadcast


def _tiny_png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (20, 20, 20)).save(buf, format="PNG")
    return buf.getvalue()


def _route_dep_names(router, path: str, method: str) -> list[str]:
    method = method.upper()
    names: list[str] = []
    for route in router.routes:
        if path not in getattr(route, "path", ""):
            continue
        if method not in getattr(route, "methods", set()):
            continue
        for dep in route.dependant.dependencies:
            call = getattr(dep, "call", None)
            if call:
                names.append(getattr(call, "__name__", ""))
    return names


class AdminGuardTests(unittest.TestCase):
    def test_admin_endpoints_require_get_current_admin(self):
        checks = [
            ("/broadcast/segments", "GET"),
            ("/broadcast/preview", "POST"),
            ("/broadcast/upload-photo", "POST"),
            ("/broadcast/jobs", "POST"),
            ("/broadcast/stickers", "GET"),
            ("/broadcast/stickers/{sticker_id}/preview", "GET"),
            ("/broadcast/ai-draft", "POST"),
            ("/broadcast/schedules", "GET"),
            ("/broadcast/schedules", "POST"),
        ]
        for path, method in checks:
            names = _route_dep_names(admin_broadcast.router, path, method)
            self.assertIn("get_current_admin", names, msg=f"{method} {path}")

    def test_operator_ai_and_catalog_routes_require_operator(self):
        checks = [
            ("/broadcast/stickers", "GET"),
            ("/broadcast/stickers/{sticker_id}/preview", "GET"),
            ("/broadcast/ai-draft", "POST"),
        ]
        for path, method in checks:
            names = _route_dep_names(operator_broadcast.router, path, method)
            self.assertIn("get_current_operator", names, msg=f"{method} {path}")

    def test_operator_jobs_still_guarded(self):
        names = _route_dep_names(operator_broadcast.router, "/broadcast/jobs", "POST")
        self.assertIn("get_current_operator", names)
        names = _route_dep_names(operator_broadcast.router, "/broadcast/schedules", "POST")
        self.assertIn("get_current_operator", names)
        names = _route_dep_names(operator_broadcast.router, "/broadcast/jobs/{job_id}", "PATCH")
        self.assertIn("get_current_operator", names)


class SegmentValidationTests(unittest.TestCase):
    def test_unknown_segment_rejected(self):
        with self.assertRaises(ValidationError):
            bh.PreviewBody(segment="everyone")
        with self.assertRaises(ValidationError):
            bh.CreateJobBody(segment="hack", text="hi")

    def test_empty_segment_becomes_all(self):
        body = bh.PreviewBody(segment="  ")
        self.assertEqual(body.segment, "all")

    def test_create_defaults_keep_old_jobs_compatible(self):
        body = bh.CreateJobBody(segment="paid", text="hello")
        self.assertEqual(body.sticker_mode, "none")
        self.assertEqual(body.selected_sticker_ids, [])
        self.assertFalse(body.ai_enabled)
        self.assertIsNone(body.scheduled_at)

    def test_patch_job_body_allows_segment(self):
        body = bh.PatchJobBody(text="updated", segment="paid")
        self.assertEqual(body.segment, "paid")
        self.assertEqual(body.text, "updated")


class UploadPhotoTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_non_image_bytes(self):
        with self.assertRaises(HTTPException) as ctx:
            bh.validate_broadcast_image(b"not-an-image", content_type="image/png")
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_rejects_wrong_mime(self):
        with self.assertRaises(HTTPException) as ctx:
            bh.validate_broadcast_image(_tiny_png(), content_type="application/pdf")
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_accepts_png_and_safe_name(self):
        data, name = bh.validate_broadcast_image(_tiny_png(), content_type="image/png")
        self.assertTrue(data.startswith(b"\x89PNG"))
        self.assertEqual(name, "broadcast.png")

    async def test_upload_502_hides_telegram_env(self):
        class FakeFile:
            content_type = "image/png"

            async def read(self):
                return _tiny_png()

        with patch(
            "routers.broadcast_handlers.upload_photo_get_file_id",
            AsyncMock(return_value=None),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await bh.upload_photo(FakeFile())  # type: ignore[arg-type]
        self.assertEqual(ctx.exception.status_code, 502)
        detail = str(ctx.exception.detail)
        self.assertNotIn("TELEGRAM_", detail)
        self.assertNotIn(".env", detail)


if __name__ == "__main__":
    unittest.main()
