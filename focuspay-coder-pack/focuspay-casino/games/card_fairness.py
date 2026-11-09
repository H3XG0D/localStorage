"""Shared provably-fair copy for baccarat and blackjack."""
from __future__ import annotations

import html
from urllib.parse import urlencode

import config

_STAGING_FAIRNESS_PAGE = "http://127.0.0.1:18081/casino/fairness"


def fairness_page_base() -> str:
    configured = (getattr(config, "CASINO_FAIRNESS_URL", "") or "").rstrip("/")
    if configured:
        return configured
    if str(getattr(config, "ENVIRONMENT", "") or "").strip().lower() == "staging":
        return _STAGING_FAIRNESS_PAGE
    return ""


def fairness_href(url: str) -> str:
    return html.escape(url, quote=True)


def apply_fairness_fields(game: dict, payload: dict) -> None:
    commit = payload.get("rng_commit")
    if isinstance(commit, str) and commit:
        game["rng_commit"] = commit
    client_seed = payload.get("client_seed")
    if isinstance(client_seed, str) and client_seed:
        game["client_seed"] = client_seed
    nonce = payload.get("nonce")
    if isinstance(nonce, bool):
        pass
    elif isinstance(nonce, int) or (isinstance(nonce, str) and nonce.lstrip("-").isdigit()):
        game["nonce"] = int(nonce)
    pair = payload.get("pair_commit")
    if isinstance(pair, str) and pair:
        game["pair_commit"] = pair


def waiting_fairness_text(game: dict) -> str:
    commit = game.get("rng_commit")
    if not isinstance(commit, str) or not commit:
        return ""
    lines = [f"Колода зафиксирована: <code>{commit}</code>"]
    client_seed = game.get("client_seed")
    if isinstance(client_seed, str) and client_seed:
        lines.append(f"Клиентский сид: <code>{client_seed}</code>")
    nonce = game.get("nonce")
    if isinstance(nonce, int) or (isinstance(nonce, str) and str(nonce).lstrip("-").isdigit()):
        lines.append(f"Nonce: <code>{int(nonce)}</code>")
    return "\n" + "\n".join(lines)


def verify_url(
    *,
    game_type: str,
    game_id: str,
    commit: str | None,
    client_seed: str | None,
    nonce: object,
    server_seed: str | None = None,
) -> str:
    base = fairness_page_base()
    if not base:
        return ""
    query = {
        "game_type": game_type,
        "game_id": game_id,
        "commit": commit or "",
        "client_seed": client_seed or "focuspay",
        "nonce": str(int(nonce) if isinstance(nonce, int) or (isinstance(nonce, str) and str(nonce).lstrip("-").isdigit()) else 0),
    }
    if server_seed:
        query["server_seed"] = server_seed
    return f"{base}?{urlencode(query)}"


def result_fairness_text(*, game_type: str, game: dict, seed: str | None) -> str:
    if not isinstance(seed, str) or not seed:
        return ""
    lines = [f"Сид: <code>{seed}</code>"]
    client_seed = game.get("client_seed")
    if isinstance(client_seed, str) and client_seed:
        lines.append(f"Клиентский сид: <code>{client_seed}</code>")
    nonce = game.get("nonce")
    if isinstance(nonce, int) or (isinstance(nonce, str) and str(nonce).lstrip("-").isdigit()):
        lines.append(f"Nonce: <code>{int(nonce)}</code>")
    url = verify_url(
        game_type=game_type,
        game_id=str(game.get("settlement_game_id") or ""),
        commit=game.get("rng_commit") if isinstance(game.get("rng_commit"), str) else None,
        client_seed=client_seed if isinstance(client_seed, str) else None,
        nonce=nonce,
        server_seed=seed,
    )
    if url:
        lines.append(f'<a href="{fairness_href(url)}">Проверить раунд</a>')
    else:
        lines.append("Проверка: страница /casino/fairness")
    return "\n\n" + "\n".join(lines)
