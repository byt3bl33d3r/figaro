"""VNC authentication helpers (DES, Apple Remote Desktop)."""

import os
import struct

from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.ciphers import Cipher, modes
from cryptography.hazmat.primitives.ciphers.algorithms import AES
from cryptography.hazmat.primitives.ciphers.modes import ECB
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.serialization import load_der_public_key

from figaro.vnc_proxy.backends import _TcpBackend, _WsBackend


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
    loaded_key = load_der_public_key(der_key_data)
    assert isinstance(loaded_key, RSAPublicKey)
    public_key = loaded_key

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
