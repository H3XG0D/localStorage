"""Admin GET /orders display helpers: referrer + partner filter (no formulas)."""
from __future__ import annotations

import unittest

from admin_orders_list import (
    PARTNER_OPTIONS_SQL,
    partner_clients_exists_sql,
    partner_option_from_row,
    referrer_fields_from_row,
)


class PartnerFilterSqlTests(unittest.TestCase):
    def test_exists_uses_promo_attributions_and_campaign_id(self):
        sql = partner_clients_exists_sql(4)
        self.assertIn("promo_attributions", sql)
        self.assertIn("promo_campaigns", sql)
        self.assertIn("pa.user_id = o.user_id", sql)
        self.assertIn("pc.id = $4", sql)
        self.assertNotIn("PAID", sql)
        self.assertNotIn("order_service_profit", sql)

    def test_rejects_bad_index(self):
        with self.assertRaises(ValueError):
            partner_clients_exists_sql(0)

    def test_options_sql_is_light(self):
        self.assertIn("partner_accounts", PARTNER_OPTIONS_SQL)
        self.assertNotIn("partner_ledger", PARTNER_OPTIONS_SQL)
        self.assertNotIn("service_profit", PARTNER_OPTIONS_SQL)


class PartnerOptionTests(unittest.TestCase):
    def test_prefers_label_then_display_name(self):
        self.assertEqual(
            partner_option_from_row({"id": 7, "label": "  Alpha  "}),
            {"id": 7, "label": "Alpha"},
        )
        self.assertEqual(
            partner_option_from_row(
                {"id": 8, "partner_display_name": "Beta", "name": "ignored"}
            ),
            {"id": 8, "label": "Beta"},
        )

    def test_fallback_id(self):
        self.assertEqual(partner_option_from_row({"id": 9}), {"id": 9, "label": "#9"})


class ReferrerFieldsTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(
            referrer_fields_from_row({}),
            {
                "referrer_user_id": None,
                "referrer_username": None,
                "referrer_first_name": None,
            },
        )

    def test_at_prefix_and_ids(self):
        out = referrer_fields_from_row(
            {
                "referrer_user_id": 42,
                "referrer_username": "miltos",
                "referrer_first_name": "Mil",
            }
        )
        self.assertEqual(out["referrer_user_id"], 42)
        self.assertEqual(out["referrer_username"], "@miltos")
        self.assertEqual(out["referrer_first_name"], "Mil")

    def test_keeps_existing_at(self):
        out = referrer_fields_from_row(
            {"referrer_user_id": 1, "referrer_username": "@already"}
        )
        self.assertEqual(out["referrer_username"], "@already")


class OrdersListQueryTests(unittest.TestCase):
    def test_status_and_search_params(self):
        from admin_orders_list import build_orders_list_query

        where, params = build_orders_list_query(status="paid", search="alex")
        self.assertIn("o.status = $1", where)
        self.assertEqual(params[0], "PAID")
        self.assertIn("o.order_id ILIKE $2", where)
        self.assertEqual(params[1], "%alex%")
        self.assertNotIn("service_profit", where)

    def test_direction_crypto(self):
        from admin_orders_list import build_orders_list_query

        where, params = build_orders_list_query(direction="Buy", crypto="USDT")
        self.assertIn("o.direction = $1", where)
        self.assertEqual(params[0], "buy")
        self.assertIn("LOWER(o.crypto) LIKE $2", where)
        self.assertEqual(params[1], "%usdt%")

    def test_counts_sql_has_kpi_statuses(self):
        from admin_orders_list import HISTORY_KPI_STATUSES, counts_from_row, counts_sql

        sql = counts_sql("1=1")
        self.assertIn("COUNT(*)::int AS total", sql)
        for status in HISTORY_KPI_STATUSES:
            self.assertIn(status, sql)
        self.assertNotIn("service_profit", sql)
        counts = counts_from_row({"total": 10, "paid": 4, "canceled": 2})
        self.assertEqual(counts["all"], 10)
        self.assertEqual(counts["PAID"], 4)
        self.assertEqual(counts["CANCELED"], 2)
        self.assertEqual(counts["CREATED"], 0)


class SerializeOrderTests(unittest.TestCase):
    def test_no_profit_unless_requested(self):
        from admin_orders_list import serialize_admin_order

        row = {
            "id": 1,
            "order_id": "ABC",
            "user_id": 11,
            "status": "PAID",
            "direction": "buy",
            "crypto": "usdt",
            "fiat_amount": 1000,
            "crypto_amount": 12,
            "operator_display_name": "miltos",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        out = serialize_admin_order(row, include_finance=False)
        self.assertNotIn("service_profit_rub", out)
        self.assertEqual(out["operator_name"], "miltos")
        self.assertEqual(out["status_label"], "Оплачена")
        self.assertFalse(out["in_live_queue"])


if __name__ == "__main__":
    unittest.main()
