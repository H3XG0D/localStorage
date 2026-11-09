"""Единый парсер payment_snapshot + запрет на новые самодельные копии."""
import json
import os
import re
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = MagicMock()

from services.payment_snapshot import (  # noqa: E402
    order_payment_snapshot,
    parse_payment_snapshot,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = {"merchant_expires_at": "2026-11-07T09:30:00.123456Z", "bill": {"bank": "T"}}


class FakeRecord:
    """asyncpg.Record умеет только индексацию, без .get()."""

    def __init__(self, data):
        self._data = dict(data)

    def __getitem__(self, key):
        return self._data[key]


class ParseTests(unittest.TestCase):
    def test_jsonb_arrives_as_string(self):
        self.assertEqual(parse_payment_snapshot(json.dumps(SNAP)), SNAP)

    def test_dict_is_copied_not_aliased(self):
        source = {"a": 1}
        parsed = parse_payment_snapshot(source)
        parsed["a"] = 2
        self.assertEqual(source["a"], 1)

    def test_garbage_gives_empty_dict(self):
        for value in (None, "", "   ", "not json", "[1, 2]", '"text"', "123", 5, [], object()):
            self.assertEqual(parse_payment_snapshot(value), {}, repr(value))


class OrderSnapshotTests(unittest.TestCase):
    def test_dict_order_with_string_snapshot(self):
        order = {"payment_snapshot": json.dumps(SNAP)}
        self.assertEqual(order_payment_snapshot(order)["bill"]["bank"], "T")

    def test_asyncpg_style_record(self):
        record = FakeRecord({"payment_snapshot": json.dumps(SNAP)})
        self.assertEqual(order_payment_snapshot(record), SNAP)

    def test_missing_column_and_none_order(self):
        self.assertEqual(order_payment_snapshot(FakeRecord({})), {})
        self.assertEqual(order_payment_snapshot({}), {})
        self.assertEqual(order_payment_snapshot(None), {})


class EverythingCompilesTests(unittest.TestCase):
    """`scripts/` и прочее вне tests никто не импортирует — синтаксис ловим здесь."""

    SKIP_DIRS = {".venv", "__pycache__", ".git", "node_modules"}

    def test_every_python_file_compiles(self):
        broken = []
        for folder, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in self.SKIP_DIRS]
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(folder, name)
                source = open(path, encoding="utf-8").read()
                try:
                    compile(source, path, "exec")
                except SyntaxError as exc:
                    broken.append(f"{os.path.relpath(path, ROOT)}:{exc.lineno}: {exc.msg}")
        self.assertEqual(broken, [])


class NoHandRolledParsersTests(unittest.TestCase):
    """Разбор снапшота руками — та самая причина прод-бага от 2026-11-02."""

    SKIP_DIRS = {".venv", "tests", "__pycache__", ".git"}
    ALLOWED = {os.path.join("services", "payment_snapshot.py")}

    def _sources(self):
        for folder, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in self.SKIP_DIRS]
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(folder, name)
                rel = os.path.relpath(path, ROOT)
                if rel in self.ALLOWED:
                    continue
                yield rel, open(path, encoding="utf-8").read()

    def test_no_raw_dict_cast(self):
        pattern = re.compile(r"dict\(\s*(?:row|order|deal|d)\[[\"']payment_snapshot[\"']\]")
        offenders = [rel for rel, src in self._sources() if pattern.search(src)]
        self.assertEqual(offenders, [], "читать снапшот только через order_payment_snapshot")

    def test_no_inline_json_loads_of_snapshot(self):
        pattern = re.compile(
            r"payment_snapshot[\"']\s*\)[^\n]*\n(?:.*\n){0,3}?\s*json\.loads", re.MULTILINE
        )
        offenders = [rel for rel, src in self._sources() if pattern.search(src)]
        self.assertEqual(offenders, [], "читать снапшот только через order_payment_snapshot")


if __name__ == "__main__":
    unittest.main()
