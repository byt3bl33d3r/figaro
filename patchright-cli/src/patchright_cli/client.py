"""Synchronous client for patchright-cli.

Connects to daemon servers via Unix domain sockets to send commands
and receive responses. Provides high-level helpers for session
lifecycle management.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time

from patchright_cli.session import (
    cleanup_session,
    get_session_dir,
    get_socket_path,
    is_session_alive,
    list_sessions,
)


def _receive_all(sock: socket.socket, buffer_size: int = 65536) -> bytes:
    """Read all data from socket until the connection closes or a newline is found.

    The daemon protocol uses newline-delimited JSON, so we stop reading
    as soon as a complete line has arrived.
    """
    data = b""
    while True:
        chunk = sock.recv(buffer_size)
        if not chunk:
            break
        data += chunk
        if b"\n" in data:
            break
    return data.strip()


def send_command(
    session_name: str,
    cmd: str,
    args: dict | None = None,
    timeout: float = 120.0,
) -> dict:
    """Send a JSON command to a running daemon and return its response.

    Connects to the Unix domain socket for *session_name*, transmits
    a newline-delimited JSON payload, and waits for the reply.

    Returns a dict that always contains an ``ok`` key (bool).  On
    failure the dict also contains an ``error`` key with a human-readable
    message.
    """
    sock_path = get_socket_path(session_name)
    if not sock_path.exists():
        return {
            "ok": False,
            "error": (
                f"Session '{session_name}' is not running. "
                "Use 'open' to start a session."
            ),
        }

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(timeout)
        s.connect(str(sock_path))
        payload = json.dumps({"cmd": cmd, "args": args or {}}).encode() + b"\n"
        s.sendall(payload)

        # Read response (may be large for snapshots)
        data = _receive_all(s)
        return json.loads(data)
    except ConnectionRefusedError:
        cleanup_session(session_name)
        return {
            "ok": False,
            "error": (
                f"Session '{session_name}' daemon is not responding. "
                "Socket may be stale. Cleaned up. "
                "Use 'open' to start a new session."
            ),
        }
    except socket.timeout:
        return {"ok": False, "error": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"ok": False, "error": f"Connection error: {e}"}
    finally:
        s.close()


def start_daemon(
    session_name: str,
    config_dict: dict,
    timeout: float = 15.0,
) -> bool:
    """Start the daemon server as a detached subprocess.

    The daemon is launched by running::

        python -c "from patchright_cli.server import start_daemon; ..."

    The function waits up to *timeout* seconds for the Unix socket to
    appear on disk, which signals that the daemon is ready to accept
    commands.

    Returns ``True`` if the daemon started (or was already running),
    ``False`` otherwise.
    """
    sock_path = get_socket_path(session_name)

    # Already running -- nothing to do.
    if sock_path.exists() and is_session_alive(session_name):
        return True

    # Clean up stale files from a previous run.
    if sock_path.exists():
        cleanup_session(session_name)

    config_json = json.dumps(config_dict)

    # Launch daemon detached from this process group.
    # stdout/stderr are set to DEVNULL for the subprocess itself because
    # the daemon configures Python logging to a file internally (daemon.log
    # inside the session directory).
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "from patchright_cli.server import start_daemon; "
                f"start_daemon({session_name!r}, {config_json!r})"
            ),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    # Poll until the socket appears or the process dies.
    start_time = time.monotonic()
    while time.monotonic() - start_time < timeout:
        if sock_path.exists():
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.1)

    return False


def open_session(
    session_name: str,
    config_dict: dict,
    url: str | None = None,
    **open_args: object,
) -> dict:
    """High-level helper for the ``open`` command.

    Ensures the daemon is running (starting it if necessary) and then
    sends the ``open`` command with the provided arguments.
    """
    if not start_daemon(session_name, config_dict):
        return {"ok": False, "error": "Failed to start browser daemon. Check logs."}

    args: dict = {**open_args}
    if url:
        args["url"] = url

    return send_command(session_name, "open", args)


def close_all_sessions() -> list[dict]:
    """Gracefully close every active session.

    Sends the ``close`` command to each running daemon.  Stale sessions
    (process no longer alive) are cleaned up automatically.
    """
    results: list[dict] = []
    for session in list_sessions():
        if session["alive"]:
            result = send_command(session["name"], "close")
            results.append({"name": session["name"], **result})
        else:
            cleanup_session(session["name"])
            results.append(
                {
                    "name": session["name"],
                    "ok": True,
                    "output": "Cleaned up stale session",
                }
            )
    return results


def kill_all_sessions() -> list[dict]:
    """Forcefully terminate all daemon processes via ``SIGTERM``.

    Every session directory is cleaned up regardless of whether the
    kill succeeds.
    """
    results: list[dict] = []
    for session in list_sessions():
        pid = session.get("pid")
        name = session["name"]
        if pid and session["alive"]:
            try:
                os.kill(pid, signal.SIGTERM)
                results.append(
                    {"name": name, "ok": True, "output": f"Killed PID {pid}"}
                )
            except ProcessLookupError:
                results.append({"name": name, "ok": True, "output": "Already dead"})
            except PermissionError:
                results.append(
                    {
                        "name": name,
                        "ok": False,
                        "error": f"Permission denied killing PID {pid}",
                    }
                )
        cleanup_session(name)
    return results


def delete_session_data(session_name: str) -> dict:
    """Delete the entire session directory, including browser user-data.

    The session must not be running; call ``close`` first.
    """
    session_dir = get_session_dir(session_name)
    if is_session_alive(session_name):
        return {
            "ok": False,
            "error": f"Session '{session_name}' is still running. Close it first.",
        }
    try:
        shutil.rmtree(session_dir)
        return {"ok": True, "output": f"Deleted session data for '{session_name}'"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
