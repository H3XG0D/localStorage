import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import chat_attachments as ca


class TestDetectMessageType(unittest.TestCase):
    def test_pdf_is_document(self):
        self.assertEqual(ca.detect_message_type("application/pdf", "check.pdf"), "document")

    def test_mp4_is_video(self):
        self.assertEqual(ca.detect_message_type("video/mp4", "clip.mp4"), "video")

    def test_ogg_is_audio(self):
        self.assertEqual(ca.detect_message_type("audio/ogg", None), "audio")

    def test_unknown_raises(self):
        with self.assertRaises(HTTPException):
            ca.detect_message_type("application/zip", "x.zip")


class TestSaveChatAttachment(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.upload_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_pdf(self):
        with patch.object(ca, "CHAT_UPLOAD_DIR", self.upload_dir):
            content = b"%PDF-1.4 test"
            aid, mt = ca.save_chat_attachment(
                content, "application/pdf", "receipt.pdf", message_type="document"
            )
            self.assertEqual(mt, "document")
            self.assertEqual(len(aid), 32)
            path = ca.resolve_attachment_path(aid)
            self.assertIsNotNone(path)
            self.assertTrue(path.is_file())

    def test_rejects_oversized_document(self):
        with patch.object(ca, "CHAT_UPLOAD_DIR", self.upload_dir):
            huge = b"x" * (ca.MAX_DOCUMENT_BYTES + 1)
            with self.assertRaises(HTTPException):
                ca.save_chat_attachment(
                    huge, "application/pdf", "big.pdf", message_type="document"
                )


class TestAttachmentAccessToken(unittest.TestCase):
    def test_token_stable_within_hour_bucket(self):
        now = 1_787_272_000
        with patch("chat_attachments.time.time", side_effect=[now + 10, now + 200, now + 200]):
            a = ca.make_attachment_access_token("abc")
            b = ca.make_attachment_access_token("abc")
            ok = ca.verify_attachment_access_token("abc", a)
        self.assertEqual(a, b)
        self.assertTrue(ok)

    def test_token_changes_across_hour_bucket(self):
        now = 1_787_270_000
        with patch("chat_attachments.time.time", return_value=now + 10):
            a = ca.make_attachment_access_token("abc")
        with patch("chat_attachments.time.time", return_value=now + 4000):
            b = ca.make_attachment_access_token("abc")
        self.assertNotEqual(a, b)


class TestAttachmentMimeType(unittest.TestCase):
    def test_mime_for_pdf(self):
        with tempfile.TemporaryDirectory() as d:
            upload = Path(d)
            with patch.object(ca, "CHAT_UPLOAD_DIR", upload):
                aid, _ = ca.save_chat_attachment(
                    b"%PDF", "application/pdf", "f.pdf", message_type="document"
                )
                self.assertEqual(ca.attachment_mime_type(aid), "application/pdf")


if __name__ == "__main__":
    unittest.main()
