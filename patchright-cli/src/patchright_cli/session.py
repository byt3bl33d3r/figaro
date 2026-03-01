"""Session file management for patchright-cli.

Manages the daemon-per-session directory layout under ~/.patchright-cli/sessions/
and workspace-relative output directories under .patchright-cli/.

Directory layout (per-user, persists across invocations):

    ~/.patchright-cli/
      sessions/
        default/
          server.sock       # Unix domain socket
          pid               # Daemon PID
          config.json       # Session config snapshot
        my-session/
          server.sock
          pid
          config.json

Output directory (workspace-relative, per working directory):

    .patchright-cli/
      page-2026-02-14T19-22-42.yml
      screenshot-2026-02-14T19-22.png
      trace.zip
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Session directory helpers
# ---------------------------------------------------------------------------

_BASE_DIR_NAME = ".patchright-cli"
_SESSIONS_SUBDIR = "sessions"
_SOCKET_FILENAME = "server.sock"
_PID_FILENAME = "pid"
_LOG_FILENAME = "daemon.log"
_ENV_SESSION_VAR = "PLAYWRIGHT_CLI_SESSION"
_DEFAULT_SESSION = "default"


def get_sessions_dir() -> Path:
    """Return ``~/.patchright-cli/sessions/``, creating it if it does not exist."""
    sessions_dir = Path.home() / _BASE_DIR_NAME / _SESSIONS_SUBDIR
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return sessions_dir


def get_session_dir(name: str) -> Path:
    """Return the directory for the given session *name*, creating it if needed."""
    session_dir = get_sessions_dir() / name
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def get_socket_path(name: str) -> Path:
    """Return the Unix domain socket path for the given session."""
    return get_session_dir(name) / _SOCKET_FILENAME


def get_pid_path(name: str) -> Path:
    """Return the PID file path for the given session."""
    return get_session_dir(name) / _PID_FILENAME


def get_log_path(name: str) -> Path:
    """Return the log file path for the given session."""
    return get_session_dir(name) / _LOG_FILENAME


def get_config_path(name: str) -> Path:
    """Return the config.json path for the given session."""
    return get_session_dir(name) / "config.json"


def read_session_config(name: str) -> dict | None:
    """Read the config.json for a session, returning None if not found."""
    config_path = get_config_path(name)
    try:
        import json

        return json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError, json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# PID management
# ---------------------------------------------------------------------------


def write_pid(name: str, pid: int) -> None:
    """Write *pid* to the session's PID file."""
    pid_path = get_pid_path(name)
    pid_path.write_text(str(pid), encoding="utf-8")


def read_pid(name: str) -> int | None:
    """Read the PID from the session's PID file.

    Returns ``None`` if the file is missing, empty, or contains non-integer
    content.
    """
    pid_path = get_pid_path(name)
    try:
        text = pid_path.read_text(encoding="utf-8").strip()
        if not text:
            return None
        return int(text)
    except FileNotFoundError, ValueError:
        return None


def is_session_alive(name: str) -> bool:
    """Return ``True`` if the daemon process for *name* is still running.

    Uses ``os.kill(pid, 0)`` which checks for process existence without
    sending a signal.  Returns ``False`` when the PID file is missing or the
    process no longer exists.
    """
    pid = read_pid(name)
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we lack permission to signal it — still alive.
        return True
    return True


# ---------------------------------------------------------------------------
# Session enumeration & cleanup
# ---------------------------------------------------------------------------


def list_sessions() -> list[dict]:
    """Scan session directories and return a summary for each.

    Each entry is a dict with keys:

    * ``name``  — session directory name (``str``)
    * ``alive`` — whether the daemon PID is running (``bool``)
    * ``pid``   — the PID read from the file, or ``None``
    """
    sessions_dir = get_sessions_dir()
    results: list[dict] = []
    for entry in sorted(sessions_dir.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        pid = read_pid(name)
        alive = is_session_alive(name)
        config = read_session_config(name)
        results.append({"name": name, "alive": alive, "pid": pid, "config": config})
    return results


def cleanup_session(name: str) -> None:
    """Remove the socket and PID files for a dead session.

    Only the transient runtime files (``server.sock`` and ``pid``) are
    removed.  The session directory and any ``config.json`` are left intact
    so that configuration is preserved for the next launch.
    """
    socket_path = get_socket_path(name)
    pid_path = get_pid_path(name)
    for path in (socket_path, pid_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Session name resolution
# ---------------------------------------------------------------------------


def resolve_session_name(cli_arg: str | None) -> str:
    """Determine which session name to use.

    Priority (highest to lowest):

    1. Explicit *cli_arg* (if not ``None`` and not empty).
    2. The ``PLAYWRIGHT_CLI_SESSION`` environment variable.
    3. ``"default"``.
    """
    if cli_arg:
        return cli_arg
    env_value = os.environ.get(_ENV_SESSION_VAR, "").strip()
    if env_value:
        return env_value
    return _DEFAULT_SESSION


# ---------------------------------------------------------------------------
# Output directory & filenames
# ---------------------------------------------------------------------------


def get_output_dir() -> Path:
    """Return ``.patchright-cli/`` relative to the current working directory.

    Creates the directory if it does not already exist.
    """
    output_dir = Path.cwd() / _BASE_DIR_NAME
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def generate_output_filename(prefix: str, ext: str) -> Path:
    """Generate a timestamped output file path.

    Returns a ``Path`` of the form::

        .patchright-cli/{prefix}-{ISO timestamp}.{ext}

    The ISO-8601 timestamp has colons replaced with dashes so it is safe for
    filesystems that disallow colons (e.g. Windows/NTFS, macOS HFS+ in some
    contexts).

    The *ext* parameter should be supplied **without** a leading dot
    (e.g. ``"png"``, not ``".png"``).
    """
    now = datetime.now(timezone.utc)
    # Produce a compact ISO timestamp: 2026-02-14T19-22-42
    timestamp = now.isoformat(timespec="seconds").replace(":", "-")
    filename = f"{prefix}-{timestamp}.{ext}"
    return get_output_dir() / filename
