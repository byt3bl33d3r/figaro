"""VNC client utilities for remote desktop interaction via asyncvnc."""

from figaro.services.vnc_client.adapter import WsVncAdapter, _WsStreamWriter
from figaro.services.vnc_client.keys import _KEY_ALIASES, _normalize_key
from figaro.services.vnc_client.operations import (
    _process_screenshot,
    click_with_client,
    key_with_client,
    parse_vnc_url,
    screenshot_with_client,
    type_with_client,
    unlock_with_client,
    vnc_click,
    vnc_key,
    vnc_screenshot,
    vnc_type,
)

__all__ = [
    "WsVncAdapter",
    "_WsStreamWriter",
    "_KEY_ALIASES",
    "_normalize_key",
    "_process_screenshot",
    "click_with_client",
    "key_with_client",
    "parse_vnc_url",
    "screenshot_with_client",
    "type_with_client",
    "unlock_with_client",
    "vnc_click",
    "vnc_key",
    "vnc_screenshot",
    "vnc_type",
]
