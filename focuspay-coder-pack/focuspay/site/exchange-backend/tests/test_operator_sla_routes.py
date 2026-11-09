"""Regression coverage for admin operator SLA route namespace and ordering."""

from routers.admin_operators import router


def test_operator_sla_routes_have_declared_paths_and_static_first():
    get_paths = [route.path for route in router.routes if "GET" in route.methods]

    summary = "/operators/sla/summary"
    detail = "/operators/{operator_id}/sla"
    assert summary in get_paths
    assert detail in get_paths
    assert get_paths.index(summary) < get_paths.index(detail)
    assert "/sla/summary" not in get_paths
    assert "/{operator_id}/sla" not in get_paths
