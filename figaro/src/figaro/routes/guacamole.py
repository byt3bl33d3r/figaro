"""Guacamole token endpoint for browser-based remote desktop access."""

import logging
from urllib.parse import ParseResult, urlparse

from fastapi import APIRouter, HTTPException, Query
from guapy.crypto import GuacamoleCrypto

from figaro.dependencies import RegistryDep, SettingsDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["guacamole"])

SCHEME_TO_PROTOCOL = {
    "vnc": "vnc",
    "rdp": "rdp",
    "ssh": "ssh",
    "telnet": "telnet",
    "ws": "vnc",
    "wss": "vnc",
}

DEFAULT_PORTS = {
    "vnc": 5900,
    "rdp": 3389,
    "ssh": 22,
    "telnet": 23,
}


def _detect_protocol(scheme: str) -> str:
    """Map a URL scheme to a Guacamole protocol name."""
    protocol = SCHEME_TO_PROTOCOL.get(scheme)
    if protocol is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported URL scheme: {scheme}",
        )
    return protocol


def _resolve_host_port(
    parsed: ParseResult, protocol: str, scheme: str, vnc_port: int
) -> tuple[str, int]:
    """Extract hostname and port from a parsed URL."""
    hostname = parsed.hostname or "localhost"

    if scheme in ("ws", "wss"):
        return hostname, vnc_port

    if parsed.port:
        return hostname, parsed.port

    return hostname, DEFAULT_PORTS[protocol]


def _build_connection_settings(
    hostname: str,
    port: int,
    password: str | None,
    username: str | None,
) -> dict[str, str | int]:
    """Build the Guacamole connection settings dict."""
    settings: dict[str, str | int] = {
        "hostname": hostname,
        "port": port,
        "width": 1024,
        "height": 768,
        "dpi": 96,
    }
    if password:
        settings["password"] = password
    if username:
        settings["username"] = username
    return settings


@router.get("/guacamole/token")
async def get_guacamole_token(
    registry: RegistryDep,
    settings: SettingsDep,
    worker_id: str = Query(..., description="Worker ID to connect to"),
) -> dict[str, str]:
    """Generate an encrypted Guacamole connection token for a worker."""
    conn = await registry.get_connection(worker_id)
    if conn is None:
        raise HTTPException(
            status_code=404,
            detail=f"Worker {worker_id} not found",
        )

    if not conn.novnc_url:
        raise HTTPException(
            status_code=400,
            detail=f"Worker {worker_id} has no connection URL",
        )

    parsed = urlparse(conn.novnc_url)
    protocol = _detect_protocol(parsed.scheme)
    hostname, port = _resolve_host_port(
        parsed, protocol, parsed.scheme, settings.vnc_port
    )

    password = conn.vnc_password or settings.vnc_password
    username = conn.vnc_username or settings.vnc_username

    connection_settings = _build_connection_settings(hostname, port, password, username)

    token_data = {
        "connection": {
            "type": protocol,
            "settings": connection_settings,
        }
    }

    crypto = GuacamoleCrypto("AES-256-CBC", settings.encryption_key)
    token = crypto.encrypt(token_data)

    return {"token": token}
