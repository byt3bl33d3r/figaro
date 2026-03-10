"""WebSocket proxy for VNC connections to workers."""

import asyncio
import logging
import ssl
import struct
from typing import TYPE_CHECKING

import websockets
from fastapi import WebSocket

from figaro.services import Registry
from figaro.vnc_proxy.auth import _perform_server_auth
from figaro.vnc_proxy.backends import (
    _TcpBackend,
    _WsBackend,
    _create_ssl_context,
    _forward_client_to_worker,
    _forward_worker_to_client,
    parse_vnc_url,
)

if TYPE_CHECKING:
    from figaro.config import Settings

logger = logging.getLogger(__name__)

# Timeout for a single connection attempt (seconds)
VNC_CONNECT_TIMEOUT = 5
# Interval between retry attempts (seconds)
VNC_RETRY_INTERVAL = 3
# Maximum number of retries before giving up
VNC_MAX_RETRIES = 20  # ~60 seconds total
# Timeout for TLS probe — how long to wait for the server to send data
# on a plain TCP connection before assuming TLS is required
_TLS_PROBE_TIMEOUT = 3.0


async def _present_no_auth_to_client(
    client_ws: WebSocket, server_version: bytes
) -> None:
    """Present 'no auth required' (RFB security type 1) to the browser client."""
    # Send server version to client
    await client_ws.send_bytes(server_version)

    # Read client version
    await client_ws.receive_bytes()

    # Send security types: only type 1 (None)
    await client_ws.send_bytes(bytes([1, 1]))  # 1 type available, type=1

    # Read client's chosen security type
    await client_ws.receive_bytes()

    # Send SecurityResult: OK
    await client_ws.send_bytes(struct.pack("!I", 0))


async def _bridge_server_init(
    client_ws: WebSocket, backend: _TcpBackend | _WsBackend
) -> None:
    """Bridge ClientInit/ServerInit between browser and VNC server."""
    # Read ClientInit from browser (1 byte: shared-flag)
    client_init = await client_ws.receive_bytes()
    await backend.send(client_init)

    # Read ServerInit header from server:
    # width(2) + height(2) + pixel_format(16) + name_length(4) = 24 bytes
    server_init_header = await backend.readexactly(24)
    name_length = struct.unpack("!I", server_init_header[20:24])[0]
    server_name = await backend.readexactly(name_length)

    # Send full ServerInit to client
    await client_ws.send_bytes(server_init_header + server_name)


async def proxy_vnc(
    client_ws: WebSocket,
    worker_id: str,
    registry: Registry,
    settings: "Settings | None" = None,
) -> None:
    """Proxy VNC WebSocket connection from browser to worker.

    Supports both vnc:// (raw TCP) and ws:///wss:// (WebSocket) URLs.
    When a VNC password is configured (per-worker or global), authenticates
    with the VNC server on behalf of the browser and presents "no auth
    required" to the client.

    Args:
        client_ws: WebSocket connection from browser
        worker_id: ID of worker to connect to
        registry: Registry to look up worker's VNC URL
        settings: Optional application settings (for global VNC password)
    """
    # Look up worker
    conn = await registry.get_connection(worker_id)
    if conn is None:
        await client_ws.close(code=4004, reason="Worker not found")
        return

    if not conn.novnc_url:
        await client_ws.close(code=4004, reason="Worker has no VNC URL")
        return

    vnc_url = conn.novnc_url
    logger.info(f"Proxying VNC for worker {worker_id} to {vnc_url}")

    scheme, host, port = parse_vnc_url(vnc_url)

    # Retry loop to connect to worker's VNC
    backend: _TcpBackend | _WsBackend | None = None
    use_tls = False
    for attempt in range(VNC_MAX_RETRIES):
        try:
            logger.debug(f"Connecting to worker VNC (attempt {attempt + 1}): {vnc_url}")
            if scheme == "vnc":
                async with asyncio.timeout(VNC_CONNECT_TIMEOUT):
                    if use_tls:
                        reader, writer = await asyncio.open_connection(
                            host, port, ssl=_create_ssl_context()
                        )
                    else:
                        reader, writer = await asyncio.open_connection(host, port)
                backend = _TcpBackend(reader, writer)

                # Probe for TLS requirement: macOS Screen Sharing requires
                # TLS before the RFB handshake.  On a plain TCP connection
                # the server will either close immediately (EOF) or not
                # send the RFB version at all.
                if not use_tls:
                    try:
                        probe = await asyncio.wait_for(
                            backend._reader.read(1), timeout=_TLS_PROBE_TIMEOUT
                        )
                        if not probe:
                            logger.info(
                                f"VNC server at {host}:{port} closed immediately, "
                                "retrying with TLS (macOS Screen Sharing)"
                            )
                            await backend.close()
                            backend = None
                            use_tls = True
                            continue
                        backend._prepend = probe
                    except asyncio.TimeoutError:
                        logger.info(
                            f"VNC server at {host}:{port} not responding on "
                            "plain TCP, retrying with TLS"
                        )
                        if backend is not None:
                            await backend.close()
                        backend = None
                        use_tls = True
                        continue
            else:
                try:
                    async with asyncio.timeout(VNC_CONNECT_TIMEOUT):
                        # Disable ping to avoid timeout issues - VNC streams binary data
                        # continuously so we don't need keepalive pings
                        ws = await websockets.connect(vnc_url, ping_interval=None)
                    backend = _WsBackend(ws)
                except websockets.exceptions.InvalidURI as e:
                    # InvalidURI is not retryable - fail immediately
                    logger.error(f"Invalid VNC URL {vnc_url}: {e}")
                    await client_ws.close(code=4002, reason="Invalid VNC URL")
                    return
            logger.info(
                f"Connected to worker VNC: {vnc_url}" + (" (TLS)" if use_tls else "")
            )
            break
        except (
            TimeoutError,
            websockets.exceptions.WebSocketException,
            OSError,
            ssl.SSLError,
        ) as e:
            logger.debug(f"VNC connection attempt {attempt + 1} failed: {e}")
            if attempt < VNC_MAX_RETRIES - 1:
                await asyncio.sleep(VNC_RETRY_INTERVAL)
            else:
                logger.error(
                    f"Failed to connect to worker VNC after {VNC_MAX_RETRIES} attempts: {vnc_url}"
                )
                await client_ws.close(code=4003, reason="Cannot connect to worker VNC")
                return

    if backend is None:
        logger.error("Failed to establish VNC connection")
        await client_ws.close(code=4003, reason="Cannot connect to worker VNC")
        return

    # Resolve VNC credentials: per-worker overrides global setting
    password = conn.vnc_password or (settings.vnc_password if settings else None)
    username = conn.vnc_username or (settings.vnc_username if settings else None)

    if password:
        try:
            server_version = await _perform_server_auth(
                backend, password, username=username
            )
            await _present_no_auth_to_client(client_ws, server_version)
            await _bridge_server_init(client_ws, backend)
            logger.info(f"Server-side VNC auth completed for worker {worker_id}")
        except Exception as e:
            logger.error(f"VNC server-side auth failed for worker {worker_id}: {e}")
            await client_ws.close(code=4001, reason="VNC authentication failed")
            await backend.close()
            return

    # Now proxy data between client and worker
    try:
        # Run both directions concurrently
        await asyncio.gather(
            _forward_client_to_worker(client_ws, backend),
            _forward_worker_to_client(client_ws, backend),
            return_exceptions=True,
        )

    except Exception as e:
        logger.exception(f"VNC proxy error: {e}")
        try:
            await client_ws.close(code=4000, reason="Proxy error")
        except Exception:
            pass
    finally:
        await backend.close()
