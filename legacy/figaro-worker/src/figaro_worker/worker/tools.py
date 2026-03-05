"""
Desktop control tools for the worker agent.

Provides direct X11 desktop interaction via xdotool and gnome-screenshot,
exposed as SDK MCP tools using the @tool + create_sdk_mcp_server pattern.
The worker runs inside a container with X11 desktop (DISPLAY=:1).
"""

import asyncio
import base64
import json
import logging
import os
import tempfile
from typing import Any

from claude_agent_sdk import tool, create_sdk_mcp_server

logger = logging.getLogger(__name__)

BUTTON_MAP = {"left": "1", "middle": "2", "right": "3"}


async def _run_command(*args: str) -> tuple[str, str, int]:
    """Run a subprocess command with DISPLAY=:1 set.

    Args:
        *args: Command and arguments to execute.

    Returns:
        Tuple of (stdout, stderr, returncode).
    """
    env = {**os.environ, "DISPLAY": ":1"}
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await proc.communicate()
    return (
        stdout.decode() if stdout else "",
        stderr.decode() if stderr else "",
        proc.returncode or 0,
    )


def _result(data: Any) -> dict[str, Any]:
    """Format a result as MCP tool content."""
    text = json.dumps(data, indent=2) if isinstance(data, (dict, list)) else str(data)
    return {"content": [{"type": "text", "text": text}]}


def _error(msg: str) -> dict[str, Any]:
    """Format an error as MCP tool content."""
    return {"content": [{"type": "text", "text": f"Error: {msg}"}]}


def create_desktop_tools_server() -> Any:
    """Create an SDK MCP server with desktop control tools.

    Returns:
        SDK MCP server to pass directly to ClaudeAgentOptions.mcp_servers
    """

    @tool(
        "screenshot",
        "Capture a screenshot of the desktop. Returns the image as base64 PNG.",
        {
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    async def screenshot(args: dict[str, Any]) -> dict[str, Any]:
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_path = tmp.name
        tmp.close()

        try:
            stdout, stderr, rc = await _run_command(
                "scrot", "--overwrite", tmp_path
            )
            if rc != 0:
                return _error(f"scrot failed (rc={rc}): {stderr}")

            with open(tmp_path, "rb") as f:
                image_bytes = f.read()

            if not image_bytes:
                return _error("Screenshot file is empty")

            b64_data = base64.b64encode(image_bytes).decode("utf-8")
            return {
                "content": [
                    {
                        "type": "image",
                        "data": b64_data,
                        "mimeType": "image/png",
                    }
                ]
            }
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    @tool(
        "mouse_click",
        "Click the mouse at the specified coordinates.",
        {
            "type": "object",
            "properties": {
                "x": {
                    "type": "integer",
                    "description": "X coordinate to click at",
                },
                "y": {
                    "type": "integer",
                    "description": "Y coordinate to click at",
                },
                "button": {
                    "type": "string",
                    "description": "Mouse button: left, middle, or right",
                    "default": "left",
                },
            },
            "required": ["x", "y"],
        },
    )
    async def mouse_click(args: dict[str, Any]) -> dict[str, Any]:
        x = str(args["x"])
        y = str(args["y"])
        button = BUTTON_MAP.get(args.get("button", "left"), "1")

        stdout, stderr, rc = await _run_command(
            "xdotool", "mousemove", "--sync", x, y, "click", button
        )
        if rc != 0:
            return _error(f"xdotool click failed (rc={rc}): {stderr}")
        return _result({"ok": True, "x": args["x"], "y": args["y"]})

    @tool(
        "mouse_move",
        "Move the mouse to the specified coordinates.",
        {
            "type": "object",
            "properties": {
                "x": {
                    "type": "integer",
                    "description": "X coordinate to move to",
                },
                "y": {
                    "type": "integer",
                    "description": "Y coordinate to move to",
                },
            },
            "required": ["x", "y"],
        },
    )
    async def mouse_move(args: dict[str, Any]) -> dict[str, Any]:
        x = str(args["x"])
        y = str(args["y"])

        stdout, stderr, rc = await _run_command(
            "xdotool", "mousemove", "--sync", x, y
        )
        if rc != 0:
            return _error(f"xdotool mousemove failed (rc={rc}): {stderr}")
        return _result({"ok": True, "x": args["x"], "y": args["y"]})

    @tool(
        "type_text",
        "Type text on the desktop keyboard.",
        {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to type",
                },
                "delay": {
                    "type": "integer",
                    "description": "Delay in milliseconds between keystrokes",
                    "default": 50,
                },
            },
            "required": ["text"],
        },
    )
    async def type_text(args: dict[str, Any]) -> dict[str, Any]:
        text = args["text"]
        delay = str(args.get("delay", 50))

        stdout, stderr, rc = await _run_command(
            "xdotool", "type", "--delay", delay, "--", text
        )
        if rc != 0:
            return _error(f"xdotool type failed (rc={rc}): {stderr}")
        return _result({"ok": True, "length": len(text)})

    @tool(
        "press_key",
        "Press a key or key combination (e.g. 'ctrl+c', 'Return', 'alt+F4').",
        {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "string",
                    "description": "Key combination to press (e.g. 'ctrl+c', 'Return', 'alt+Tab')",
                },
            },
            "required": ["keys"],
        },
    )
    async def press_key(args: dict[str, Any]) -> dict[str, Any]:
        keys = args["keys"]

        stdout, stderr, rc = await _run_command(
            "xdotool", "key", "--", keys
        )
        if rc != 0:
            return _error(f"xdotool key failed (rc={rc}): {stderr}")
        return _result({"ok": True, "keys": keys})

    @tool(
        "scroll",
        "Scroll the mouse wheel up or down.",
        {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "description": "Scroll direction: 'up' or 'down'",
                },
                "clicks": {
                    "type": "integer",
                    "description": "Number of scroll clicks",
                    "default": 3,
                },
            },
            "required": ["direction"],
        },
    )
    async def scroll(args: dict[str, Any]) -> dict[str, Any]:
        direction = args["direction"]
        clicks = args.get("clicks", 3)

        # xdotool: button 4 = scroll up, button 5 = scroll down
        button = "4" if direction == "up" else "5"

        stdout, stderr, rc = await _run_command(
            "xdotool", "click", "--repeat", str(clicks), "--delay", "50", button
        )
        if rc != 0:
            return _error(f"xdotool scroll failed (rc={rc}): {stderr}")
        return _result({"ok": True, "direction": direction, "clicks": clicks})

    @tool(
        "mouse_drag",
        "Drag the mouse from one position to another with smooth, human-like movement. "
        "The drag uses eased interpolation so the cursor accelerates and decelerates naturally.",
        {
            "type": "object",
            "properties": {
                "start_x": {
                    "type": "integer",
                    "description": "Starting X coordinate",
                },
                "start_y": {
                    "type": "integer",
                    "description": "Starting Y coordinate",
                },
                "end_x": {
                    "type": "integer",
                    "description": "Ending X coordinate",
                },
                "end_y": {
                    "type": "integer",
                    "description": "Ending Y coordinate",
                },
                "button": {
                    "type": "string",
                    "description": "Mouse button: left, middle, or right",
                    "default": "left",
                },
                "duration_ms": {
                    "type": "integer",
                    "description": "Total duration of the drag in milliseconds",
                    "default": 600,
                },
                "steps": {
                    "type": "integer",
                    "description": "Number of intermediate movement steps (auto-calculated from distance if omitted)",
                },
            },
            "required": ["start_x", "start_y", "end_x", "end_y"],
        },
    )
    async def mouse_drag(args: dict[str, Any]) -> dict[str, Any]:
        start_x = args["start_x"]
        start_y = args["start_y"]
        end_x = args["end_x"]
        end_y = args["end_y"]
        button = BUTTON_MAP.get(args.get("button", "left"), "1")
        duration_ms = args.get("duration_ms", 600)

        dx = end_x - start_x
        dy = end_y - start_y
        distance = (dx * dx + dy * dy) ** 0.5

        # Auto-calculate steps: ~1 per 5px, clamped to [10, 50]
        steps = args.get("steps")
        if steps is None:
            steps = max(10, min(50, int(distance / 5)))
        steps = max(1, steps)

        step_delay = max(0.001, duration_ms / steps / 1000.0)

        # Build a bash script with individual xdotool calls separated by
        # bash sleep.  Chaining subcommands inside a single xdotool
        # invocation (xdotool mousedown ... sleep ... mousemove ...) is
        # unreliable — the mousedown fires but subsequent moves are lost.
        # Individual calls are proven to generate proper X11 MotionNotify
        # events that applications recognise as a drag.
        #
        # This still runs as a single subprocess, so the Python event loop
        # is never blocked (await proc.communicate() yields while bash runs).
        lines: list[str] = [
            f"xdotool mousemove --sync {start_x} {start_y}",
            f"xdotool mousedown {button}",
        ]

        for i in range(1, steps + 1):
            t = i / steps
            # Ease-in-out cubic for natural acceleration/deceleration
            if t < 0.5:
                eased = 4 * t * t * t
            else:
                eased = 1 - (-2 * t + 2) ** 3 / 2

            x = int(start_x + dx * eased)
            y = int(start_y + dy * eased)

            lines.append(f"sleep {step_delay:.4f}")
            lines.append(f"xdotool mousemove {x} {y}")

        lines.append(f"xdotool mouseup {button}")

        _, stderr, rc = await _run_command("bash", "-c", "\n".join(lines))
        if rc != 0:
            return _error(f"xdotool drag failed (rc={rc}): {stderr}")
        return _result({
            "ok": True,
            "from": {"x": start_x, "y": start_y},
            "to": {"x": end_x, "y": end_y},
            "steps": steps,
            "duration_ms": duration_ms,
        })

    return create_sdk_mcp_server(
        name="desktop",
        version="1.0.0",
        tools=[
            screenshot,
            mouse_click,
            mouse_move,
            type_text,
            press_key,
            scroll,
            mouse_drag,
        ],
    )
