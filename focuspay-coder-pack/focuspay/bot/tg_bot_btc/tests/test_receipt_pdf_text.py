"""Чтение текста банковских PDF-чеков (Identity-H сабсеты + ToUnicode).

Регресс на баг: без разбора ToUnicode текст возвращался глиф-айдишниками,
а latin-1 мусор из сжатых потоков считался валидным текстом — поэтому флаг
`pdf_amount_missing` срабатывал на каждом настоящем чеке Сбера/Т-Банка.
"""
from __future__ import annotations

import os
import sys
import unittest
import zlib
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.receipt_pdf_inspect import (  # noqa: E402
    _cmap_pdf_text,
    _parse_tounicode_cmap,
    _unescape_pdf_string,
    inspect_pdf_bytes,
    looks_like_extracted_text,
)


def _build_bank_pdf(lines: list[str]) -> bytes:
    """Собирает PDF как выгрузка банка: Type0/Identity-H, текст глифами + ToUnicode."""
    charset = sorted({ch for line in lines for ch in line})
    # CID = индекс в сабсете + 1 (нулевой глиф зарезервирован), как у iText.
    cid_by_char = {ch: idx + 1 for idx, ch in enumerate(charset)}

    bfchars = "".join(
        f"<{cid:04X}> <{ord(ch):04X}>\n" for ch, cid in cid_by_char.items()
    )
    cmap = (
        "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        f"{len(cid_by_char)} beginbfchar\n{bfchars}endbfchar\n"
        "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
    ).encode("ascii")

    content_parts = ["BT /F1 10 Tf"]
    for line in lines:
        hexed = "".join(f"{cid_by_char[ch]:04X}" for ch in line)
        content_parts.append(f"<{hexed}> Tj")
    content_parts.append("ET")
    content = zlib.compress(" ".join(content_parts).encode("ascii"))
    cmap_z = zlib.compress(cmap)

    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 700]"
        b"/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>",
        b"<</Length %d/Filter/FlateDecode>>stream\n%s\nendstream" % (len(content), content),
        b"<</Type/Font/Subtype/Type0/BaseFont/AAAAAA+ArialMT/Encoding/Identity-H"
        b"/DescendantFonts[6 0 R]/ToUnicode 7 0 R>>",
        b"<</Type/Font/Subtype/CIDFontType2/BaseFont/AAAAAA+ArialMT>>",
        b"<</Length %d/Filter/FlateDecode>>stream\n%s\nendstream" % (len(cmap_z), cmap_z),
    ]

    out = bytearray(b"%PDF-1.5\n")
    for num, body in enumerate(objects, start=1):
        out += b"%d 0 obj\n" % num + body + b"\nendobj\n"
    out += (
        b"trailer\n<</Root 1 0 R/Producer(iText 2.1.7 by 1T3XT)"
        b"/Creator(JasperReports Library version 6.18.1)/Size %d>>\n"
        b"startxref\n0\n%%%%EOF\n" % (len(objects) + 1)
    )
    return bytes(out)


SBER_LINES = [
    "Чек по операции",
    "2 сентября 2026 14:00:41 (МСК)",
    "Перевод клиенту СберБанка",
    "Номер карты получателя",
    "**** 5863",
    "Сумма перевода",
    "3 357,00",
]


class TestToUnicodeCmap(unittest.TestCase):
    def test_bfchar_pairs(self):
        data = b"begincmap\n2 beginbfchar\n<0041> <0410>\n<0042> <0411>\nendbfchar\nendcmap"
        self.assertEqual(_parse_tounicode_cmap(data), {0x41: "А", 0x42: "Б"})

    def test_bfrange_span(self):
        data = b"beginbfrange\n<0010> <0012> <0030>\nendbfrange"
        self.assertEqual(_parse_tounicode_cmap(data), {0x10: "0", 0x11: "1", 0x12: "2"})

    def test_bfrange_array(self):
        data = b"beginbfrange\n<0020> <0021> [<0041> <0042>]\nendbfrange"
        self.assertEqual(_parse_tounicode_cmap(data), {0x20: "A", 0x21: "B"})


class TestPdfStringUnescape(unittest.TestCase):
    def test_escapes_and_octal(self):
        self.assertEqual(_unescape_pdf_string(rb"a\(b\)c\\d"), b"a(b)c\\d")
        self.assertEqual(_unescape_pdf_string(rb"\101\102"), b"AB")

    def test_line_continuation_dropped(self):
        self.assertEqual(_unescape_pdf_string(b"ab\\\ncd"), b"abcd")


class TestExtractedTextGate(unittest.TestCase):
    def test_pdf_syntax_garbage_rejected(self):
        garbage = (
            "%PDF-1.5 3 0 obj <</ColorSpace/DeviceGray/Subtype/Image/Filter/FlateDecode"
            "/Type/XObject>>stream wi+e &nFPA .P%x1 endstream endobj"
        )
        self.assertFalse(looks_like_extracted_text(garbage))

    def test_real_receipt_text_accepted(self):
        self.assertTrue(
            looks_like_extracted_text("Чек по операции Сумма перевода 3 357,00 ₽ Комиссия 0,00 ₽")
        )

    def test_empty_and_short_rejected(self):
        self.assertFalse(looks_like_extracted_text(None))
        self.assertFalse(looks_like_extracted_text("3 357"))


def _without_pypdf():
    """Гасит pypdf, чтобы тест фолбэка не зависел от того, стоит ли он в venv."""
    return mock.patch(
        "services.receipt_pdf_inspect._pypdf_text_and_dates",
        return_value=(None, None, None),
    )


class TestBankReceiptExtraction(unittest.TestCase):
    def test_cmap_reads_glyph_encoded_text(self):
        text = _cmap_pdf_text(_build_bank_pdf(SBER_LINES))
        self.assertIsNotNone(text)
        self.assertIn("Перевод клиенту СберБанка", text)
        self.assertIn("**** 5863", text)
        self.assertIn("3 357,00", text)

    def test_amount_found_without_pypdf(self):
        """Ключевой регресс: сумма находится даже когда pypdf недоступен."""
        with _without_pypdf():
            res = inspect_pdf_bytes(_build_bank_pdf(SBER_LINES), fiat_amount=3357.0)
        self.assertEqual(res["text_source"], "cmap")
        self.assertIs(res["amount_present"], True)
        self.assertNotIn("pdf_amount_missing", res["flags"])
        self.assertNotIn("pdf_text_unreadable", res["flags"])

    def test_amount_found_with_whatever_engine_is_available(self):
        res = inspect_pdf_bytes(_build_bank_pdf(SBER_LINES), fiat_amount=3357.0)
        self.assertIn(res["text_source"], ("pypdf", "cmap"))
        self.assertIs(res["amount_present"], True)
        self.assertNotIn("pdf_amount_missing", res["flags"])

    def test_wrong_amount_still_flagged(self):
        res = inspect_pdf_bytes(_build_bank_pdf(SBER_LINES), fiat_amount=9999.0)
        self.assertIsNotNone(res["text_source"])
        self.assertIs(res["amount_present"], False)
        self.assertIn("pdf_amount_missing", res["flags"])

    def test_unreadable_pdf_does_not_claim_missing_amount(self):
        """Нет ToUnicode → текста нет → флаг про нечитаемость, а не про сумму."""
        raster = (
            b"%PDF-1.5\n1 0 obj\n<</Type/Catalog>>\nendobj\n"
            b"2 0 obj\n<</Subtype/Image/Filter/FlateDecode/Length 4>>stream\n"
            + zlib.compress(b"\x00\x01\x02\x03")
            + b"\nendstream\nendobj\ntrailer\n<</Producer(iText 2.1.7 by 1T3XT)>>\n%%EOF\n"
        )
        with _without_pypdf():
            res = inspect_pdf_bytes(raster, fiat_amount=3357.0)
        self.assertIsNone(res["text_source"])
        self.assertIsNone(res["amount_present"])
        self.assertIn("pdf_text_unreadable", res["flags"])
        self.assertNotIn("pdf_amount_missing", res["flags"])


if __name__ == "__main__":
    unittest.main()
