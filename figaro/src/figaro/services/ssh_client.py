"""SSH client utilities for remote command execution via asyncssh."""

import logging
from urllib.parse import urlparse

import asyncssh

logger = logging.getLogger(__name__)


def parse_ssh_url(
    url: str, default_port: int = 22
) -> tuple[str, int, str | None, str | None]:
    """Parse an SSH URL into (host, port, username, password).

    Supports ``ssh://user:pass@host:port`` format.  Falls back to
    *default_port* when the URL does not include an explicit port.
    """
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port if parsed.port is not None else default_port
    username = parsed.username or None
    password = parsed.password or None
    return host, port, username, password


async def run_command(
    host: str,
    port: int,
    username: str | None,
    password: str | None,
    command: str,
    timeout: float = 30.0,
) -> dict:
    """Connect to an SSH server and execute a command.

    Returns a dict with ``stdout``, ``stderr``, and ``exit_code``.
    """
    conn_kwargs: dict = {
        "port": port,
        "known_hosts": None,
    }
    if username:
        conn_kwargs["username"] = username
    if password:
        conn_kwargs["password"] = password

    async with asyncssh.connect(host, **conn_kwargs) as conn:
        result = await conn.run(command, timeout=timeout)
        exit_code = result.exit_status if result.exit_status is not None else -1
        return {
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "exit_code": exit_code,
        }
