from __future__ import annotations

from test_support.e2e_payfast.runner import (
    DSN_VARIABLE,
    INTERNAL_COMPOSE_FLAG,
    OPT_IN_FLAG,
    E2EConfig,
    E2EConfigurationError,
)


def test_accepts_owned_internal_compose_database(monkeypatch) -> None:
    monkeypatch.setenv(OPT_IN_FLAG, "1")
    monkeypatch.setenv(INTERNAL_COMPOSE_FLAG, "1")
    monkeypatch.setenv(
        DSN_VARIABLE,
        "postgresql://e2e:synthetic-only@postgres:5432/e2e_payfast_abc123def456",
    )

    assert E2EConfig.from_environment().dsn.startswith("postgresql://e2e:")


def test_rejects_internal_compose_database_without_ownership_flag(monkeypatch) -> None:
    monkeypatch.setenv(OPT_IN_FLAG, "1")
    monkeypatch.delenv(INTERNAL_COMPOSE_FLAG, raising=False)
    monkeypatch.setenv(
        DSN_VARIABLE,
        "postgresql://e2e:synthetic-only@postgres:5432/e2e_payfast_abc123def456",
    )

    try:
        E2EConfig.from_environment()
    except E2EConfigurationError as error:
        assert "owned internal Compose" in str(error)
    else:
        raise AssertionError("internal Compose host must require explicit ownership")


def test_rejects_internal_compose_database_without_payfast_prefix(monkeypatch) -> None:
    monkeypatch.setenv(OPT_IN_FLAG, "1")
    monkeypatch.setenv(INTERNAL_COMPOSE_FLAG, "1")
    monkeypatch.setenv(
        DSN_VARIABLE,
        "postgresql://e2e:synthetic-only@postgres:5432/e2e_other_abc123def456",
    )

    try:
        E2EConfig.from_environment()
    except E2EConfigurationError as error:
        assert "owned internal Compose" in str(error)
    else:
        raise AssertionError("only the lifecycle-owned PayFast database is valid")
