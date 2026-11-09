from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    signer_api_key: str = "focuspay-main"
    signer_secret_key: str = ""
    bind_host: str = "10.8.0.2"
    bind_port: int = 9000
    max_tx_rub: float = 10_000.0
    max_tx_btc: float = 0.05
    max_tx_ltc: float = 20.0
    daily_cap_btc: float = 0.2
    daily_cap_ltc: float = 60.0
    fee_pct_cap: float = 5.0
    dry_run: bool = True
    audit_path: str = "/var/lib/focuspay-signer/audit.log"
    # Запятая/точка с запятой: адреса, на которые отправка запрещена всегда.
    address_blocklist: str = ""

    btc_rpc_url: str = "http://127.0.0.1:8332"
    btc_rpc_user: str = ""
    btc_rpc_password: str = ""
    btc_rpc_wallet: str = "hot"
    ltc_rpc_url: str = "http://127.0.0.1:9332"
    ltc_rpc_user: str = ""
    ltc_rpc_password: str = ""
    ltc_rpc_wallet: str = "hot"
    conf_target: int = 6
    estimate_mode: str = "economical"
    # BTC считаем отдельно от LTC: клиенту обещаны ~10 минут, поэтому цель — следующий
    # блок, а не conf_target=6, иначе оценка почти всегда падает на нижнюю ставку.
    btc_conf_target: int = 1
    btc_estimate_mode: str = "conservative"
    # Нижняя ставка для выплат BTC. Ниже кошелёк всё равно не ставит (mintxfee 1 sat/vB),
    # а оценка ноды бывает 0.3 — окно оператора показывало бы не ту комиссию.
    btc_min_fee_rate_sat_vb: float = 1.5
    # Потолок ставки выплаты. В сильный шторм выше этого tx может ждать блока —
    # ускоряем через RBF (/v1/tx/bump-quotes), а не поднимая потолок.
    btc_max_fee_rate_sat_vb: float = 10.0
    # Пополнение, отмеченное админом, можно тратить до подтверждения (только BTC).
    trusted_topups_enabled: bool = False
    # Сколько BTC доверенных пополнений одновременно может ждать подтверждения.
    trusted_topup_max_btc: float = 0.05

    class Config:
        env_file = "/etc/focuspay/signer.env"
        env_file_encoding = "utf-8"


settings = Settings()
