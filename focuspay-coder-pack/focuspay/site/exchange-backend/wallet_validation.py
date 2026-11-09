"""Проверка адресов криптокошельков и реквизитов для выплаты в рублях."""
import re

from config import settings

_BTC = re.compile(r"^(bc1|[13])[a-zA-HJ-NP-Z0-9]{25,62}$")
_LTC = re.compile(r"^(ltc1|[LM])[a-zA-HJ-NP-Z0-9]{25,62}$")
_TRON = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")
_EVM = re.compile(r"^0x[a-fA-F0-9]{40}$")


def _our_deposit_addresses() -> set[str]:
    out: set[str] = set()
    for coin, nets in settings.sell_wallets.items():
        if isinstance(nets, dict):
            for addr in nets.values():
                a = str(addr or "").strip()
                if a and "REPLACE" not in a.upper():
                    out.add(a.strip().lower())
        elif nets:
            a = str(nets).strip()
            if a and "REPLACE" not in a.upper():
                out.add(a.lower())
    return out


def crypto_display(crypto: str, network: str | None) -> str:
    c = crypto.lower()
    if c == "usdt" and network:
        return f"USDT ({network.upper()})"
    return c.upper()


def clean_crypto_address(address: str) -> str:
    """Убирает пробелы и случайные слэши/кавычки по краям адреса."""
    raw = (address or "").strip()
    if not raw:
        return ""
    token = raw.split()[0]
    return token.strip("\\/\"'`.,;:")


def validate_buy_wallet(crypto: str, network: str | None, address: str) -> None:
    """Проверяет адрес получателя при покупке крипты. Raises ValueError с текстом для пользователя."""
    addr = clean_crypto_address(address)
    if len(addr) < 10:
        raise ValueError("Укажите адрес кошелька (минимум 10 символов)")

    c = crypto.lower()
    net = (network or "").lower()

    if addr.lower() in _our_deposit_addresses():
        raise ValueError(
            "Это адрес сервиса для приёма крипты при продаже. "
            "Укажите свой личный кошелёк для получения."
        )

    if c == "btc":
        if not _BTC.match(addr):
            raise ValueError("Неверный формат адреса Bitcoin (ожидается bc1…, 1… или 3…)")
        if addr.startswith("0x") or addr.startswith("T"):
            raise ValueError("Похоже на адрес другой сети. Для BTC нужен Bitcoin-адрес.")
        return

    if c == "ltc":
        if not _LTC.match(addr):
            raise ValueError("Неверный формат адреса Litecoin (ожидается ltc1…, L… или M…)")
        if addr.startswith("0x") or addr.startswith("T"):
            raise ValueError("Похоже на адрес другой сети. Для LTC нужен Litecoin-адрес.")
        return

    if c == "trx":
        if not _TRON.match(addr):
            raise ValueError("Неверный формат адреса TRON (34 символа, начинается с T)")
        if addr.startswith("0x"):
            raise ValueError("Это адрес сети Ethereum/ERC20. Для TRX выберите TRON-адрес (T…).")
        return

    if c == "usdt":
        if net == "trc20":
            if addr.startswith("0x"):
                raise ValueError(
                    "Адрес ERC20 (0x…) не подходит для сети TRC20. "
                    "Выберите сеть ERC20 или укажите TRON-адрес (T…)."
                )
            if not _TRON.match(addr):
                raise ValueError("Для USDT TRC20 нужен TRON-адрес: 34 символа, начинается с T")
            return
        if net == "erc20":
            if addr.startswith("T") and _TRON.match(addr):
                raise ValueError(
                    "Адрес TRC20 (T…) не подходит для сети ERC20. "
                    "Выберите сеть TRC20 или укажите адрес 0x…"
                )
            if not _EVM.match(addr):
                raise ValueError("Для USDT ERC20 нужен адрес Ethereum: 0x и 40 hex-символов")
            return
        raise ValueError("Укажите сеть USDT: TRC20 или ERC20")

    raise ValueError("Неподдерживаемая криптовалюта")


def validate_sell_fiat_requisites(text: str) -> None:
    """Реквизиты для выплаты рублей при продаже крипты."""
    t = (text or "").strip()
    if len(t) < 10:
        raise ValueError("Укажите реквизиты: карта + банк или телефон СБП + банк (мин. 10 символов)")

    digits = re.sub(r"\D", "", t)
    if len(digits) >= 10:
        return
    if len(t) >= 15 and re.search(r"[а-яА-Яa-zA-Z]", t):
        return
    raise ValueError(
        "Пример: 7777444466668888 Т-банк или +79991234567 Сбербанк"
    )
