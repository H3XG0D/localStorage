from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_SECRET = "dev-secret-key-change-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://doliv:doliv@localhost:5432/doliv"
    SECRET_KEY: str = _DEFAULT_SECRET
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024  # 10 MB
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    # Set to "true" in docker-compose.yml / .env for local development
    DEV_MODE: bool = False
    # Default false so HTTP deployments work. Set true only behind HTTPS.
    COOKIE_SECURE: bool = False
    # Rapira / market rate for exposure & default target_rate (lab fallback 90)
    RAPIRA_RATE_FALLBACK: float = 90.0
    RAPIRA_RATE_URL: str = "https://api.rapira.net/open/market/rates"
    # Fixed lab credentials (DEV_MODE only) — FocusPay adapter + Merchant smoke
    LAB_BRIDGE_KEY: str = "doliv-lab-bridge-dev-key"
    LAB_MERCHANT_API_KEY: str = "lab_merchant_key"
    LAB_MERCHANT_SECRET: str = "lab_merchant_secret"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    def check_secrets(self) -> None:
        if self.SECRET_KEY == _DEFAULT_SECRET and not self.DEV_MODE:
            raise RuntimeError(
                "SECRET_KEY is the insecure default value. "
                "Set SECRET_KEY in your .env file before deploying. "
                "Set DEV_MODE=true for local development only."
            )


settings = Settings()
settings.check_secrets()
