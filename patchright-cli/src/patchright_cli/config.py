from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProxyConfig(BaseModel):
    server: str | None = None
    bypass: str | None = None


def _default_launch_options() -> dict:
    opts: dict = {"headless": False, "chromium_sandbox": True}
    # Prefer system chromium (has proprietary codec support, e.g. h264)
    # over Playwright's bundled chromium (compiled without proprietary codecs).
    system_chromium = shutil.which("chromium") or shutil.which("chromium-browser")
    if system_chromium:
        opts["executable_path"] = system_chromium
    return opts


class BrowserConfig(BaseModel):
    browser_name: Literal["chromium", "firefox", "webkit"] = "chromium"
    isolated: bool = False
    user_data_dir: str | None = None
    launch_options: dict = Field(default_factory=_default_launch_options)
    context_options: dict = Field(default_factory=lambda: {"no_viewport": True})
    cdp_endpoint: str | None = None
    cdp_headers: dict[str, str] = Field(default_factory=dict)
    cdp_timeout: int = 30000
    remote_endpoint: str | None = None
    init_page: list[str] = Field(default_factory=list)
    init_script: list[str] = Field(default_factory=list)
    webgl_renderer: str | None = None


class ConsoleConfig(BaseModel):
    level: Literal["error", "warning", "info", "debug"] = "info"


class NetworkConfig(BaseModel):
    allowed_origins: list[str] = Field(default_factory=list)
    blocked_origins: list[str] = Field(default_factory=list)


class TimeoutsConfig(BaseModel):
    action: int = 5000
    navigation: int = 60000


class VideoSize(BaseModel):
    width: int
    height: int


class CLIConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PLAYWRIGHT_MCP_",
        env_nested_delimiter="__",
    )

    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    save_video: VideoSize | None = None
    output_dir: str = ".patchright-cli"
    output_mode: Literal["file", "stdout"] = "stdout"
    console: ConsoleConfig = Field(default_factory=ConsoleConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    test_id_attribute: str = "data-testid"
    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)
    allow_unrestricted_file_access: bool = False
    codegen: Literal["typescript", "none"] = "typescript"

    @field_validator("save_video", mode="before")
    @classmethod
    def parse_save_video(
        cls, v: str | dict | VideoSize | None
    ) -> dict | VideoSize | None:
        if v is None:
            return None
        if isinstance(v, str):
            parts = v.lower().split("x")
            if len(parts) != 2:
                raise ValueError(
                    f"PLAYWRIGHT_MCP_SAVE_VIDEO must be in 'WxH' format, got '{v}'"
                )
            return {"width": int(parts[0]), "height": int(parts[1])}
        return v

    @field_validator("network", mode="before")
    @classmethod
    def parse_network(cls, v: str | dict | NetworkConfig) -> dict | NetworkConfig:
        if isinstance(v, (dict, NetworkConfig)):
            return v
        return v

    @classmethod
    def _parse_semicolon_list(cls, value: str) -> list[str]:
        return [item.strip() for item in value.split(";") if item.strip()]


def _parse_viewport_size(value: str) -> dict[str, int]:
    """Parse a 'WxH' string into a viewport size dict."""
    parts = value.lower().split("x")
    if len(parts) != 2:
        raise ValueError(
            f"PLAYWRIGHT_MCP_VIEWPORT_SIZE must be in 'WxH' format, got '{value}'"
        )
    return {"width": int(parts[0]), "height": int(parts[1])}


def apply_env_overrides(config: CLIConfig) -> CLIConfig:
    """Read specific PLAYWRIGHT_MCP_* env vars and apply them as overrides.

    These env vars don't map directly via pydantic-settings nested delimiter
    conventions, so they are handled manually here.
    """

    # PLAYWRIGHT_MCP_BROWSER -> browser.launch_options.channel
    browser_channel = os.environ.get("PLAYWRIGHT_MCP_BROWSER")
    if browser_channel is not None:
        config.browser.launch_options["channel"] = browser_channel

    # PLAYWRIGHT_MCP_HEADLESS -> browser.launch_options.headless
    headless = os.environ.get("PLAYWRIGHT_MCP_HEADLESS")
    if headless is not None:
        config.browser.launch_options["headless"] = headless.lower() in (
            "1",
            "true",
            "yes",
        )

    # PLAYWRIGHT_MCP_VIEWPORT_SIZE -> browser.context_options.viewport
    viewport_size = os.environ.get("PLAYWRIGHT_MCP_VIEWPORT_SIZE")
    if viewport_size is not None:
        config.browser.context_options["viewport"] = _parse_viewport_size(viewport_size)

    # PLAYWRIGHT_MCP_EXECUTABLE_PATH -> browser.launch_options.executable_path
    executable_path = os.environ.get("PLAYWRIGHT_MCP_EXECUTABLE_PATH")
    if executable_path is not None:
        config.browser.launch_options["executable_path"] = executable_path

    # PLAYWRIGHT_MCP_CDP_ENDPOINT -> browser.cdp_endpoint
    cdp_endpoint = os.environ.get("PLAYWRIGHT_MCP_CDP_ENDPOINT")
    if cdp_endpoint is not None:
        config.browser.cdp_endpoint = cdp_endpoint

    # PLAYWRIGHT_MCP_USER_AGENT -> browser.context_options.user_agent
    user_agent = os.environ.get("PLAYWRIGHT_MCP_USER_AGENT")
    if user_agent is not None:
        config.browser.context_options["user_agent"] = user_agent

    # PLAYWRIGHT_MCP_PROXY_SERVER -> browser.launch_options.proxy.server
    proxy_server = os.environ.get("PLAYWRIGHT_MCP_PROXY_SERVER")
    if proxy_server is not None:
        proxy = config.browser.launch_options.get("proxy", {})
        proxy["server"] = proxy_server
        config.browser.launch_options["proxy"] = proxy

    # PLAYWRIGHT_MCP_PROXY_BYPASS -> browser.launch_options.proxy.bypass
    proxy_bypass = os.environ.get("PLAYWRIGHT_MCP_PROXY_BYPASS")
    if proxy_bypass is not None:
        proxy = config.browser.launch_options.get("proxy", {})
        proxy["bypass"] = proxy_bypass
        config.browser.launch_options["proxy"] = proxy

    # PLAYWRIGHT_MCP_NO_SANDBOX -> browser.launch_options.chromium_sandbox = False
    no_sandbox = os.environ.get("PLAYWRIGHT_MCP_NO_SANDBOX")
    if no_sandbox is not None and no_sandbox.lower() in ("1", "true", "yes"):
        config.browser.launch_options["chromium_sandbox"] = False

    # PLAYWRIGHT_MCP_IGNORE_HTTPS_ERRORS -> browser.context_options.ignore_https_errors
    ignore_https = os.environ.get("PLAYWRIGHT_MCP_IGNORE_HTTPS_ERRORS")
    if ignore_https is not None:
        config.browser.context_options["ignore_https_errors"] = (
            ignore_https.lower()
            in (
                "1",
                "true",
                "yes",
            )
        )

    # PLAYWRIGHT_MCP_INIT_SCRIPT -> browser.init_script (semicolon-separated)
    init_script = os.environ.get("PLAYWRIGHT_MCP_INIT_SCRIPT")
    if init_script is not None:
        config.browser.init_script = [
            s.strip() for s in init_script.split(";") if s.strip()
        ]

    # PLAYWRIGHT_MCP_WEBGL_RENDERER -> browser.webgl_renderer
    webgl_renderer = os.environ.get("PLAYWRIGHT_MCP_WEBGL_RENDERER")
    if webgl_renderer is not None:
        config.browser.webgl_renderer = webgl_renderer

    # PLAYWRIGHT_MCP_INIT_PAGE -> browser.init_page (semicolon-separated)
    init_page = os.environ.get("PLAYWRIGHT_MCP_INIT_PAGE")
    if init_page is not None:
        config.browser.init_page = [
            p.strip() for p in init_page.split(";") if p.strip()
        ]

    # PLAYWRIGHT_MCP_TIMEOUT_ACTION -> timeouts.action
    timeout_action = os.environ.get("PLAYWRIGHT_MCP_TIMEOUT_ACTION")
    if timeout_action is not None:
        config.timeouts.action = int(timeout_action)

    # PLAYWRIGHT_MCP_TIMEOUT_NAVIGATION -> timeouts.navigation
    timeout_navigation = os.environ.get("PLAYWRIGHT_MCP_TIMEOUT_NAVIGATION")
    if timeout_navigation is not None:
        config.timeouts.navigation = int(timeout_navigation)

    # PLAYWRIGHT_MCP_ALLOWED_ORIGINS -> network.allowed_origins (semicolon-separated)
    allowed_origins = os.environ.get("PLAYWRIGHT_MCP_ALLOWED_ORIGINS")
    if allowed_origins is not None:
        config.network.allowed_origins = [
            o.strip() for o in allowed_origins.split(";") if o.strip()
        ]

    # PLAYWRIGHT_MCP_BLOCKED_ORIGINS -> network.blocked_origins (semicolon-separated)
    blocked_origins = os.environ.get("PLAYWRIGHT_MCP_BLOCKED_ORIGINS")
    if blocked_origins is not None:
        config.network.blocked_origins = [
            o.strip() for o in blocked_origins.split(";") if o.strip()
        ]

    # PLAYWRIGHT_MCP_GRANT_PERMISSIONS -> browser.context_options.permissions (comma-separated)
    grant_permissions = os.environ.get("PLAYWRIGHT_MCP_GRANT_PERMISSIONS")
    if grant_permissions is not None:
        config.browser.context_options["permissions"] = [
            p.strip() for p in grant_permissions.split(",") if p.strip()
        ]

    # PLAYWRIGHT_MCP_SAVE_VIDEO -> save_video (WxH format)
    save_video = os.environ.get("PLAYWRIGHT_MCP_SAVE_VIDEO")
    if save_video is not None:
        parsed = _parse_viewport_size(save_video)
        config.save_video = VideoSize(width=parsed["width"], height=parsed["height"])

    return config


def get_version() -> str:
    """Return the package version string."""
    try:
        from importlib.metadata import version

        return version("patchright-cli")
    except Exception:
        return "0.1.0"


def load_config(config_path: str | None = None) -> CLIConfig:
    """Load CLI configuration from a JSON file and/or environment variables.

    Priority (highest to lowest):
        1. PLAYWRIGHT_MCP_* environment variables (via pydantic-settings + apply_env_overrides)
        2. Explicitly provided config_path JSON file
        3. Default config file at .playwright/cli.config.json in cwd
        4. Built-in defaults

    Args:
        config_path: Optional path to a JSON configuration file. If not
            provided, the function looks for ``.playwright/cli.config.json``
            in the current working directory.

    Returns:
        A fully resolved ``CLIConfig`` instance.
    """
    file_values: dict = {}

    if config_path is not None:
        config_file = Path(config_path)
        if config_file.is_file():
            file_values = json.loads(config_file.read_text(encoding="utf-8"))
    else:
        default_config = Path.cwd() / ".playwright" / "cli.config.json"
        if default_config.is_file():
            file_values = json.loads(default_config.read_text(encoding="utf-8"))

    # pydantic-settings will layer env vars on top of these values automatically
    config = CLIConfig(**file_values)

    # Apply the env-var overrides that don't fit the nested delimiter pattern
    config = apply_env_overrides(config)

    return config
