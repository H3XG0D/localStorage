"""RBAC: роли → атомарные permissions, grants, finance.analytics default-deny для операторов."""
from __future__ import annotations

import unittest

from fastapi import HTTPException

from permissions import (
    PERM_ANTISPAM_PHRASES,
    PERM_CASINO_PAYOUT,
    PERM_EXTERNAL_CONFIRM,
    PERM_FINANCE_ANALYTICS,
    PERM_FINANCE_PAYOUT,
    PERM_ORDERS_HISTORY,
    PERM_PAYOUT_REQUISITES,
    PERM_PAYOUT_REQUISITES_CONFIRM,
    PERM_TEMPLATES_CREATE,
    PERM_TEMPLATES_EDIT_ANY,
    PERM_TEMPLATES_EDIT_OWN,
    PERM_TEMPLATES_VIEW,
    apply_permission_grants,
    attach_operator_permissions_sync,
    has_permission,
    permissions_for_operator_roles,
    require_permission,
    resolve_admin_permissions,
)


class RoleMatrixTests(unittest.TestCase):
    def test_client_has_templates_and_external_not_finance_analytics(self):
        perms = permissions_for_operator_roles(["client"])
        self.assertIn(PERM_TEMPLATES_VIEW, perms)
        self.assertIn(PERM_TEMPLATES_CREATE, perms)
        self.assertIn(PERM_TEMPLATES_EDIT_OWN, perms)
        self.assertIn(PERM_EXTERNAL_CONFIRM, perms)
        self.assertNotIn(PERM_FINANCE_ANALYTICS, perms)
        self.assertNotIn(PERM_FINANCE_PAYOUT, perms)
        self.assertNotIn(PERM_CASINO_PAYOUT, perms)
        self.assertIn(PERM_ANTISPAM_PHRASES, perms)
        self.assertIn(PERM_PAYOUT_REQUISITES, perms)
        self.assertNotIn(PERM_PAYOUT_REQUISITES_CONFIRM, perms)
        self.assertNotIn(PERM_TEMPLATES_EDIT_ANY, perms)
        self.assertNotIn(PERM_ORDERS_HISTORY, perms)

    def test_finance_has_payout_not_analytics_by_default(self):
        perms = permissions_for_operator_roles(["finance"])
        self.assertIn(PERM_FINANCE_PAYOUT, perms)
        self.assertIn(PERM_TEMPLATES_VIEW, perms)
        self.assertIn(PERM_ANTISPAM_PHRASES, perms)
        self.assertNotIn(PERM_FINANCE_ANALYTICS, perms)
        self.assertNotIn(PERM_CASINO_PAYOUT, perms)
        self.assertNotIn(PERM_TEMPLATES_CREATE, perms)
        self.assertNotIn(PERM_ORDERS_HISTORY, perms)

    def test_dual_role_union(self):
        perms = permissions_for_operator_roles(["client", "finance"])
        self.assertIn(PERM_TEMPLATES_CREATE, perms)
        self.assertIn(PERM_FINANCE_PAYOUT, perms)
        self.assertNotIn(PERM_FINANCE_ANALYTICS, perms)

    def test_grant_adds_and_revoke_removes(self):
        base = permissions_for_operator_roles(["client"])
        with_analytics = apply_permission_grants(base, [(PERM_FINANCE_ANALYTICS, True)])
        self.assertIn(PERM_FINANCE_ANALYTICS, with_analytics)
        revoked = apply_permission_grants(with_analytics, [(PERM_FINANCE_ANALYTICS, False)])
        self.assertNotIn(PERM_FINANCE_ANALYTICS, revoked)

    def test_require_permission_raises(self):
        op = attach_operator_permissions_sync(
            {"id": 1, "operator_roles": ["finance"], "operator_role": "finance"}
        )
        with self.assertRaises(HTTPException) as ctx:
            require_permission(op, PERM_TEMPLATES_CREATE)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_admin_without_telegram_finance_loses_analytics(self):
        admin = {"id": 1, "is_admin": True, "telegram_user_id": None}
        perms = resolve_admin_permissions(admin)
        self.assertIn(PERM_TEMPLATES_EDIT_ANY, perms)
        self.assertNotIn(PERM_FINANCE_ANALYTICS, perms)

    def test_has_permission_helper(self):
        op = attach_operator_permissions_sync({"id": 2, "operator_roles": ["client"]})
        self.assertTrue(has_permission(op, PERM_TEMPLATES_VIEW))
        self.assertFalse(has_permission(op, PERM_FINANCE_ANALYTICS))
        self.assertFalse(has_permission(op, PERM_CASINO_PAYOUT))

    def test_casino_payout_grant_only(self):
        base = permissions_for_operator_roles(["finance"])
        granted = apply_permission_grants(base, [(PERM_CASINO_PAYOUT, True)])
        self.assertIn(PERM_CASINO_PAYOUT, granted)
        finance = attach_operator_permissions_sync(
            {"id": 3, "operator_roles": ["finance"], "operator_role": "finance"}
        )
        with self.assertRaises(HTTPException) as ctx:
            require_permission(finance, PERM_CASINO_PAYOUT)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_senior_grade_adds_orders_history(self):
        senior = attach_operator_permissions_sync(
            {
                "id": 4,
                "operator_roles": ["client"],
                "role_grades": {"client": "senior"},
            }
        )
        self.assertIn(PERM_ORDERS_HISTORY, senior["permissions"])
        self.assertTrue(has_permission(senior, PERM_ORDERS_HISTORY))

    def test_junior_finance_lacks_orders_history(self):
        junior = attach_operator_permissions_sync(
            {
                "id": 5,
                "operator_roles": ["finance"],
                "operator_role": "finance",
                "role_grades": {"finance": "junior"},
            }
        )
        self.assertNotIn(PERM_ORDERS_HISTORY, junior["permissions"])
        with self.assertRaises(HTTPException) as ctx:
            require_permission(junior, PERM_ORDERS_HISTORY)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_grant_can_revoke_senior_history(self):
        base = set(
            attach_operator_permissions_sync(
                {
                    "id": 6,
                    "operator_roles": ["client"],
                    "role_grades": {"client": "senior"},
                }
            )["permissions"]
        )
        revoked = apply_permission_grants(base, [(PERM_ORDERS_HISTORY, False)])
        self.assertNotIn(PERM_ORDERS_HISTORY, revoked)

    def test_finance_junior_lacks_requisite_confirm(self):
        perms = permissions_for_operator_roles(["finance"])
        self.assertNotIn(PERM_PAYOUT_REQUISITES_CONFIRM, perms)
        junior = attach_operator_permissions_sync(
            {
                "id": 7,
                "operator_roles": ["finance"],
                "operator_role": "finance",
                "role_grades": {"finance": "junior"},
            }
        )
        self.assertNotIn(PERM_PAYOUT_REQUISITES_CONFIRM, junior["permissions"])

    def test_finance_senior_gets_requisite_confirm(self):
        senior = attach_operator_permissions_sync(
            {
                "id": 8,
                "operator_roles": ["finance"],
                "operator_role": "finance",
                "role_grades": {"finance": "senior"},
            }
        )
        self.assertIn(PERM_PAYOUT_REQUISITES_CONFIRM, senior["permissions"])
        self.assertTrue(has_permission(senior, PERM_PAYOUT_REQUISITES_CONFIRM))

    def test_client_senior_does_not_get_requisite_confirm(self):
        senior = attach_operator_permissions_sync(
            {
                "id": 9,
                "operator_roles": ["client"],
                "role_grades": {"client": "senior"},
            }
        )
        self.assertIn(PERM_ORDERS_HISTORY, senior["permissions"])
        self.assertNotIn(PERM_PAYOUT_REQUISITES_CONFIRM, senior["permissions"])

    def test_grant_adds_requisite_confirm_to_junior_finance(self):
        base = set(
            attach_operator_permissions_sync(
                {
                    "id": 10,
                    "operator_roles": ["finance"],
                    "operator_role": "finance",
                    "role_grades": {"finance": "junior"},
                }
            )["permissions"]
        )
        granted = apply_permission_grants(base, [(PERM_PAYOUT_REQUISITES_CONFIRM, True)])
        self.assertIn(PERM_PAYOUT_REQUISITES_CONFIRM, granted)


if __name__ == "__main__":
    unittest.main()
