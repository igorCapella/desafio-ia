from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openrouter_api_key: str = ""
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "deepseek/deepseek-v4.1-flash"
    llm_model_reserva: str = "deepseek/deepseek-v4-pro-0813"
    reasoning_effort: str = "high"
    force_ipv4: bool = False
    orcamento_usd: float = 3.0
    mascarar_cpf: bool = True
    db_path: str = "data/desafio.sqlite"


@lru_cache
def get_settings() -> Settings:
    return Settings()
