"""Gateway configuration."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    nats_url: str = "nats://localhost:4222"

    # Telegram channel config
    telegram_bot_token: str | None = None
    telegram_allowed_chat_ids: list[int] = []

    # STT (speech-to-text) config for voice messages
    stt_base_url: str = "wss://claude.ai"
    stt_credentials_path: Path = Path.home() / ".claude" / ".credentials.json"

    model_config = SettingsConfigDict(env_prefix="GATEWAY_")
