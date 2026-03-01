"""Integration tests for daemon lifecycle via the client module.

These tests exercise the real subprocess daemon path — start_daemon(),
send_command(), open_session() — communicating over Unix domain sockets
with an actual background server process.

All tests are synchronous because the client functions are synchronous.
Each test uses a short temp directory under /tmp to keep the Unix socket
path within the 108-character limit.
"""

from __future__ import annotations

import os
import signal
import tempfile
import time
from pathlib import Path

import pytest

from patchright_cli.client import open_session, send_command, start_daemon
from patchright_cli.config import BrowserConfig, CLIConfig
from patchright_cli.session import (
    cleanup_session,
    get_socket_path,
    read_pid,
)


def _cleanup_daemon(session_name: str) -> None:
    """Best-effort cleanup: close gracefully, then SIGTERM, then remove files."""
    try:
        send_command(session_name, "close", timeout=10)
    except Exception:
        pass
    time.sleep(0.5)
    pid = read_pid(session_name)
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError, PermissionError:
            pass
    cleanup_session(session_name)


def _make_config_dict() -> dict:
    """Return a serialised CLIConfig suitable for headless container use."""
    return CLIConfig(
        browser=BrowserConfig(
            isolated=True,
            launch_options={"headless": True, "chromium_sandbox": False},
            context_options={},
        ),
    ).model_dump()


@pytest.fixture
def short_home(monkeypatch: pytest.MonkeyPatch):
    """Provide a short temp dir as HOME so Unix socket paths stay under 108 chars.

    pytest's tmp_path is too long (e.g. /tmp/pytest-of-vscode/pytest-N/test_name0/)
    and the socket path exceeds the 108-char Unix limit.
    """
    # Preserve the real browser cache path before changing HOME
    real_home = Path.home()
    browsers_path = str(real_home / ".cache" / "ms-playwright")

    tmpdir = tempfile.mkdtemp(prefix="prt-")
    home = Path(tmpdir)
    monkeypatch.setenv("HOME", tmpdir)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", browsers_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(Path, "cwd", lambda: home)
    yield home
    # Cleanup is best-effort; daemon cleanup in tests handles the important parts


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_start_daemon_creates_socket(short_home: Path) -> None:
    """start_daemon should spawn a background process and create the Unix socket."""
    name = "dt"
    config_dict = _make_config_dict()
    try:
        result = start_daemon(name, config_dict)
        assert result is True
        assert get_socket_path(name).exists()
    finally:
        _cleanup_daemon(name)


@pytest.mark.integration
def test_send_command_open_and_snapshot(short_home: Path) -> None:
    """After opening the browser, a snapshot command should return non-empty output."""
    name = "dt"
    config_dict = _make_config_dict()
    try:
        assert start_daemon(name, config_dict) is True

        open_result = send_command(name, "open", {"headless": True})
        assert open_result["ok"] is True

        snap_result = send_command(name, "snapshot")
        assert snap_result["ok"] is True
        assert snap_result.get("output", "") != ""
    finally:
        _cleanup_daemon(name)


@pytest.mark.integration
def test_send_command_goto_data_url(short_home: Path) -> None:
    """Navigating to a data: URL should succeed and reflect the page content."""
    name = "dt"
    config_dict = _make_config_dict()
    try:
        assert start_daemon(name, config_dict) is True

        open_result = send_command(name, "open", {"headless": True})
        assert open_result["ok"] is True

        goto_result = send_command(
            name, "goto", {"url": "data:text/html,<h1>DataTest</h1>"}
        )
        assert goto_result["ok"] is True
        assert "DataTest" in goto_result.get("output", "")
    finally:
        _cleanup_daemon(name)


@pytest.mark.integration
def test_close_terminates_daemon(short_home: Path) -> None:
    """Sending 'close' should succeed and the socket should no longer accept connections."""
    name = "dt"
    config_dict = _make_config_dict()
    try:
        assert start_daemon(name, config_dict) is True

        open_result = send_command(name, "open", {"headless": True})
        assert open_result["ok"] is True

        close_result = send_command(name, "close")
        assert close_result["ok"] is True

        # After close, the socket should stop accepting new connections.
        # Wait for server shutdown then verify.
        time.sleep(2)
        retry_result = send_command(name, "snapshot", timeout=3)
        assert retry_result["ok"] is False
    finally:
        _cleanup_daemon(name)


@pytest.mark.integration
def test_open_session_helper(short_home: Path) -> None:
    """open_session() should start the daemon and navigate to the given URL."""
    name = "dt"
    config_dict = _make_config_dict()
    try:
        result = open_session(name, config_dict, url="data:text/html,<h1>Helper</h1>")
        assert result["ok"] is True
        assert "Helper" in result.get("output", "")
    finally:
        _cleanup_daemon(name)


@pytest.mark.integration
def test_start_daemon_already_running(short_home: Path) -> None:
    """Calling start_daemon twice for the same session should be idempotent."""
    name = "dt"
    config_dict = _make_config_dict()
    try:
        assert start_daemon(name, config_dict) is True
        assert start_daemon(name, config_dict) is True
    finally:
        _cleanup_daemon(name)
