"""Gateway configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    nats_url: str = "nats://localhost:4222"

    # Telegram channel config
    telegram_bot_token: str | None = None
    telegram_allowed_chat_ids: list[int] = []

    model_config = SettingsConfigDict(env_prefix="GATEWAY_")
