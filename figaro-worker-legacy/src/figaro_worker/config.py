import socket

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    nats_url: str = "nats://localhost:4222"
    worker_id: str | None = None
    heartbeat_interval: float = 30.0
    reconnect_delay: float = 1.0
    max_reconnect_delay: float = 60.0
    novnc_url: str | None = None
    novnc_port: int = 6080
    model: str = "claude-opus-4-6"

    model_config = SettingsConfigDict(env_prefix="WORKER_")

    def get_worker_id(self) -> str:
        return self.worker_id or socket.gethostname()

    def get_novnc_url(self) -> str:
        if self.novnc_url:
            return self.novnc_url
        # Auto-detect hostname and construct URL
        hostname = socket.gethostname()
        return f"ws://{hostname}:{self.novnc_port}/websockify"
