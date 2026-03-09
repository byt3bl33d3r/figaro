"""VNC operations — screenshot, type, key, click, unlock, and standalone wrappers."""

import asyncio
import base64
import io
from urllib.parse import urlparse

import asyncvnc
import numpy as np
from PIL import Image

from figaro.services.vnc_client.keys import _normalize_key


def parse_vnc_url(
    novnc_url: str, default_port: int = 5901
) -> tuple[str, int, str | None, str | None]:
    """Parse a VNC/noVNC URL into (host, port, username, password).

    Extracts all connection parameters from the URL.  Falls back to
    *default_port* when the URL does not include an explicit port
    (5900 for ``vnc://`` scheme, *default_port* otherwise).
    """
    parsed = urlparse(novnc_url)
    host = parsed.hostname or "localhost"
    if parsed.port is not None:
        port = parsed.port
    elif parsed.scheme == "vnc":
        port = 5900
    else:
        port = default_port
    username = parsed.username or None
    password = parsed.password or None
    return host, port, username, password


# ---------------------------------------------------------------------------
# _with_client variants — operate on an already-connected asyncvnc.Client
# ---------------------------------------------------------------------------


def _process_screenshot(
    rgba_array: np.ndarray,
    quality: int,
    max_width: int | None,
    max_height: int | None,
) -> tuple[str, str, int, int, int, int]:
    """CPU-bound screenshot processing (designed for asyncio.to_thread).

    Returns ``(base64_jpeg, mime_type, original_width, original_height,
    display_width, display_height)``.
    """
    image = Image.fromarray(np.asarray(rgba_array, dtype=np.uint8), mode="RGBA")
    original_width, original_height = image.size

    if max_width and max_height:
        image.thumbnail((max_width, max_height), Image.Resampling.BILINEAR)

    display_width, display_height = image.size

    rgb_image = image.convert("RGB")

    buffer = io.BytesIO()
    rgb_image.save(buffer, format="JPEG", quality=quality)
    b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return (
        b64,
        "image/jpeg",
        original_width,
        original_height,
        display_width,
        display_height,
    )


async def screenshot_with_client(
    client: asyncvnc.Client,
    quality: int = 70,
    max_width: int | None = None,
    max_height: int | None = None,
) -> tuple[str, str, int, int, int, int]:
    """Take a screenshot using an already-connected client.

    Returns ``(base64_jpeg, mime_type, original_width, original_height,
    display_width, display_height)``.
    """
    rgba_array = await client.screenshot()
    return await asyncio.to_thread(
        _process_screenshot, rgba_array, quality, max_width, max_height
    )


async def type_with_client(client: asyncvnc.Client, text: str) -> None:
    """Type text using an already-connected client."""
    client.keyboard.write(text)
    await asyncio.sleep(0.05)


async def key_with_client(
    client: asyncvnc.Client,
    key: str,
    modifiers: list[str] | None = None,
    hold_seconds: float | None = None,
) -> None:
    """Press a key combination using an already-connected client.

    When *hold_seconds* is given (and > 0), the keys are held down for that
    many seconds before being released.  Otherwise they are pressed and
    released immediately.
    """
    keys = [_normalize_key(k) for k in (modifiers or [])] + [_normalize_key(key)]
    try:
        if hold_seconds and hold_seconds > 0:
            with client.keyboard.hold(*keys):
                await asyncio.sleep(hold_seconds)
        else:
            client.keyboard.press(*keys)
    except KeyError as e:
        raise ValueError(
            f"Unrecognized key {e}. Use X11 keysym names like 'Ctrl', 'Shift', "
            f"'Alt', 'Return', 'Esc', 'Tab', 'F1'-'F12', etc."
        ) from e
    await asyncio.sleep(0.05)


async def click_with_client(
    client: asyncvnc.Client,
    x: int,
    y: int,
    button: str = "left",
) -> None:
    """Click at coordinates using an already-connected client."""
    client.mouse.move(x, y)
    await asyncio.sleep(0.05)
    if button == "right":
        client.mouse.right_click()
    elif button == "middle":
        client.mouse.middle_click()
    else:
        client.mouse.click()
    await asyncio.sleep(0.05)


async def unlock_with_client(
    client: asyncvnc.Client,
    password: str,
    username: str | None = None,
    click_screen: bool = False,
) -> None:
    """Unlock a desktop lock screen using an already-connected client.

    Performs the unlock sequence server-side so credentials never leave the
    orchestrator process.

    When *click_screen* is ``True``, clicks the centre of the screen first
    to wake the display.  When *username* is provided, types the username
    and presses Tab before typing the password.  Always finishes by pressing
    Enter.
    """
    if click_screen:
        # Click centre of screen to wake the display
        w = client.video.width
        h = client.video.height
        client.mouse.move(w // 2, h // 2)
        await asyncio.sleep(0.05)
        client.mouse.click()
        await asyncio.sleep(0.5)

    if username is not None:
        client.keyboard.write(username)
        await asyncio.sleep(0.05)
        client.keyboard.press("Tab")
        await asyncio.sleep(0.2)

    client.keyboard.write(password)
    await asyncio.sleep(0.05)
    client.keyboard.press("Return")
    await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# Standalone functions — open a new connection per call (backward compat)
# ---------------------------------------------------------------------------


async def vnc_screenshot(
    host: str,
    port: int,
    password: str | None = None,
    quality: int = 70,
    username: str | None = None,
    max_width: int | None = None,
    max_height: int | None = None,
) -> tuple[str, str, int, int, int, int]:
    """Connect to VNC, take screenshot, optionally resize, return dimensions.

    Returns ``(base64_jpeg, mime_type, original_width, original_height,
    display_width, display_height)``.  When *max_width*/*max_height* are
    given and the captured image exceeds those bounds it is resized
    (preserving aspect ratio) so that Claude receives coordinates in a
    known, smaller space.
    """
    async with asyncvnc.connect(
        host, port=port, username=username, password=password
    ) as client:
        return await screenshot_with_client(client, quality, max_width, max_height)


async def vnc_type(
    host: str, port: int, password: str | None, text: str, username: str | None = None
) -> None:
    """Connect to VNC and type text characters one by one."""
    async with asyncvnc.connect(
        host, port=port, username=username, password=password
    ) as client:
        await type_with_client(client, text)


async def vnc_key(
    host: str,
    port: int,
    password: str | None,
    key: str,
    modifiers: list[str] | None = None,
    username: str | None = None,
    hold_seconds: float | None = None,
) -> None:
    """Connect to VNC and press a key combination.

    *modifiers* are held in order, then *key* is pressed and all are released
    in reverse order (matching ``Keyboard.press`` semantics).

    When *hold_seconds* is given, the keys are held for that duration.
    """
    async with asyncvnc.connect(
        host, port=port, username=username, password=password
    ) as client:
        await key_with_client(client, key, modifiers, hold_seconds=hold_seconds)


async def vnc_click(
    host: str,
    port: int,
    password: str | None,
    x: int,
    y: int,
    button: str = "left",
    username: str | None = None,
) -> None:
    """Connect to VNC, move mouse to (*x*, *y*) and click.

    *button* can be ``"left"`` (default), ``"middle"``, or ``"right"``.
    """
    async with asyncvnc.connect(
        host, port=port, username=username, password=password
    ) as client:
        await click_with_client(client, x, y, button)
