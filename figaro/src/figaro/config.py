from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8000
    heartbeat_timeout: int = 60
    static_dir: str | None = None

    # Help request settings (UI-based)
    # Note: Telegram is now handled by the supervisor service
    help_request_timeout: int = 1800  # 30 minutes default

    # Database settings
    database_url: str = "postgresql+asyncpg://figaro:figaro@localhost/figaro"
    db_pool_size: int = 20
    db_max_overflow: int = 30
    db_echo: bool = False
    db_statement_timeout: int = 30000  # 30 seconds in milliseconds
    db_command_timeout: int = 30  # 30 seconds

    # VNC settings
    vnc_username: str | None = None  # VNC username (for macOS Apple Remote Desktop auth)
    vnc_password: str | None = None  # VNC password (None = no auth, matches -SecurityTypes None)
    vnc_port: int = 5901  # VNC display port (matches install.sh VNC_PORT)
    vnc_screenshot_max_width: int = 1280  # Max screenshot width sent to Claude
    vnc_screenshot_max_height: int = 800  # Max screenshot height sent to Claude
    vnc_pool_idle_timeout: int = 60  # Seconds before idle VNC connections are closed
    vnc_pool_sweep_interval: int = 15  # Seconds between pool sweep runs

    # NATS settings
    nats_url: str = "nats://localhost:4222"
    nats_ws_url: str = "ws://localhost:8443"  # For UI config endpoint

    # Supervisor settings
    supervisor_enabled: bool = True  # Whether to accept supervisor connections
    supervisor_default_target: str = "auto"  # Default task target: "worker", "supervisor", or "auto"
    supervisor_learn_from_questions: bool = True  # Auto-update scheduled task prompts based on learnings

    # Desktop workers — JSON string of pre-configured desktop worker entries
    # e.g. [{"id": "...", "novnc_url": "...", "metadata": {"os": "macos"}}]
    desktop_workers: str = "[]"

    # Self-healing settings
    self_healing_enabled: bool = True  # System-wide default for self-healing
    self_healing_max_retries: int = 2  # Default max retry attempts

    model_config = SettingsConfigDict(env_prefix="FIGARO_")
