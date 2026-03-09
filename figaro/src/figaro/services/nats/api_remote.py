from __future__ import annotations

import asyncio
import logging
from typing import Any, TYPE_CHECKING
from urllib.parse import urlparse

from figaro.services.ssh_client import parse_ssh_url, run_command as ssh_run_command
from figaro.services.telnet_client import (
    parse_telnet_url,
    run_command as telnet_run_command,
)
from figaro.services.vnc_client import (
    click_with_client,
    key_with_client,
    parse_vnc_url,
    screenshot_with_client,
    type_with_client,
    unlock_with_client,
)

if TYPE_CHECKING:
    from figaro.services.nats.service import NatsService

logger = logging.getLogger(__name__)


async def api_vnc(svc: NatsService, data: dict[str, Any]) -> dict[str, Any]:
    """Handle VNC interaction requests (screenshot, type, key, click)."""
    worker_id = data.get("worker_id", "")
    action = data.get("action", "")

    logger.info("VNC %s requested for worker %s", action, worker_id)

    # Look up worker in registry
    conn = await svc._registry.get_connection(worker_id)
    if conn is None:
        logger.warning("VNC %s: worker %s not found in registry", action, worker_id)
        return {"error": "Worker not found"}

    # Extract VNC host/port/credentials from worker's URL
    novnc_url = conn.novnc_url or ""
    url_host, url_port, url_user, url_pass = parse_vnc_url(
        novnc_url, default_port=svc._settings.vnc_port
    )
    # Per-worker fields -> URL-embedded creds -> global settings
    username = conn.vnc_username or url_user or svc._settings.vnc_username
    password = conn.vnc_password or url_pass or svc._settings.vnc_password

    try:
        parsed = urlparse(novnc_url)

        if parsed.scheme == "wss":
            # WebSocket mode — tunnel through websockify (raw VNC port not accessible)
            logger.debug("VNC %s: using WebSocket connection to %s", action, novnc_url)
            ctx = svc._vnc_pool.ws_connection(
                novnc_url,
                username=username,
                password=password,
            )
        elif parsed.scheme == "vnc":
            # Raw TCP mode — URL points directly at VNC server
            logger.debug(
                "VNC %s: using TCP connection to %s:%d", action, url_host, url_port
            )
            ctx = svc._vnc_pool.connection(
                url_host,
                url_port,
                username=username,
                password=password,
            )
        else:
            # ws:// or other — host is reachable, use raw VNC port
            logger.debug(
                "VNC %s: using TCP connection to %s:%d",
                action,
                url_host,
                svc._settings.vnc_port,
            )
            ctx = svc._vnc_pool.connection(
                url_host,
                svc._settings.vnc_port,
                username=username,
                password=password,
            )

        async with ctx as client:
            if action == "screenshot":
                quality = data.get("quality", 70)
                max_width = data.get("max_width")
                max_height = data.get("max_height")
                (
                    image,
                    mime_type,
                    orig_w,
                    orig_h,
                    disp_w,
                    disp_h,
                ) = await screenshot_with_client(
                    client,
                    quality,
                    max_width,
                    max_height,
                )
                logger.info(
                    "VNC screenshot for worker %s: %dx%d -> %dx%d",
                    worker_id,
                    orig_w,
                    orig_h,
                    disp_w,
                    disp_h,
                )
                return {
                    "image": image,
                    "mime_type": mime_type,
                    "original_width": orig_w,
                    "original_height": orig_h,
                    "width": disp_w,
                    "height": disp_h,
                }
            elif action == "type":
                await type_with_client(client, data["text"])
                return {"ok": True}
            elif action == "key":
                await key_with_client(
                    client,
                    data["key"],
                    data.get("modifiers"),
                    hold_seconds=data.get("hold_seconds"),
                )
                return {"ok": True}
            elif action == "click":
                await click_with_client(
                    client,
                    data["x"],
                    data["y"],
                    data.get("button", "left"),
                )
                return {"ok": True}
            elif action == "unlock":
                if not password:
                    logger.warning(
                        "VNC unlock: no password configured for worker %s",
                        worker_id,
                    )
                    return {"error": "No VNC password configured for this worker"}
                await unlock_with_client(
                    client,
                    password,
                    username=username if data.get("username") else None,
                    click_screen=data.get("click_screen", False),
                )
                return {"ok": True}
            else:
                logger.warning(
                    "VNC unknown action '%s' for worker %s", action, worker_id
                )
                return {"error": f"Unknown action: {action}"}
    except asyncio.TimeoutError:
        logger.error(
            "VNC %s timed out for worker %s (url=%s)", action, worker_id, novnc_url
        )
        return {"error": f"VNC connection timed out for worker {worker_id}"}
    except Exception as e:
        logger.exception("VNC %s failed for worker %s", action, worker_id)
        return {"error": str(e)}


async def api_ssh(svc: NatsService, data: dict[str, Any]) -> dict[str, Any]:
    """Handle SSH command execution requests."""
    worker_id = data.get("worker_id", "")
    action = data.get("action", "")

    logger.info("SSH %s requested for worker %s", action, worker_id)

    conn = await svc._registry.get_connection(worker_id)
    if conn is None:
        logger.warning("SSH %s: worker %s not found in registry", action, worker_id)
        return {"error": "Worker not found"}

    novnc_url = conn.novnc_url or ""
    url_host, url_port, url_user, url_pass = parse_ssh_url(novnc_url)
    username = conn.vnc_username or url_user
    password = conn.vnc_password or url_pass

    try:
        if action == "run_command":
            command = data.get("command", "")
            timeout = data.get("timeout", 30.0)
            result = await ssh_run_command(
                url_host, url_port, username, password, command, timeout=timeout
            )
            logger.info(
                "SSH run_command for worker %s: exit_code=%s",
                worker_id,
                result.get("exit_code"),
            )
            return result
        else:
            logger.warning("SSH unknown action '%s' for worker %s", action, worker_id)
            return {"error": f"Unknown action: {action}"}
    except asyncio.TimeoutError:
        logger.error("SSH %s timed out for worker %s", action, worker_id)
        return {"error": f"SSH command timed out for worker {worker_id}"}
    except Exception as e:
        logger.exception("SSH %s failed for worker %s", action, worker_id)
        return {"error": str(e)}


async def api_telnet(svc: NatsService, data: dict[str, Any]) -> dict[str, Any]:
    """Handle telnet command execution requests."""
    worker_id = data.get("worker_id", "")
    action = data.get("action", "")

    logger.info("Telnet %s requested for worker %s", action, worker_id)

    conn = await svc._registry.get_connection(worker_id)
    if conn is None:
        logger.warning("Telnet %s: worker %s not found in registry", action, worker_id)
        return {"error": "Worker not found"}

    novnc_url = conn.novnc_url or ""
    url_host, url_port, url_user, url_pass = parse_telnet_url(novnc_url)
    username = conn.vnc_username or url_user
    password = conn.vnc_password or url_pass

    try:
        if action == "run_command":
            command = data.get("command", "")
            timeout = data.get("timeout", 10.0)
            result = await telnet_run_command(
                url_host, url_port, username, password, command, timeout=timeout
            )
            logger.info("Telnet run_command for worker %s completed", worker_id)
            return result
        else:
            logger.warning(
                "Telnet unknown action '%s' for worker %s", action, worker_id
            )
            return {"error": f"Unknown action: {action}"}
    except asyncio.TimeoutError:
        logger.error("Telnet %s timed out for worker %s", action, worker_id)
        return {"error": f"Telnet command timed out for worker {worker_id}"}
    except Exception as e:
        logger.exception("Telnet %s failed for worker %s", action, worker_id)
        return {"error": str(e)}
