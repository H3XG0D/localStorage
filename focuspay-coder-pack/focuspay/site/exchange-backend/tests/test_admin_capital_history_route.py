"""Regression coverage for the specified admin capital-history route and legacy alias."""

from routers.admin_dashboard import router


def test_capital_history_has_finance_route_and_legacy_alias():
    get_routes = {
        route.path: route
        for route in router.routes
        if "GET" in route.methods
    }

    specified = "/finance/capital-history"
    legacy = "/dashboard/capital-history"
    assert specified in get_routes
    assert legacy in get_routes
    assert get_routes[specified].endpoint is get_routes[legacy].endpoint
    assert get_routes[specified].include_in_schema is True
    assert get_routes[legacy].include_in_schema is False
