from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Quinta da Baroneza - Agendamento de Tee"
    SECRET_KEY: str = "troque-por-uma-chave-segura-em-producao"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "sqlite:///./quinta_baroneza.db"

    # Evolution API (WhatsApp)
    EVOLUTION_API_URL: str = ""
    EVOLUTION_API_KEY: str = ""
    EVOLUTION_INSTANCE: str = ""

    # Scheduling rules (defaults — can be overridden via SystemConfig in DB)
    DEFAULT_BOOKING_WINDOW_DAYS: int = 14
    DEFAULT_TEE_INTERVAL_MINUTES: int = 10
    DEFAULT_REQUEST_TIMEOUT_HOURS: int = 1
    DEFAULT_CANCEL_DEADLINE_HOURS: int = 24

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
