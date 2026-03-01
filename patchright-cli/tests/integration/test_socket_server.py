"""Integration tests for the Unix socket server.

These tests run ``run_server()`` as an ``asyncio.create_task`` in-process and
communicate with it over ``asyncio.open_unix_connection``.  Each test gets a
short temporary home directory so the Unix socket path stays under 108 chars.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from patchright_cli.config import BrowserConfig, CLIConfig
from patchright_cli.server import run_server
from patchright_cli.session import get_pid_path, get_socket_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def wait_for_socket(socket_path: Path, timeout: float = 15) -> bool:
    """Poll until the Unix socket file appears on disk."""
    for _ in range(int(timeout * 10)):
        if socket_path.exists():
            return True
        await asyncio.sleep(0.1)
    return False


async def send_json(socket_path: Path, cmd: str, args: dict | None = None) -> dict:
    """Open a new connection, send a single JSON command, return the response."""
    reader, writer = await asyncio.open_unix_connection(str(socket_path))
    payload = json.dumps({"cmd": cmd, "args": args or {}}).encode() + b"\n"
    writer.write(payload)
    await writer.drain()
    data = await reader.readline()
    writer.close()
    await writer.wait_closed()
    return json.loads(data)


def make_config_dict() -> dict:
    """Return a serialised CLIConfig suitable for headless isolated tests."""
    return CLIConfig(
        browser=BrowserConfig(
            isolated=True,
            launch_options={"headless": True, "chromium_sandbox": False},
            context_options={},
        ),
    ).model_dump()


@pytest.fixture
def short_home(monkeypatch: pytest.MonkeyPatch):
    """Provide a short temp dir as HOME so Unix socket paths stay under 108 chars."""
    tmpdir = tempfile.mkdtemp(prefix="prt-")
    home = Path(tmpdir)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(Path, "cwd", lambda: home)
    yield home


async def _cleanup_task(task: asyncio.Task, socket_path: Path) -> None:
    """Best-effort cleanup of a server task."""
    if not task.done():
        try:
            await send_json(socket_path, "close")
        except Exception:
            pass
        try:
            await asyncio.wait_for(task, timeout=10)
        except asyncio.CancelledError, Exception:
            # CancelledError is expected — serve_forever raises it on server.close()
            pass
    else:
        # If already done, retrieve exception to avoid "exception never retrieved"
        try:
            task.result()
        except asyncio.CancelledError, Exception:
            pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_server_creates_socket_and_pid_file(short_home: Path) -> None:
    """Starting the server should create the socket and PID files."""
    session_name = "st"
    config_dict = make_config_dict()
    socket_path = get_socket_path(session_name)
    pid_path = get_pid_path(session_name)

    task = asyncio.create_task(run_server(session_name, config_dict))
    try:
        assert await wait_for_socket(socket_path), "Socket file never appeared"
        assert socket_path.exists()
        assert pid_path.exists()
    finally:
        await _cleanup_task(task, socket_path)


@pytest.mark.integration
async def test_server_accepts_and_responds(short_home: Path) -> None:
    """Sending an 'open' command should succeed and return ok=True."""
    session_name = "st"
    config_dict = make_config_dict()
    socket_path = get_socket_path(session_name)

    task = asyncio.create_task(run_server(session_name, config_dict))
    try:
        assert await wait_for_socket(socket_path)
        resp = await send_json(socket_path, "open", {"headless": True})
        assert resp["ok"] is True
    finally:
        await _cleanup_task(task, socket_path)


@pytest.mark.integration
async def test_server_unknown_command(short_home: Path) -> None:
    """An unknown command should return ok=False with 'Unknown command' in the error."""
    session_name = "st"
    config_dict = make_config_dict()
    socket_path = get_socket_path(session_name)

    task = asyncio.create_task(run_server(session_name, config_dict))
    try:
        assert await wait_for_socket(socket_path)
        await send_json(socket_path, "open", {"headless": True})
        resp = await send_json(socket_path, "nonexistent", {})
        assert resp["ok"] is False
        assert "Unknown command" in resp["error"]
    finally:
        await _cleanup_task(task, socket_path)


@pytest.mark.integration
async def test_server_command_error_handled(short_home: Path) -> None:
    """A command that fails (goto without browser) should return ok=False, not crash."""
    session_name = "st"
    config_dict = make_config_dict()
    socket_path = get_socket_path(session_name)

    task = asyncio.create_task(run_server(session_name, config_dict))
    try:
        assert await wait_for_socket(socket_path)
        resp = await send_json(socket_path, "goto", {"url": "http://example.com"})
        assert resp["ok"] is False
    finally:
        await _cleanup_task(task, socket_path)


@pytest.mark.integration
async def test_server_close_stops_server(short_home: Path) -> None:
    """Sending 'close' should stop the server task."""
    session_name = "st"
    config_dict = make_config_dict()
    socket_path = get_socket_path(session_name)

    task = asyncio.create_task(run_server(session_name, config_dict))
    try:
        assert await wait_for_socket(socket_path)
        await send_json(socket_path, "open", {"headless": True})
        await send_json(socket_path, "close")
        try:
            await asyncio.wait_for(task, timeout=10)
        except asyncio.CancelledError:
            pass  # serve_forever raises CancelledError on normal shutdown
        assert task.done()
    except Exception:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError, Exception:
                pass
        raise


@pytest.mark.integration
async def test_server_cleanup_on_exit(short_home: Path) -> None:
    """After a clean shutdown the socket and PID files should be removed."""
    session_name = "st"
    config_dict = make_config_dict()
    socket_path = get_socket_path(session_name)

    task = asyncio.create_task(run_server(session_name, config_dict))
    try:
        assert await wait_for_socket(socket_path)
        await send_json(socket_path, "open", {"headless": True})
        await send_json(socket_path, "close")
        try:
            await asyncio.wait_for(task, timeout=10)
        except asyncio.CancelledError:
            pass  # serve_forever raises CancelledError on normal shutdown
        # asyncio removes the socket file when the server closes
        assert not socket_path.exists(), "Socket file should be removed after close"
    except Exception:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError, Exception:
                pass
        raise


@pytest.mark.integration
async def test_server_multiple_sequential_connections(short_home: Path) -> None:
    """Multiple sequential connections should each get a valid response."""
    session_name = "st"
    config_dict = make_config_dict()
    socket_path = get_socket_path(session_name)

    task = asyncio.create_task(run_server(session_name, config_dict))
    try:
        assert await wait_for_socket(socket_path)

        resp_open = await send_json(socket_path, "open", {"headless": True})
        assert resp_open["ok"] is True

        resp_snapshot = await send_json(socket_path, "snapshot")
        assert resp_snapshot["ok"] is True

        resp_close = await send_json(socket_path, "close")
        assert resp_close["ok"] is True

        try:
            await asyncio.wait_for(task, timeout=10)
        except asyncio.CancelledError:
            pass  # serve_forever raises CancelledError on normal shutdown
    except Exception:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError, Exception:
                pass
        raise
