"""Telnet client utilities for remote command execution via telnetlib3."""

import asyncio
import logging
from urllib.parse import urlparse

import telnetlib3

logger = logging.getLogger(__name__)


def parse_telnet_url(
    url: str, default_port: int = 23
) -> tuple[str, int, str | None, str | None]:
    """Parse a telnet URL into (host, port, username, password).

    Falls back to *default_port* when the URL does not include an explicit port.
    """
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    if parsed.port is not None:
        port = parsed.port
    elif parsed.scheme == "telnet":
        port = 23
    else:
        port = default_port
    username = parsed.username or None
    password = parsed.password or None
    return host, port, username, password


async def run_command(
    host: str,
    port: int,
    username: str | None,
    password: str | None,
    command: str,
    timeout: float = 10.0,
) -> dict[str, str]:
    """Connect to a telnet server and execute a command.

    Opens a fresh connection, handles optional login prompts, sends the
    command, and reads output until EOF or timeout.

    Returns a dict with ``output``.
    """
    reader, writer = await asyncio.wait_for(
        telnetlib3.open_connection(host, port),
        timeout=timeout,
    )

    output_parts: list[str] = []

    try:
        if username is not None:
            data = await asyncio.wait_for(reader.read(4096), timeout=timeout)
            output_parts.append(data)
            writer.write(f"{username}\n")

        if password is not None:
            data = await asyncio.wait_for(reader.read(4096), timeout=timeout)
            output_parts.append(data)
            writer.write(f"{password}\n")

        # Wait for prompt after login
        if username is not None or password is not None:
            data = await asyncio.wait_for(reader.read(4096), timeout=timeout)
            output_parts.append(data)

        # Send the command
        writer.write(f"{command}\n")

        # Read available output until EOF or timeout
        while True:
            try:
                data = await asyncio.wait_for(reader.read(4096), timeout=timeout)
                if not data:
                    break
                output_parts.append(data)
            except asyncio.TimeoutError:
                break

    finally:
        writer.close()

    return {"output": "".join(output_parts)}
