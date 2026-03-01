"""WebSocket proxy for VNC connections to workers."""

import asyncio
import logging
import os
import ssl
import struct
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import websockets
from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.ciphers import Cipher, modes
from cryptography.hazmat.primitives.ciphers.algorithms import AES
from cryptography.hazmat.primitives.ciphers.modes import ECB
from cryptography.hazmat.primitives.serialization import load_der_public_key
from fastapi import WebSocket, WebSocketDisconnect

from figaro.services import Registry

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


def _create_ssl_context() -> ssl.SSLContext:
    """Create a permissive SSL context for TLS-wrapped VNC connections.

    Used for macOS Screen Sharing which requires TLS before the RFB
    handshake.  Certificate verification is disabled since these are
    typically internal or Tailscale connections.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def parse_vnc_url(url: str) -> tuple[str, str, int]:
    """Parse a VNC URL and return (scheme, host, port).

    Supports vnc://, ws://, and wss:// schemes.
    Default ports: 5900 for vnc://, 6080 for ws:///wss://.

    Args:
        url: The VNC URL to parse.

    Returns:
        A tuple of (scheme, host, port).
    """
    parsed = urlparse(url)
    scheme = parsed.scheme
    host = parsed.hostname or "localhost"
    if parsed.port is not None:
        port = parsed.port
    elif scheme == "vnc":
        port = 5900
    else:
        port = 6080
    return scheme, host, port


class _TcpBackend:
    """Backend wrapping a raw TCP connection (asyncio streams)."""

    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._prepend = b""

    async def send(self, data: bytes) -> None:
        self._writer.write(data)
        await self._writer.drain()

    async def readexactly(self, n: int) -> bytes:
        if self._prepend:
            if len(self._prepend) >= n:
                result = self._prepend[:n]
                self._prepend = self._prepend[n:]
                return result
            remaining = n - len(self._prepend)
            result = self._prepend + await self._reader.readexactly(remaining)
            self._prepend = b""
            return result
        return await self._reader.readexactly(n)

    async def recv(self) -> bytes | None:
        if self._prepend:
            data = self._prepend
            self._prepend = b""
            return data
        data = await self._reader.read(65536)
        if not data:
            return None
        return data

    async def close(self) -> None:
        self._writer.close()
        await self._writer.wait_closed()


class _WsBackend:
    """Backend wrapping a websockets connection."""

    def __init__(self, ws: websockets.WebSocketClientProtocol) -> None:
        self._ws = ws
        self._buf = bytearray()

    async def readexactly(self, n: int) -> bytes:
        while len(self._buf) < n:
            data = await self.recv()
            if data is None:
                raise ConnectionError("WebSocket closed during readexactly")
            self._buf.extend(data)
        result = bytes(self._buf[:n])
        self._buf = self._buf[n:]
        return result

    async def send(self, data: bytes) -> None:
        await self._ws.send(data)

    async def recv(self) -> bytes | None:
        try:
            message = await self._ws.recv()
            if isinstance(message, bytes):
                return message
            return message.encode()
        except websockets.exceptions.ConnectionClosed:
            return None

    async def close(self) -> None:
        await self._ws.close()


async def _forward_client_to_worker(
    client_ws: WebSocket, backend: _TcpBackend | _WsBackend
) -> None:
    """Forward messages from browser to worker."""
    try:
        while True:
            data = await client_ws.receive_bytes()
            await backend.send(data)
    except WebSocketDisconnect:
        logger.debug("Client disconnected")
    except Exception as e:
        logger.debug(f"Client->Worker error: {e}")


async def _forward_worker_to_client(
    client_ws: WebSocket, backend: _TcpBackend | _WsBackend
) -> None:
    """Forward messages from worker to browser."""
    try:
        while True:
            message = await backend.recv()
            if message is None:
                break
            await client_ws.send_bytes(message)
    except Exception as e:
        logger.debug(f"Worker->Client error: {e}")


def _reverse_bits(byte: int) -> int:
    """Reverse the bits in a single byte (VNC DES key encoding)."""
    result = 0
    for _ in range(8):
        result = (result << 1) | (byte & 1)
        byte >>= 1
    return result


def _vnc_des_key(password: str) -> bytes:
    """Convert a VNC password to a DES key with reversed bit order per byte."""
    key = password.encode("ascii")[:8].ljust(8, b"\x00")
    return bytes(_reverse_bits(b) for b in key)


def _vnc_des_response(password: str, challenge: bytes) -> bytes:
    """Compute VNC DES challenge response.

    Uses the same algorithm as asyncvnc: TripleDES in ECB mode with
    the 8-byte VNC key (which TripleDES internally extends by repeating).
    """
    des_key = _vnc_des_key(password)
    encryptor = Cipher(TripleDES(des_key), modes.ECB()).encryptor()
    return encryptor.update(challenge) + encryptor.finalize()


def _pack_ard(data: str) -> bytes:
    """Pack a string into 64 bytes (null-terminated, random-padded).

    Encodes the string to UTF-8, appends a null terminator, and pads
    the remaining bytes with random data to reach 64 bytes total.
    Mirrors asyncvnc's pack_ard() function.
    """
    encoded = data.encode("utf-8") + b"\x00"
    padding_length = 64 - len(encoded)
    return encoded + os.urandom(padding_length)


async def _apple_auth_response(
    username: str,
    password: str,
    backend: _TcpBackend | _WsBackend,
) -> None:
    """Perform Type 33 Apple Remote Desktop authentication.

    Implements the ARD protocol handshake, mirroring asyncvnc lines 492-511.
    Exchanges RSA-encrypted AES key and AES-encrypted credentials with the server.
    """
    # Send ARD auth request
    await backend.send(b"\x00\x00\x00\x0a\x01\x00RSA1\x00\x00\x00\x00")

    # Read response header
    _packet_length = await backend.readexactly(4)
    _version = await backend.readexactly(2)
    key_length_bytes = await backend.readexactly(4)
    key_length = struct.unpack("!I", key_length_bytes)[0]

    # Read DER public key + trailing byte
    der_key_data = await backend.readexactly(key_length)
    _trailing = await backend.readexactly(1)

    # Load the RSA public key from DER format
    public_key = load_der_public_key(der_key_data)

    # Generate random 16-byte AES key
    aes_key = os.urandom(16)

    # Encrypt credentials with AES-128-ECB
    credentials = _pack_ard(username) + _pack_ard(password)
    encryptor = Cipher(AES(aes_key), ECB()).encryptor()
    encrypted_credentials = encryptor.update(credentials) + encryptor.finalize()

    # Encrypt the AES key with RSA PKCS1v15
    encrypted_aes_key = public_key.encrypt(aes_key, PKCS1v15())

    # Send encrypted data
    await backend.send(
        b"\x00\x00\x01\x8a\x01\x00RSA1"
        + b"\x00\x01"
        + encrypted_credentials
        + b"\x00\x01"
        + encrypted_aes_key
    )

    # Read acknowledgement
    await backend.readexactly(4)


async def _perform_server_auth(
    backend: _TcpBackend | _WsBackend,
    password: str,
    username: str | None = None,
) -> bytes:
    """Perform RFB 3.8 handshake and auth with the VNC server.

    Returns the 12-byte server version string so it can be forwarded
    to the browser client.
    """
    # 1. Read server version (12 bytes: "RFB 003.008\n")
    server_version = await backend.readexactly(12)

    # 2. Send client version
    await backend.send(b"RFB 003.008\n")

    # 3. Read security types
    num_types = struct.unpack("!B", await backend.readexactly(1))[0]
    if num_types == 0:
        # Server sent an error
        reason_len = struct.unpack("!I", await backend.readexactly(4))[0]
        reason = (await backend.readexactly(reason_len)).decode("latin-1")
        raise ConnectionError(f"VNC server refused: {reason}")

    sec_types = await backend.readexactly(num_types)

    # 4. Choose security type (prefer 33 → 2 → 1, matching asyncvnc order)
    if 33 in sec_types and username and password:
        # Apple Remote Desktop authentication (type 33)
        await backend.send(bytes([33]))
        await _apple_auth_response(username, password, backend)
    elif 2 in sec_types:
        # VNC Authentication (type 2)
        await backend.send(bytes([2]))

        # 5. Read 16-byte challenge
        challenge = await backend.readexactly(16)

        # 6. Compute and send DES response
        response = _vnc_des_response(password, challenge)
        await backend.send(response)
    elif 1 in sec_types:
        # No auth needed on server side
        await backend.send(bytes([1]))
    else:
        raise ConnectionError(
            f"VNC server doesn't support VNC auth or no-auth: {list(sec_types)}"
        )

    # 7. Read SecurityResult (4 bytes, 0 = OK)
    result = struct.unpack("!I", await backend.readexactly(4))[0]
    if result != 0:
        raise ConnectionError("VNC authentication failed")

    return server_version


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
