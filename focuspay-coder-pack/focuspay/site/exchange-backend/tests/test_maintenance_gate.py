"""Режим техперерыва живёт на проде — репозиторий не должен его терять.

Фича существовала только в `/opt/exchange-backend`: в git её не было ни в
`runtime_settings.py`, ни в двух местах создания заявки. Любой выкат файлов
«как в репозитории» молча снимал техперерыв с боевого сервиса. Эти проверки
ловят такую потерю до выката.
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]


class MaintenanceSettingTests(unittest.TestCase):
    def test_runtime_settings_exposes_the_flag(self):
        from runtime_settings import MAINTENANCE_MESSAGE, maintenance_mode

        self.assertTrue(callable(maintenance_mode))
        self.assertIn("перерыв", MAINTENANCE_MESSAGE.lower())

    def test_flag_is_a_known_key_with_a_safe_default(self):
        src = (ROOT / "runtime_settings.py").read_text()
        self.assertIn('"maintenance_mode",', src, "ключ выпал из _SETTING_KEYS")
        self.assertIn('"maintenance_mode": False', src, "дефолт должен быть выключен")

    def test_default_is_off(self):
        import runtime_settings

        defaults = runtime_settings.merge_settings(None)
        self.assertFalse(defaults["maintenance_mode"])


class MaintenanceGateTests(unittest.TestCase):
    """Оба пути создания заявки должны уважать техперерыв."""

    def _gate_present(self, path: Path, func: str) -> bool:
        src = path.read_text()
        start = src.index(func)
        body = src[start : start + 3000]
        return bool(re.search(r"if maintenance_mode\(\):", body)) and "MAINTENANCE_MESSAGE" in body

    def test_create_web_order_is_gated(self):
        self.assertTrue(
            self._gate_present(ROOT / "order_service.py", "async def create_web_order"),
            "создание заявки на сайте/в мини-аппе перестало уважать техперерыв",
        )

    def test_requisite_retry_is_gated(self):
        self.assertTrue(
            self._gate_present(ROOT / "requisite_retry.py", "async def fulfill_open_retry"),
            "повтор запроса реквизитов обходит техперерыв",
        )


if __name__ == "__main__":
    unittest.main()
