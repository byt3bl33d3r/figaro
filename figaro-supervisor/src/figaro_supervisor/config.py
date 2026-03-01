"""Configuration settings for the Figaro Supervisor service."""

import socket

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Supervisor service configuration."""

    # Connection settings
    nats_url: str = "nats://localhost:4222"
    supervisor_id: str | None = None

    # Reconnection settings
    heartbeat_interval: float = 30.0

    # Claude SDK settings
    model: str = "claude-opus-4-6"
    max_turns: int | None = None

    model_config = SettingsConfigDict(env_prefix="SUPERVISOR_")

    def get_supervisor_id(self) -> str:
        """Get or generate a supervisor ID."""
        return self.supervisor_id or socket.gethostname()
