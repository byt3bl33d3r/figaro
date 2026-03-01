"""Comprehensive tests for patchright_cli.config module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patchright_cli.config import (
    BrowserConfig,
    CLIConfig,
    ConsoleConfig,
    NetworkConfig,
    ProxyConfig,
    TimeoutsConfig,
    VideoSize,
    _parse_viewport_size,
    apply_env_overrides,
    load_config,
)


# ---------------------------------------------------------------------------
# 1. Pydantic model defaults and custom values
# ---------------------------------------------------------------------------


class TestProxyConfig:
    def test_defaults(self):
        proxy = ProxyConfig()
        assert proxy.server is None
        assert proxy.bypass is None

    def test_custom_values(self):
        proxy = ProxyConfig(server="http://proxy:8080", bypass="localhost,127.0.0.1")
        assert proxy.server == "http://proxy:8080"
        assert proxy.bypass == "localhost,127.0.0.1"


class TestBrowserConfig:
    def test_defaults(self):
        browser = BrowserConfig()
        assert browser.browser_name == "chromium"
        assert browser.isolated is False
        assert browser.user_data_dir is None
        assert browser.launch_options["headless"] is False
        assert browser.launch_options["chromium_sandbox"] is True
        assert browser.context_options == {"no_viewport": True}
        assert browser.cdp_endpoint is None
        assert browser.cdp_headers == {}
        assert browser.cdp_timeout == 30000
        assert browser.remote_endpoint is None
        assert browser.init_page == []
        assert browser.init_script == []

    def test_custom_values(self):
        browser = BrowserConfig(
            browser_name="firefox",
            isolated=True,
            user_data_dir="/tmp/profile",
            launch_options={"headless": True},
            context_options={"viewport": {"width": 800, "height": 600}},
            cdp_endpoint="http://localhost:9222",
            cdp_headers={"Authorization": "Bearer token"},
            cdp_timeout=60000,
            remote_endpoint="ws://remote:1234",
            init_page=["https://example.com"],
            init_script=["console.log('hello')"],
        )
        assert browser.browser_name == "firefox"
        assert browser.isolated is True
        assert browser.user_data_dir == "/tmp/profile"
        assert browser.launch_options == {"headless": True}
        assert browser.context_options == {"viewport": {"width": 800, "height": 600}}
        assert browser.cdp_endpoint == "http://localhost:9222"
        assert browser.cdp_headers == {"Authorization": "Bearer token"}
        assert browser.cdp_timeout == 60000
        assert browser.remote_endpoint == "ws://remote:1234"
        assert browser.init_page == ["https://example.com"]
        assert browser.init_script == ["console.log('hello')"]


class TestConsoleConfig:
    def test_defaults(self):
        console = ConsoleConfig()
        assert console.level == "info"

    def test_custom_level(self):
        for level in ("error", "warning", "info", "debug"):
            console = ConsoleConfig(level=level)
            assert console.level == level


class TestNetworkConfig:
    def test_defaults(self):
        network = NetworkConfig()
        assert network.allowed_origins == []
        assert network.blocked_origins == []

    def test_custom_values(self):
        network = NetworkConfig(
            allowed_origins=["https://example.com"],
            blocked_origins=["https://ads.example.com"],
        )
        assert network.allowed_origins == ["https://example.com"]
        assert network.blocked_origins == ["https://ads.example.com"]


class TestTimeoutsConfig:
    def test_defaults(self):
        timeouts = TimeoutsConfig()
        assert timeouts.action == 5000
        assert timeouts.navigation == 60000

    def test_custom_values(self):
        timeouts = TimeoutsConfig(action=10000, navigation=120000)
        assert timeouts.action == 10000
        assert timeouts.navigation == 120000


class TestVideoSize:
    def test_creation(self):
        vs = VideoSize(width=1280, height=720)
        assert vs.width == 1280
        assert vs.height == 720


class TestCLIConfigDefaults:
    def test_defaults(self):
        config = CLIConfig()
        assert isinstance(config.browser, BrowserConfig)
        assert config.save_video is None
        assert config.output_dir == ".patchright-cli"
        assert config.output_mode == "stdout"
        assert isinstance(config.console, ConsoleConfig)
        assert isinstance(config.network, NetworkConfig)
        assert config.test_id_attribute == "data-testid"
        assert isinstance(config.timeouts, TimeoutsConfig)
        assert config.allow_unrestricted_file_access is False
        assert config.codegen == "typescript"

    def test_custom_values(self):
        config = CLIConfig(
            browser=BrowserConfig(browser_name="webkit"),
            save_video=VideoSize(width=1920, height=1080),
            output_dir="/custom/output",
            output_mode="file",
            console=ConsoleConfig(level="debug"),
            network=NetworkConfig(allowed_origins=["https://example.com"]),
            test_id_attribute="data-cy",
            timeouts=TimeoutsConfig(action=10000, navigation=30000),
            allow_unrestricted_file_access=True,
            codegen="none",
        )
        assert config.browser.browser_name == "webkit"
        assert config.save_video.width == 1920
        assert config.save_video.height == 1080
        assert config.output_dir == "/custom/output"
        assert config.output_mode == "file"
        assert config.console.level == "debug"
        assert config.network.allowed_origins == ["https://example.com"]
        assert config.test_id_attribute == "data-cy"
        assert config.timeouts.action == 10000
        assert config.timeouts.navigation == 30000
        assert config.allow_unrestricted_file_access is True
        assert config.codegen == "none"


# ---------------------------------------------------------------------------
# 2. Validators
# ---------------------------------------------------------------------------


class TestParseSaveVideo:
    def test_none_passthrough(self):
        config = CLIConfig(save_video=None)
        assert config.save_video is None

    def test_wxh_string(self):
        config = CLIConfig(save_video="1280x720")
        assert isinstance(config.save_video, VideoSize)
        assert config.save_video.width == 1280
        assert config.save_video.height == 720

    def test_wxh_string_uppercase(self):
        config = CLIConfig(save_video="1920X1080")
        assert config.save_video.width == 1920
        assert config.save_video.height == 1080

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="WxH"):
            CLIConfig(save_video="invalid")

    def test_invalid_format_too_many_parts(self):
        with pytest.raises(ValueError, match="WxH"):
            CLIConfig(save_video="100x200x300")

    def test_dict_passthrough(self):
        config = CLIConfig(save_video={"width": 640, "height": 480})
        assert isinstance(config.save_video, VideoSize)
        assert config.save_video.width == 640
        assert config.save_video.height == 480

    def test_video_size_passthrough(self):
        vs = VideoSize(width=800, height=600)
        config = CLIConfig(save_video=vs)
        assert config.save_video is vs
        assert config.save_video.width == 800
        assert config.save_video.height == 600


class TestParseSemicolonList:
    def test_basic(self):
        result = CLIConfig._parse_semicolon_list("a;b;c")
        assert result == ["a", "b", "c"]

    def test_with_whitespace(self):
        result = CLIConfig._parse_semicolon_list("  a ; b ; c  ")
        assert result == ["a", "b", "c"]

    def test_empty_segments_filtered(self):
        result = CLIConfig._parse_semicolon_list("a;;b;;;c")
        assert result == ["a", "b", "c"]

    def test_empty_string(self):
        result = CLIConfig._parse_semicolon_list("")
        assert result == []

    def test_single_item(self):
        result = CLIConfig._parse_semicolon_list("only_one")
        assert result == ["only_one"]


# ---------------------------------------------------------------------------
# 3. _parse_viewport_size
# ---------------------------------------------------------------------------


class TestParseViewportSize:
    def test_valid(self):
        result = _parse_viewport_size("1280x720")
        assert result == {"width": 1280, "height": 720}

    def test_valid_uppercase(self):
        result = _parse_viewport_size("1920X1080")
        assert result == {"width": 1920, "height": 1080}

    def test_invalid_format_no_x(self):
        with pytest.raises(ValueError, match="WxH"):
            _parse_viewport_size("1280-720")

    def test_invalid_format_too_many_parts(self):
        with pytest.raises(ValueError, match="WxH"):
            _parse_viewport_size("100x200x300")

    def test_invalid_non_numeric(self):
        with pytest.raises(ValueError):
            _parse_viewport_size("widexhigh")


# ---------------------------------------------------------------------------
# 4. apply_env_overrides
#
# NOTE: PLAYWRIGHT_MCP_BROWSER and PLAYWRIGHT_MCP_SAVE_VIDEO collide with
# pydantic-settings field names (browser, save_video) on CLIConfig. Because
# CLIConfig uses env_prefix="PLAYWRIGHT_MCP_", pydantic-settings would try
# to parse these env vars as the respective field types during construction.
# Therefore, for apply_env_overrides tests, we construct the CLIConfig first
# and set the env var afterward so that only apply_env_overrides sees it.
# ---------------------------------------------------------------------------


class TestApplyEnvOverrides:
    def test_browser_channel(self, monkeypatch):
        config = CLIConfig()
        monkeypatch.setenv("PLAYWRIGHT_MCP_BROWSER", "chrome")
        config = apply_env_overrides(config)
        assert config.browser.launch_options["channel"] == "chrome"

    def test_headless_true(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_MCP_HEADLESS", "true")
        config = apply_env_overrides(CLIConfig())
        assert config.browser.launch_options["headless"] is True

    def test_headless_false(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_MCP_HEADLESS", "false")
        config = apply_env_overrides(CLIConfig())
        assert config.browser.launch_options["headless"] is False

    def test_headless_yes(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_MCP_HEADLESS", "yes")
        config = apply_env_overrides(CLIConfig())
        assert config.browser.launch_options["headless"] is True

    def test_headless_1(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_MCP_HEADLESS", "1")
        config = apply_env_overrides(CLIConfig())
        assert config.browser.launch_options["headless"] is True

    def test_viewport_size(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_MCP_VIEWPORT_SIZE", "1024x768")
        config = apply_env_overrides(CLIConfig())
        assert config.browser.context_options["viewport"] == {
            "width": 1024,
            "height": 768,
        }

    def test_executable_path(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_MCP_EXECUTABLE_PATH", "/usr/bin/chromium")
        config = apply_env_overrides(CLIConfig())
        assert config.browser.launch_options["executable_path"] == "/usr/bin/chromium"

    def test_cdp_endpoint(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_MCP_CDP_ENDPOINT", "http://localhost:9222")
        config = apply_env_overrides(CLIConfig())
        assert config.browser.cdp_endpoint == "http://localhost:9222"

    def test_user_agent(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_MCP_USER_AGENT", "CustomAgent/1.0")
        config = apply_env_overrides(CLIConfig())
        assert config.browser.context_options["user_agent"] == "CustomAgent/1.0"

    def test_proxy_server(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_MCP_PROXY_SERVER", "http://proxy:8080")
        config = apply_env_overrides(CLIConfig())
        assert config.browser.launch_options["proxy"]["server"] == "http://proxy:8080"

    def test_proxy_bypass(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_MCP_PROXY_BYPASS", "localhost,127.0.0.1")
        config = apply_env_overrides(CLIConfig())
        assert config.browser.launch_options["proxy"]["bypass"] == "localhost,127.0.0.1"

    def test_proxy_server_and_bypass_together(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_MCP_PROXY_SERVER", "http://proxy:3128")
        monkeypatch.setenv("PLAYWRIGHT_MCP_PROXY_BYPASS", "*.local")
        config = apply_env_overrides(CLIConfig())
        proxy = config.browser.launch_options["proxy"]
        assert proxy["server"] == "http://proxy:3128"
        assert proxy["bypass"] == "*.local"

    def test_no_sandbox_true(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_MCP_NO_SANDBOX", "true")
        config = apply_env_overrides(CLIConfig())
        assert config.browser.launch_options["chromium_sandbox"] is False

    def test_no_sandbox_false_leaves_default(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_MCP_NO_SANDBOX", "false")
        config = apply_env_overrides(CLIConfig())
        # When NO_SANDBOX is not truthy, chromium_sandbox stays at its default
        assert config.browser.launch_options["chromium_sandbox"] is True

    def test_ignore_https_errors_true(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_MCP_IGNORE_HTTPS_ERRORS", "1")
        config = apply_env_overrides(CLIConfig())
        assert config.browser.context_options["ignore_https_errors"] is True

    def test_ignore_https_errors_false(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_MCP_IGNORE_HTTPS_ERRORS", "no")
        config = apply_env_overrides(CLIConfig())
        assert config.browser.context_options["ignore_https_errors"] is False

    def test_init_script(self, monkeypatch):
        monkeypatch.setenv(
            "PLAYWRIGHT_MCP_INIT_SCRIPT", "console.log('a');console.log('b')"
        )
        config = apply_env_overrides(CLIConfig())
        assert config.browser.init_script == ["console.log('a')", "console.log('b')"]

    def test_init_page(self, monkeypatch):
        monkeypatch.setenv(
            "PLAYWRIGHT_MCP_INIT_PAGE",
            "https://example.com;https://test.com",
        )
        config = apply_env_overrides(CLIConfig())
        assert config.browser.init_page == [
            "https://example.com",
            "https://test.com",
        ]

    def test_timeout_action(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_MCP_TIMEOUT_ACTION", "10000")
        config = apply_env_overrides(CLIConfig())
        assert config.timeouts.action == 10000

    def test_timeout_navigation(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_MCP_TIMEOUT_NAVIGATION", "120000")
        config = apply_env_overrides(CLIConfig())
        assert config.timeouts.navigation == 120000

    def test_allowed_origins(self, monkeypatch):
        monkeypatch.setenv(
            "PLAYWRIGHT_MCP_ALLOWED_ORIGINS",
            "https://a.com;https://b.com",
        )
        config = apply_env_overrides(CLIConfig())
        assert config.network.allowed_origins == [
            "https://a.com",
            "https://b.com",
        ]

    def test_blocked_origins(self, monkeypatch):
        monkeypatch.setenv(
            "PLAYWRIGHT_MCP_BLOCKED_ORIGINS",
            "https://ads.com ; https://tracker.com",
        )
        config = apply_env_overrides(CLIConfig())
        assert config.network.blocked_origins == [
            "https://ads.com",
            "https://tracker.com",
        ]

    def test_grant_permissions(self, monkeypatch):
        monkeypatch.setenv(
            "PLAYWRIGHT_MCP_GRANT_PERMISSIONS",
            "geolocation, notifications, clipboard-read",
        )
        config = apply_env_overrides(CLIConfig())
        assert config.browser.context_options["permissions"] == [
            "geolocation",
            "notifications",
            "clipboard-read",
        ]

    def test_save_video(self, monkeypatch):
        config = CLIConfig()
        monkeypatch.setenv("PLAYWRIGHT_MCP_SAVE_VIDEO", "1280x720")
        config = apply_env_overrides(config)
        assert isinstance(config.save_video, VideoSize)
        assert config.save_video.width == 1280
        assert config.save_video.height == 720

    def test_no_env_vars_set_leaves_defaults(self):
        config = apply_env_overrides(CLIConfig())
        assert config.browser.launch_options["headless"] is False
        assert config.browser.launch_options["chromium_sandbox"] is True
        assert config.browser.context_options == {"no_viewport": True}
        assert config.browser.cdp_endpoint is None
        assert config.browser.init_script == []
        assert config.browser.init_page == []
        assert config.timeouts.action == 5000
        assert config.timeouts.navigation == 60000
        assert config.network.allowed_origins == []
        assert config.network.blocked_origins == []
        assert config.save_video is None


# ---------------------------------------------------------------------------
# 5. load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_explicit_config_path(self, config_file):
        config = load_config(str(config_file))
        assert config.browser.browser_name == "firefox"
        assert config.browser.isolated is True
        assert config.output_dir == ".custom-output"

    def test_default_config_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        config_dir = tmp_path / ".playwright"
        config_dir.mkdir()
        config_data = {
            "browser": {"browser_name": "webkit"},
            "test_id_attribute": "data-qa",
        }
        (config_dir / "cli.config.json").write_text(
            json.dumps(config_data), encoding="utf-8"
        )
        config = load_config()
        assert config.browser.browser_name == "webkit"
        assert config.test_id_attribute == "data-qa"

    def test_missing_file_uses_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        config = load_config()
        assert config.browser.browser_name == "chromium"
        assert config.output_dir == ".patchright-cli"
        assert config.save_video is None

    def test_explicit_path_missing_file_uses_defaults(self, tmp_path):
        nonexistent = tmp_path / "does-not-exist.json"
        config = load_config(str(nonexistent))
        assert config.browser.browser_name == "chromium"
        assert config.output_dir == ".patchright-cli"

    def test_env_overrides_applied_on_top(self, config_file, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_MCP_HEADLESS", "true")
        monkeypatch.setenv("PLAYWRIGHT_MCP_CDP_ENDPOINT", "http://remote:9222")
        config = load_config(str(config_file))
        # From file
        assert config.browser.browser_name == "firefox"
        assert config.browser.isolated is True
        assert config.output_dir == ".custom-output"
        # From env overrides
        assert config.browser.launch_options["headless"] is True
        assert config.browser.cdp_endpoint == "http://remote:9222"

    def test_env_overrides_on_default_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
        monkeypatch.setenv("PLAYWRIGHT_MCP_TIMEOUT_ACTION", "20000")
        monkeypatch.setenv("PLAYWRIGHT_MCP_CDP_ENDPOINT", "http://remote:9222")
        config = load_config()
        assert config.timeouts.action == 20000
        assert config.browser.cdp_endpoint == "http://remote:9222"
