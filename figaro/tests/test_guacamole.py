"""Tests for the Guacamole token endpoint."""

from urllib.parse import urlparse

import pytest
from fastapi import HTTPException

from figaro.routes.guacamole import (
    _build_connection_settings,
    _detect_protocol,
    _resolve_host_port,
)


class TestDetectProtocol:
    def test_vnc_scheme(self):
        assert _detect_protocol("vnc") == "vnc"

    def test_ssh_scheme(self):
        assert _detect_protocol("ssh") == "ssh"

    def test_rdp_scheme(self):
        assert _detect_protocol("rdp") == "rdp"

    def test_ws_maps_to_vnc(self):
        assert _detect_protocol("ws") == "vnc"

    def test_wss_maps_to_vnc(self):
        assert _detect_protocol("wss") == "vnc"

    def test_unsupported_scheme_raises(self):
        with pytest.raises(HTTPException) as exc_info:
            _detect_protocol("ftp")
        assert exc_info.value.status_code == 400


class TestResolveHostPort:
    def test_ws_uses_vnc_port(self):
        parsed = urlparse("ws://worker-1:6080")
        hostname, port = _resolve_host_port(parsed, "vnc", "ws", 5901)
        assert hostname == "worker-1"
        assert port == 5901

    def test_explicit_port(self):
        parsed = urlparse("vnc://worker-1:5902")
        hostname, port = _resolve_host_port(parsed, "vnc", "vnc", 5901)
        assert hostname == "worker-1"
        assert port == 5902

    def test_default_ssh_port(self):
        parsed = urlparse("ssh://worker-1")
        hostname, port = _resolve_host_port(parsed, "ssh", "ssh", 5901)
        assert hostname == "worker-1"
        assert port == 22

    def test_default_vnc_port(self):
        parsed = urlparse("vnc://worker-1")
        hostname, port = _resolve_host_port(parsed, "vnc", "vnc", 5901)
        assert hostname == "worker-1"
        assert port == 5900


class TestBuildConnectionSettings:
    def test_always_includes_display_dimensions(self):
        """Regression: guacd crashes with GUAC_ASSERT in
        guac_terminal_fit_to_range() when width/height/dpi are missing."""
        settings = _build_connection_settings("host", 22, None, None)
        assert settings["width"] == 1024
        assert settings["height"] == 768
        assert settings["dpi"] == 96

    def test_ssh_settings_include_dimensions(self):
        """SSH connections must have display dimensions to avoid guacd crash."""
        settings = _build_connection_settings("worker-1", 22, "pass", "user")
        assert "width" in settings
        assert "height" in settings
        assert "dpi" in settings
        assert settings["width"] > 0
        assert settings["height"] > 0

    def test_includes_credentials(self):
        settings = _build_connection_settings("host", 22, "secret", "admin")
        assert settings["password"] == "secret"
        assert settings["username"] == "admin"

    def test_omits_none_credentials(self):
        settings = _build_connection_settings("host", 5900, None, None)
        assert "password" not in settings
        assert "username" not in settings

    def test_hostname_and_port(self):
        settings = _build_connection_settings("worker-1", 5901, None, None)
        assert settings["hostname"] == "worker-1"
        assert settings["port"] == 5901
