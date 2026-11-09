"""Network-based withdraw fees for wallet requests."""
from __future__ import annotations

from decimal import Decimal

from app.models import CryptoNetwork

# USDT $3; BTC/LTC $2; other defaults to USDT fee
FEE_BY_NETWORK: dict[CryptoNetwork, Decimal] = {
    CryptoNetwork.usdt_trc20: Decimal("3"),
    CryptoNetwork.btc: Decimal("2"),
    CryptoNetwork.ltc: Decimal("2"),
    CryptoNetwork.other: Decimal("3"),
}


def fee_for_network(network: CryptoNetwork | str) -> Decimal:
    if isinstance(network, str):
        try:
            network = CryptoNetwork(network)
        except ValueError:
            return Decimal("3")
    return FEE_BY_NETWORK.get(network, Decimal("3"))
