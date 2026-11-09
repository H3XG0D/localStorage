"""HTTP-клиент для взаимодействия с FocusPay API."""
import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time
from decimal import Decimal
from typing import Optional, Dict, Any

import httpx

from config import (
    FOCUSPAY_API_URL,
    FOCUSPAY_INTERNAL_TOKEN,
    FOCUSPAY_EXCHANGER_API_KEY,
    FOCUSPAY_EXCHANGER_SECRET,
)
from finance import money

logger = logging.getLogger(__name__)


class FocusPayClient:
    """Клиент для FocusPay Internal API и Exchanger API."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        internal_token: Optional[str] = None,
        api_key: Optional[str] = None,
        secret: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.entry_check = None
        self.base_url = (base_url or FOCUSPAY_API_URL).rstrip("/")
        self.internal_token = (
            FOCUSPAY_INTERNAL_TOKEN if internal_token is None else internal_token
        )
        self.api_key = FOCUSPAY_EXCHANGER_API_KEY if api_key is None else api_key
        self.secret = FOCUSPAY_EXCHANGER_SECRET if secret is None else secret
        self.client = http_client or httpx.AsyncClient(timeout=30.0)

    async def _check_entry(self, user_id, *, game_chat_id=None):
        if self.entry_check is not None:
            if game_chat_id is None:
                await self.entry_check(user_id)
            else:
                await self.entry_check(user_id, game_chat_id=game_chat_id)

    async def close(self):
        """Закрыть HTTP-клиент."""
        await self.client.aclose()

    # ========================================================================
    # INTERNAL API (Casino)
    # ========================================================================

    def _internal_headers(self) -> Dict[str, str]:
        """Заголовки для Internal API."""
        return {
            "X-Internal-Token": self.internal_token,
            "Content-Type": "application/json",
        }

    async def get_balance(self, telegram_id: int) -> float:
        """Получить доступный баланс игрока."""
        url = f"{self.base_url}/api/internal/casino/users/{telegram_id}/balance"
        response = await self.client.get(url, headers=self._internal_headers())
        response.raise_for_status()
        data = response.json()
        return float(data["available_rub"])

    async def get_wagering(self, telegram_id: int) -> Dict[str, Any]:
        """Прогресс отыгрыша: сколько ещё нужно сыграть, чтобы открыть вывод."""
        url = f"{self.base_url}/api/internal/casino/users/{telegram_id}/wagering"
        response = await self.client.get(url, headers=self._internal_headers())
        response.raise_for_status()
        return response.json()

    async def get_profile(self, telegram_id: int) -> Dict[str, Any]:
        """Получить сводный профиль игрока казино."""
        url = f"{self.base_url}/api/internal/casino/users/{telegram_id}/profile"
        response = await self.client.get(url, headers=self._internal_headers())
        response.raise_for_status()
        return response.json()

    async def get_clan(self, telegram_id: int) -> Dict[str, Any]:
        url = f"{self.base_url}/api/internal/casino/users/{telegram_id}/clan"
        response = await self.client.get(url, headers=self._internal_headers())
        response.raise_for_status()
        return response.json()

    async def attach_web_login(
        self,
        *,
        start_token: str,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Mark a waiting site login (cauth_ Start). None if the link expired."""
        url = f"{self.base_url}/api/auth/telegram/bot-attach"
        response = await self.client.post(
            url,
            json={
                "start_token": start_token,
                "telegram_user_id": telegram_id,
                "username": username,
                "first_name": first_name,
            },
            headers=self._internal_headers(),
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    async def get_clan_top(self) -> Dict[str, Any]:
        url = f"{self.base_url}/api/internal/casino/clans/top"
        response = await self.client.get(url, headers=self._internal_headers())
        response.raise_for_status()
        return response.json()

    async def create_clan(self, *, telegram_id: int, tag: str, name: str) -> Dict[str, Any]:
        url = f"{self.base_url}/api/internal/casino/clans"
        response = await self.client.post(
            url,
            json={"telegram_id": telegram_id, "tag": tag, "name": name},
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def join_clan(self, *, telegram_id: int, code: str) -> Dict[str, Any]:
        url = f"{self.base_url}/api/internal/casino/clans/join"
        response = await self.client.post(
            url,
            json={"telegram_id": telegram_id, "code": code},
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def leave_clan(self, *, telegram_id: int) -> Dict[str, Any]:
        url = f"{self.base_url}/api/internal/casino/clans/leave"
        response = await self.client.post(
            url,
            json={"telegram_id": telegram_id},
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def kick_clan_member(self, *, telegram_id: int, target_id: int) -> Dict[str, Any]:
        url = f"{self.base_url}/api/internal/casino/clans/kick"
        response = await self.client.post(
            url,
            json={"telegram_id": telegram_id, "target_id": target_id},
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def rotate_clan_invite(self, *, telegram_id: int) -> Dict[str, Any]:
        url = f"{self.base_url}/api/internal/casino/clans/invite"
        response = await self.client.post(
            url,
            json={"telegram_id": telegram_id},
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def transfer_clan(self, *, telegram_id: int, target_id: int) -> Dict[str, Any]:
        url = f"{self.base_url}/api/internal/casino/clans/transfer"
        response = await self.client.post(
            url,
            json={"telegram_id": telegram_id, "target_id": target_id},
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def disband_clan(self, *, telegram_id: int) -> Dict[str, Any]:
        url = f"{self.base_url}/api/internal/casino/clans/disband"
        response = await self.client.post(
            url,
            json={"telegram_id": telegram_id},
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def get_profile_avatar(self, telegram_id: int) -> bytes | None:
        """Получить аватар профиля только по внутреннему авторизованному каналу."""
        url = f"{self.base_url}/api/internal/casino/users/{telegram_id}/avatar"
        response = await self.client.get(url, headers=self._internal_headers())
        if response.status_code == 404:
            return None
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        content = response.content
        if not content_type.startswith("image/") or not 64 <= len(content) <= 5 * 1024 * 1024:
            raise ValueError("Casino profile avatar response is invalid")
        return content

    async def prepare_cub(self, *, telegram_id: int) -> Dict[str, Any]:
        """Получить commit честного RNG до выбора ставки пользователем."""
        url = f"{self.base_url}/api/internal/casino/cub/prepare"
        response = await self.client.post(
            url,
            json={"telegram_id": telegram_id},
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def play_cub(
        self,
        *,
        game_id: str,
        telegram_id: int,
        stake_rub: Decimal | str | int | float,
    ) -> Dict[str, Any]:
        """Сыграть одиночный кубик против отдельного резерва казино."""
        await self._check_entry(telegram_id)
        url = f"{self.base_url}/api/internal/casino/cub/play"
        response = await self.client.post(
            url,
            json={
                "game_id": str(game_id),
                "telegram_id": telegram_id,
                "stake_rub": format(money(stake_rub), "f"),
            },
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def open_cub(
        self,
        *,
        telegram_id: int,
        stake_rub: Decimal | str | int | float,
    ) -> Dict[str, Any]:
        """Hold a house cub stake and wait for live Telegram dice."""
        await self._check_entry(telegram_id)
        url = f"{self.base_url}/api/internal/casino/cub/open"
        response = await self.client.post(
            url,
            json={
                "telegram_id": telegram_id,
                "stake_rub": format(money(stake_rub), "f"),
            },
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def resolve_cub(
        self,
        *,
        game_id: str,
        telegram_id: int,
        player_value: int,
        house_value: int,
    ) -> Dict[str, Any]:
        """Settle a waiting house cub from two live dice values."""
        url = f"{self.base_url}/api/internal/casino/cub/resolve"
        response = await self.client.post(
            url,
            json={
                "game_id": str(game_id),
                "telegram_id": telegram_id,
                "player_value": int(player_value),
                "house_value": int(house_value),
            },
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def get_pending_cub(self, *, telegram_id: int) -> Dict[str, Any]:
        """Return the waiting house cub for this player, if any."""
        url = f"{self.base_url}/api/internal/casino/cub/pending"
        response = await self.client.get(
            url,
            params={"telegram_id": telegram_id},
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def prepare_cards(
        self,
        *,
        game_id: str,
        game_type: str,
        telegram_id: int,
    ) -> Dict[str, Any]:
        """Commit the card shoe hash before the creator stake is held."""
        url = f"{self.base_url}/api/internal/casino/cards/prepare"
        response = await self.client.post(
            url,
            json={
                "game_id": str(game_id),
                "game_type": game_type,
                "telegram_id": telegram_id,
            },
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def deal_cards(
        self,
        *,
        game_id: str,
        telegram_id: int,
        hand_size: int,
    ) -> Dict[str, Any]:
        """Deal from the backend shoe. The bot must not shuffle."""
        url = f"{self.base_url}/api/internal/casino/cards/deal"
        response = await self.client.post(
            url,
            json={
                "game_id": str(game_id),
                "telegram_id": telegram_id,
                "hand_size": int(hand_size),
            },
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def reveal_cards(self, *, game_id: str, telegram_id: int) -> Dict[str, Any]:
        """Reveal the committed shoe seed after the round."""
        url = f"{self.base_url}/api/internal/casino/cards/reveal"
        response = await self.client.post(
            url,
            json={"game_id": str(game_id), "telegram_id": telegram_id},
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def fairness_session(self, *, telegram_id: int) -> Dict[str, Any]:
        url = f"{self.base_url}/api/internal/casino/fairness/session"
        response = await self.client.get(
            url,
            params={"telegram_id": telegram_id},
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def set_fairness_client_seed(self, *, telegram_id: int, client_seed: str) -> Dict[str, Any]:
        url = f"{self.base_url}/api/internal/casino/fairness/client-seed"
        response = await self.client.post(
            url,
            json={"telegram_id": telegram_id, "client_seed": client_seed},
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def rotate_fairness_seeds(self, *, telegram_id: int) -> Dict[str, Any]:
        url = f"{self.base_url}/api/internal/casino/fairness/rotate"
        response = await self.client.post(
            url,
            json={"telegram_id": telegram_id},
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def hold_balance(
        self,
        telegram_id: int,
        game_id: str,
        amount_rub: Decimal | str | int | float,
        role: str = "player",
    ) -> Dict[str, Any]:
        """Заблокировать баланс для ставки."""
        await self._check_entry(telegram_id)
        url = f"{self.base_url}/api/internal/casino/games/hold"
        payload = {
            "telegram_id": telegram_id,
            "game_id": game_id,
            "amount_rub": format(money(amount_rub), "f"),
            "role": role,
        }
        response = await self.client.post(
            url, json=payload, headers=self._internal_headers()
        )
        response.raise_for_status()
        return response.json()

    async def confirm_bet(self, *, hold_id: str) -> Dict[str, Any]:
        """Подтвердить холд (списать баланс)."""
        url = f"{self.base_url}/api/internal/casino/games/confirm"
        payload = {"hold_id": hold_id}
        response = await self.client.post(
            url, json=payload, headers=self._internal_headers()
        )
        response.raise_for_status()
        return response.json()

    async def release_bet(self, *, hold_id: str) -> Dict[str, Any]:
        """Отменить холд (вернуть баланс)."""
        url = f"{self.base_url}/api/internal/casino/games/release"
        payload = {"hold_id": hold_id}
        response = await self.client.post(
            url, json=payload, headers=self._internal_headers()
        )
        response.raise_for_status()
        return response.json()

    async def credit_deposit(self, *, deal_id: int) -> Dict[str, Any]:
        """Идемпотентно зачислить подтверждённое пополнение по ID сделки."""
        url = f"{self.base_url}/api/internal/casino/deposits/credit"
        response = await self.client.post(
            url,
            json={"deal_id": deal_id},
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def payout(
        self,
        *,
        telegram_id: int,
        game_id: str,
        amount_rub: Decimal | str | int | float,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Зачислить выигрыш игроку."""
        url = f"{self.base_url}/api/internal/casino/games/payout"
        payload = {
            "telegram_id": telegram_id,
            "game_id": game_id,
            "amount_rub": format(
                Decimal(str(amount_rub)).quantize(Decimal("0.01")), "f"
            ),
        }
        if note:
            payload["note"] = note
        response = await self.client.post(
            url, json=payload, headers=self._internal_headers()
        )
        response.raise_for_status()
        return response.json()

    async def distribute_commissions(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Не выполнять legacy-распределение комиссии со стороны бота.

        Денежные доли и реферальную цепочку формирует только атомарный
        ``/games/settle``. Сигнатура принимает старые вызовы для совместимости,
        но намеренно не отправляет запрос и не создаёт двойных начислений.
        """
        logger.warning(
            "Legacy client commission distribution skipped; "
            "atomic backend settlement owns commission allocation"
        )
        return {
            "success": False,
            "skipped": True,
            "reason": "commission_is_managed_by_atomic_backend_settlement",
        }

    async def settle_head_to_head_game(
        self,
        *,
        game_id: str,
        game_type: str,
        creator_id: int,
        opponent_id: int,
        winner_id: int,
        creator_hold_id: str,
        opponent_hold_id: str,
        stake_rub: Decimal | str | int | float,
    ) -> Dict[str, Any]:
        """Атомарно завершить head-to-head игру на доверенном backend.

        Backend подтверждает оба холда, рассчитывает комиссию из актуальных
        настроек, выплачивает победителю, сохраняет игру и распределяет доли
        комиссии в одной транзакции. ``game_id`` одновременно служит ключом
        идемпотентности; бот не передаёт комиссию или реферальную цепочку.
        """
        payload = {
            "game_id": str(game_id),
            "game_type": game_type,
            "creator_id": creator_id,
            "opponent_id": opponent_id,
            "winner_id": winner_id,
            "creator_hold_id": creator_hold_id,
            "opponent_hold_id": opponent_hold_id,
            "stake_rub": format(money(stake_rub), "f"),
        }
        url = f"{self.base_url}/api/internal/casino/games/settle"
        response = await self.client.post(
            url,
            json=payload,
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def get_roulette_table(self, telegram_id: int | None = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if telegram_id is not None:
            params["telegram_id"] = telegram_id
        response = await self.client.get(
            f"{self.base_url}/api/internal/casino/roulette-table",
            params=params or None,
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Roulette table snapshot must be an object")
        return data

    async def place_roulette_table_bet(
        self,
        *,
        telegram_id: int,
        notify_chat_id: int,
        bet: str | None = None,
        amount_rub: Any = None,
        chips: list[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        await self._check_entry(telegram_id)
        payload: Dict[str, Any] = {
            "telegram_id": telegram_id,
            "notify_chat_id": notify_chat_id,
        }
        if chips:
            payload["chips"] = chips
        else:
            payload["bet"] = bet
            payload["amount_rub"] = format(money(amount_rub), "f")
        return await self._post_internal("/roulette-table/bet", payload)

    async def get_jackpot(self, telegram_id: int | None = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if telegram_id is not None:
            params["telegram_id"] = telegram_id
        response = await self.client.get(
            f"{self.base_url}/api/internal/casino/jackpot",
            params=params or None,
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Jackpot snapshot must be an object")
        return data

    async def place_jackpot_bet(
        self,
        *,
        telegram_id: int,
        notify_chat_id: int,
        amount_rub: Any,
    ) -> Dict[str, Any]:
        await self._check_entry(telegram_id)
        return await self._post_internal(
            "/jackpot/bet",
            {
                "telegram_id": telegram_id,
                "notify_chat_id": notify_chat_id,
                "amount_rub": format(money(amount_rub), "f"),
            },
        )

    async def list_fixed_rooms(self, telegram_id: int | None = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if telegram_id is not None:
            params["telegram_id"] = telegram_id
        return await self._get_internal("/rooms", params)

    async def get_fixed_room(self, room_id: str, telegram_id: int | None = None) -> Dict[str, Any]:
        token = str(room_id or "").strip()
        if not token:
            raise ValueError("room_id must not be blank")
        params: Dict[str, Any] = {}
        if telegram_id is not None:
            params["telegram_id"] = telegram_id
        return await self._get_internal(f"/rooms/{token}", params)

    async def create_fixed_room(
        self,
        *,
        telegram_id: int,
        stake_rub: Any,
        seat_count: int,
    ) -> Dict[str, Any]:
        await self._check_entry(telegram_id)
        return await self._post_internal(
            "/rooms",
            {
                "telegram_id": telegram_id,
                "stake_rub": format(money(stake_rub), "f"),
                "seat_count": int(seat_count),
            },
        )

    async def join_fixed_room(self, room_id: str, *, telegram_id: int) -> Dict[str, Any]:
        await self._check_entry(telegram_id)
        return await self._post_internal(
            f"/rooms/{str(room_id).strip()}/join",
            {"telegram_id": telegram_id},
        )

    async def leave_fixed_room(self, room_id: str, *, telegram_id: int) -> Dict[str, Any]:
        return await self._post_internal(
            f"/rooms/{str(room_id).strip()}/leave",
            {"telegram_id": telegram_id},
        )

    async def cancel_fixed_room(self, room_id: str, *, telegram_id: int) -> Dict[str, Any]:
        return await self._post_internal(
            f"/rooms/{str(room_id).strip()}/cancel",
            {"telegram_id": telegram_id},
        )

    async def add_fixed_room_bot(self, room_id: str, *, telegram_id: int) -> Dict[str, Any]:
        return await self._post_internal(
            f"/rooms/{str(room_id).strip()}/bots",
            {"telegram_id": telegram_id},
        )

    async def get_casino_settings(self) -> Dict[str, Any]:
        """Получить настройки казино."""
        url = f"{self.base_url}/api/internal/casino/settings"
        response = await self.client.get(url, headers=self._internal_headers())
        response.raise_for_status()
        return response.json()

    async def get_active_game_chat_binding(self) -> Dict[str, Any] | None:
        """Get the administrator-confirmed PVP chat without exposing configuration."""
        response = await self.client.get(
            f"{self.base_url}/api/internal/casino/chat-binding/active",
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or "binding" not in data:
            raise ValueError("Active game chat binding response is invalid")
        binding = data["binding"]
        if binding is not None and not isinstance(binding, dict):
            raise ValueError("Active game chat binding must be an object or null")
        return binding

    async def create_pending_game_chat_binding(
        self,
        *,
        chat_id: int,
        chat_type: str,
        chat_title: str | None,
        requested_by_telegram_id: int,
        telegram_url: str | None = None,
    ) -> Dict[str, Any]:
        """Submit a group binding request for administrator approval."""
        return await self._post_internal(
            "/chat-binding/pending",
            {
                "chat_id": chat_id,
                "chat_type": chat_type,
                "chat_title": chat_title,
                "telegram_url": telegram_url,
                "requested_by_telegram_id": requested_by_telegram_id,
            },
        )

    # ========================================================================
    # MULTIPLAYER V2 LIFECYCLE (Internal API)
    # ========================================================================

    async def create_v2_table(self, **payload: Any) -> Dict[str, Any]:
        await self._check_entry(payload.get("creator_id"), game_chat_id=payload.get("game_chat_id"))
        return await self._post_internal("/v2/tables", payload)

    async def v2_table_operation(self, table_id: str, operation: str, **payload: Any) -> Dict[str, Any]:
        if operation == "seats":
            await self._check_entry(payload.get("telegram_id"))
        return await self._post_internal(f"/v2/tables/{table_id}/{operation}", payload)

    async def v2_tables_get(self, path: str) -> Dict[str, Any]:
        response = await self.client.get(
            f"{self.base_url}/api/internal/casino{path}",
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError(f"Internal API {path} response must be an object")
        return data

    async def v2_recovery_or_outbox(self, path: str, **payload: Any) -> Dict[str, Any]:
        return await self._post_internal(path, payload)

    async def v2_table_cards(self, table_id: str, operation: str, **payload: Any) -> Dict[str, Any]:
        return await self._post_internal(f"/v2/tables/{table_id}/cards/{operation}", payload)


    async def _get_internal(self, path: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
        response = await self.client.get(
            f"{self.base_url}/api/internal/casino{path}",
            params=params or None,
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError(f"Internal API {path} response must be an object")
        return data

    async def _post_internal(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST an Internal API request and require an object response."""
        response = await self.client.post(
            f"{self.base_url}/api/internal/casino{path}",
            json=payload,
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError(f"Internal API {path} response must be an object")
        return data

    async def get_active_pvp_games(self) -> list[Dict[str, Any]]:
        """Load recoverable PVP UI snapshots without changing game state."""
        response = await self.client.get(
            f"{self.base_url}/api/internal/casino/games/active",
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        data = response.json()
        games = data.get("games") if isinstance(data, dict) else None
        if not isinstance(games, list) or not all(isinstance(game, dict) for game in games):
            raise ValueError("Active casino games response is invalid")
        return games

    async def create_or_resume_game(
        self,
        game_id: str,
        game_type: str,
        creator_id: int,
        stake_rub: Decimal | str | int | float,
    ) -> Dict[str, Any]:
        """Create a durable game and creator hold, or resume its same contract."""
        await self._check_entry(creator_id)
        return await self._post_internal(
            "/games/create-or-resume",
            {
                "game_id": str(game_id),
                "game_type": game_type,
                "creator_id": creator_id,
                "stake_rub": format(money(stake_rub), "f"),
            },
        )

    async def create_pvp_game_from_dm(
        self,
        *,
        game_id: str,
        game_type: str,
        creator_id: int,
        stake_rub: Decimal | str | int | float,
        rounds: int,
        publish_to_group: bool = False,
    ) -> Dict[str, Any]:
        """Atomically create a held PVP game pinned to the active game chat.
        
        Args:
            game_id: Unique game identifier
            game_type: Game type (pvp_dice, baccara, blackjack, cub)
            creator_id: Telegram ID of creator
            stake_rub: Stake amount in RUB
            rounds: Number of rounds/rolls
            publish_to_group: Whether to publish invitation card to group chat (False for DM-only games)
        """
        await self._check_entry(creator_id)
        return await self._post_internal(
            "/games/create-from-dm",
            {
                "game_id": str(game_id),
                "game_type": game_type,
                "creator_id": creator_id,
                "stake_rub": format(money(stake_rub), "f"),
                "rounds": rounds,
                "publish_to_group": publish_to_group,
            },
        )

    async def claim_pvp_invitations(
        self,
        *,
        worker_id: str,
        limit: int = 50,
        lease_seconds: int = 60,
    ) -> Dict[str, Any]:
        return await self._post_internal(
            "/pvp-invitations/claim",
            {"worker_id": worker_id, "limit": limit, "lease_seconds": lease_seconds},
        )

    async def complete_pvp_invitation(
        self,
        *,
        outbox_id: int,
        claim_token: str,
        telegram_message_id: int,
    ) -> Dict[str, Any]:
        return await self._post_internal(
            "/pvp-invitations/complete",
            {
                "outbox_id": outbox_id,
                "claim_token": claim_token,
                "telegram_message_id": telegram_message_id,
            },
        )

    async def fail_pvp_invitation(
        self,
        *,
        outbox_id: int,
        claim_token: str,
        error: str,
    ) -> Dict[str, Any]:
        return await self._post_internal(
            "/pvp-invitations/fail",
            {"outbox_id": outbox_id, "claim_token": claim_token, "error": error[:1000]},
        )

    async def join_pvp_robot(self, *, game_id: str) -> Dict[str, Any]:
        """Подключить к ожидающей игре робота, обеспеченного банком казино."""
        return await self._post_internal(
            "/games/join-pvp-robot",
            {"game_id": str(game_id)},
        )

    async def join_and_hold_game(
        self,
        game_id: str,
        opponent_id: int,
    ) -> Dict[str, Any]:
        """Atomically join a durable game and create its opponent hold."""
        await self._check_entry(opponent_id)
        return await self._post_internal(
            "/games/join-and-hold",
            {"game_id": str(game_id), "opponent_id": opponent_id},
        )

    async def persist_game_state(
        self,
        game_id: str,
        *,
        expected_state_version: int,
        game_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Persist a compare-and-swap game snapshot for crash recovery."""
        return await self._post_internal(
            "/games/persist-state",
            {
                "game_id": str(game_id),
                "expected_state_version": expected_state_version,
                "game_state": game_state,
            },
        )

    async def record_pvp_dice_roll(
        self,
        *,
        game_id: str,
        telegram_id: int,
        value: int,
    ) -> Dict[str, Any]:
        """Record a live Telegram die without replacing the other seat's HMAC rolls."""
        return await self._post_internal(
            "/games/record-roll",
            {"game_id": str(game_id), "telegram_id": telegram_id, "value": int(value)},
        )

    async def commit_game_outcome(
        self,
        game_id: str,
        winner_id: Optional[int],
        *,
        expected_state_version: int,
        outcome: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Persist the immutable game outcome before any money operation."""
        return await self._post_internal(
            "/games/commit-outcome",
            {
                "game_id": str(game_id),
                "winner_id": winner_id,
                "expected_state_version": expected_state_version,
                "outcome": outcome,
            },
        )

    async def settle_committed_outcome(self, game_id: str) -> Dict[str, Any]:
        """Settle only the backend-persisted outcome for a game."""
        return await self._post_internal(
            "/games/settle-committed-outcome",
            {"game_id": str(game_id)},
        )

    async def settle_committed_game(self, game_id: str) -> Dict[str, Any]:
        """Compatibility alias for the durable committed-outcome settlement."""
        return await self.settle_committed_outcome(game_id)

    async def release_game(
        self,
        game_id: str,
        *,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Release a durable game's active holds through the backend pair flow."""
        payload: Dict[str, Any] = {"game_id": str(game_id)}
        if reason is not None:
            payload["reason"] = reason
        return await self._post_internal("/games/release-game", payload)

    # ========================================================================
    # RECOVERY AND NOTIFICATION OUTBOX (Internal API)
    # ========================================================================

    async def claim_recovery_jobs(
        self,
        *,
        worker_id: str,
        limit: int = 50,
        lease_seconds: int = 60,
    ) -> Dict[str, Any]:
        """Claim a bounded batch of backend-selected recovery jobs."""
        return await self._post_internal(
            "/recovery/claim",
            {
                "worker_id": worker_id,
                "limit": limit,
                "lease_seconds": lease_seconds,
            },
        )

    async def get_recovery_snapshot(self) -> Dict[str, Any]:
        """Read the backend's canonical recovery snapshot without changing it."""
        response = await self.client.get(
            f"{self.base_url}/api/internal/casino/recovery/snapshot",
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Internal API /recovery/snapshot response must be an object")
        return data

    async def complete_recovery_job(
        self,
        *,
        game_id: str,
        claim_token: str,
    ) -> Dict[str, Any]:
        """Acknowledge a successfully processed recovery job."""
        return await self._post_internal(
            "/recovery/complete",
            {"game_id": str(game_id), "claim_token": claim_token},
        )

    async def claim_outbox_messages(
        self,
        *,
        worker_id: str,
        limit: int = 50,
        lease_seconds: int = 60,
    ) -> Dict[str, Any]:
        """Claim a bounded batch of already-financially-terminal notifications."""
        return await self._post_internal(
            "/outbox/claim",
            {
                "worker_id": worker_id,
                "limit": limit,
                "lease_seconds": lease_seconds,
            },
        )

    async def complete_outbox_message(
        self,
        *,
        outbox_id: str | int,
        claim_token: str,
    ) -> Dict[str, Any]:
        """Acknowledge successful Telegram delivery of an outbox message."""
        return await self._post_internal(
            "/outbox/complete",
            {"outbox_id": outbox_id, "claim_token": claim_token},
        )

    async def fail_outbox_message(
        self,
        *,
        outbox_id: str | int,
        claim_token: str,
        error: str,
        error_kind: str = "temporary",
        retry_after_seconds: int | None = None,
    ) -> Dict[str, Any]:
        """Return an undelivered outbox message to backend retry/backoff."""
        return await self._post_internal(
            "/outbox/fail",
            {
                "outbox_id": outbox_id,
                "claim_token": claim_token,
                "error": error,
                "error_kind": error_kind,
                "retry_after_seconds": retry_after_seconds,
            },
        )

    # ========================================================================
    # EXCHANGER API (HMAC)
    # ========================================================================

    def _sign_hmac(self, body: str) -> tuple[str, str]:
        """Создать HMAC-подпись для Exchanger API."""
        timestamp = str(int(time.time()))
        message = (timestamp + body).encode("utf-8")
        signature = hmac.new(
            self.secret.encode("utf-8"), message, hashlib.sha256
        ).hexdigest()
        return timestamp, signature

    def _exchanger_headers(self, body: str) -> Dict[str, str]:
        """Заголовки для Exchanger API с HMAC."""
        timestamp, signature = self._sign_hmac(body)
        return {
            "X-API-Key": self.api_key,
            "X-Timestamp": timestamp,
            "X-Signature": signature,
            "Content-Type": "application/json",
        }

    async def create_deposit(
        self,
        telegram_id: int,
        credit_rub: float,
        callback_url: str,
        sub_token: str = "SBPRUB",
        commission_pct: float = 21.0,
    ) -> Dict[str, Any]:
        """Создать заявку на пополнение игрового баланса через Exchanger API.

        ``credit_rub`` — сумма, которую игрок хочет получить на баланс. К оплате
        по реквизитам выставляется ``credit_rub * (1 + commission_pct/100)``.
        Целевой кредит зашивается в client_transaction_id (в копейках), чтобы
        backend зачислил именно его, а не всю оплату. Возвращает реквизиты
        (СБП/карта) и срок оплаты.
        """
        url = f"{self.base_url}/api/exchanger/v1/deals"
        credit = round(float(credit_rub), 2)
        charged = round(credit * (1.0 + float(commission_pct) / 100.0), 2)
        credit_kopecks = int(round(credit * 100))
        client_tx_id = (
            f"casino-dep-{telegram_id}-c{credit_kopecks}-{secrets.token_urlsafe(24)}"
        )
        payload = {
            "amount_rub": charged,
            "crypto": "usdt",
            "sub_token": sub_token,
            "client_transaction_id": client_tx_id,
            "callback_url": callback_url,
            "fingerprint": f"tg:{telegram_id}",
            "note": f"Casino deposit for user {telegram_id} (credit {credit:.2f})",
        }
        body = json.dumps(payload, separators=(",", ":"))
        headers = self._exchanger_headers(body)

        response = await self.client.post(url, content=body, headers=headers)
        response.raise_for_status()
        return response.json()

    async def cancel_deposit(self, deal_id: int, telegram_id: int) -> Dict[str, Any]:
        """Отменить неоплаченную заявку игрока на пополнение.

        Возвращает {"success": True, ...} при отмене. Бросает httpx.HTTPStatusError
        с кодом 409, если заявка уже оплачена/зачислена — вызывающий это обрабатывает.
        """
        url = f"{self.base_url}/api/internal/casino/deposits/{deal_id}/cancel"
        response = await self.client.post(
            url,
            params={"telegram_id": telegram_id},
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def get_deal_status(self, deal_id: int) -> Dict[str, Any]:
        """Получить статус сделки."""
        url = f"{self.base_url}/api/exchanger/v1/deals/{deal_id}"
        body = ""
        headers = self._exchanger_headers(body)
        response = await self.client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()

    # ========================================================================
    # REFERRAL (Internal API)
    # ========================================================================

    async def get_referrer(self, telegram_id: int) -> Optional[int]:
        """Получить ID реферера пользователя (L1)."""
        # Это нужно будет добавить в Internal API или использовать прямой запрос к БД
        # Пока заглушка
        return None

    async def get_referrer_chain(self, telegram_id: int) -> tuple[Optional[int], Optional[int]]:
        """Получить цепочку рефералов (L1, L2)."""
        # L1
        ref_l1 = await self.get_referrer(telegram_id)
        if not ref_l1:
            return None, None
        
        # L2
        ref_l2 = await self.get_referrer(ref_l1)
        return ref_l1, ref_l2


# Singleton
_client: Optional[FocusPayClient] = None


async def get_focuspay_client() -> FocusPayClient:
    """Получить глобальный экземпляр клиента."""
    global _client
    if _client is None:
        _client = FocusPayClient()
    return _client


async def close_focuspay_client():
    """Закрыть глобальный клиент."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None
