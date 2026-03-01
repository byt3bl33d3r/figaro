"""
Custom SDK tools with NATS-backed orchestrator operations.
"""

import asyncio
import json
import logging
from typing import Any, TYPE_CHECKING

from claude_agent_sdk import tool, create_sdk_mcp_server

from figaro_nats import Subjects

if TYPE_CHECKING:
    from figaro_supervisor.supervisor.client import SupervisorNatsClient

logger = logging.getLogger(__name__)

DELEGATION_INACTIVITY_TIMEOUT = 600.0


def _result(data: Any) -> dict[str, Any]:
    """Format a result as MCP tool content."""
    text = json.dumps(data, indent=2) if isinstance(data, (dict, list)) else str(data)
    return {"content": [{"type": "text", "text": text}]}


def _error(msg: str) -> dict[str, Any]:
    """Format an error as MCP tool content."""
    return {"content": [{"type": "text", "text": f"Error: {msg}"}]}


async def _wait_for_delegation(
    client: "SupervisorNatsClient",
    delegated_task_id: str,
    api_result: dict[str, Any],
    inactivity_timeout: float = DELEGATION_INACTIVITY_TIMEOUT,
) -> dict[str, Any]:
    """Wait for a delegated task to complete, using a progress-based inactivity timeout.

    Instead of a fixed total timeout, this resets the timer each time the worker
    publishes a task message, so long-running but active tasks are not killed.

    Args:
        client: SupervisorNatsClient for NATS communication
        delegated_task_id: The task ID to monitor
        api_result: The initial API response dict (contains task_id, worker_id, etc.)
        inactivity_timeout: Seconds of inactivity before timing out

    Returns:
        MCP tool content dict with the result
    """
    loop = asyncio.get_running_loop()

    completion_event = asyncio.Event()
    worker_result: dict[str, Any] = {}

    async def _on_complete(data: dict[str, Any]) -> None:
        worker_result.update(data)
        completion_event.set()

    error_event = asyncio.Event()
    error_result: dict[str, Any] = {}

    async def _on_error(data: dict[str, Any]) -> None:
        error_result.update(data)
        error_event.set()

    activity_event = asyncio.Event()

    async def _on_message(data: dict[str, Any]) -> None:
        activity_event.set()

    sub_complete = await client.subscribe_task_complete(delegated_task_id, _on_complete)
    sub_error = await client.conn.js_subscribe(
        Subjects.task_error(delegated_task_id),
        _on_error,
        deliver_policy="new",
    )
    sub_message = await client.conn.js_subscribe(
        Subjects.task_message(delegated_task_id),
        _on_message,
        deliver_policy="new",
    )

    try:
        last_activity = loop.time()
        completion_task = asyncio.create_task(completion_event.wait())
        error_task = asyncio.create_task(error_event.wait())
        activity_task = asyncio.create_task(activity_event.wait())

        while True:
            remaining = inactivity_timeout - (loop.time() - last_activity)
            if remaining <= 0:
                logger.warning(
                    f"Worker inactivity timeout for task {delegated_task_id}"
                )
                return _result(
                    {
                        **api_result,
                        "status": "timeout",
                        "message": f"Worker had no activity for {inactivity_timeout:.0f} seconds",
                    }
                )

            done, _ = await asyncio.wait(
                [completion_task, error_task, activity_task],
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if not done:
                logger.warning(
                    f"Worker inactivity timeout for task {delegated_task_id}"
                )
                return _result(
                    {
                        **api_result,
                        "status": "timeout",
                        "message": f"Worker had no activity for {inactivity_timeout:.0f} seconds",
                    }
                )

            if completion_event.is_set():
                return _result(
                    {
                        **api_result,
                        "status": "completed",
                        "worker_result": worker_result.get("result"),
                    }
                )

            if error_event.is_set():
                return _result(
                    {
                        **api_result,
                        "status": "failed",
                        "error": error_result.get("error", "Unknown error"),
                    }
                )

            # Activity happened -- reset timer and re-wait
            last_activity = loop.time()
            activity_event.clear()
            activity_task = asyncio.create_task(activity_event.wait())
    finally:
        # Cancel any pending tasks
        for task in [completion_task, error_task, activity_task]:
            if not task.done():
                task.cancel()
        # Unsubscribe from all subscriptions
        for sub in [sub_complete, sub_error, sub_message]:
            try:
                await sub.unsubscribe()
            except Exception:
                pass


def create_tools_server(
    client: "SupervisorNatsClient", source_metadata: dict[str, Any] | None = None
) -> Any:
    """Create an SDK MCP server with NATS-backed orchestrator tools.

    Args:
        client: SupervisorNatsClient for NATS communication
        source_metadata: Optional metadata from the task source (e.g. channel, chat_id)

    Returns:
        SDK MCP server to pass directly to ClaudeAgentOptions.mcp_servers
    """
    conn = client.conn

    # Track scale factors from screenshots for coordinate scaling
    _worker_scale: dict[str, tuple[float, float]] = {}

    async def _request(
        subject: str, data: dict[str, Any], timeout: float = 10.0
    ) -> dict[str, Any]:
        """Send a NATS request with error handling."""
        try:
            return await conn.request(subject, data, timeout=timeout)
        except Exception as e:
            logger.error(f"NATS request failed on {subject}: {e}")
            return {"error": f"Request failed: {e}"}

    @tool(
        "delegate_to_worker",
        "Delegate an optimized task to a worker for execution. "
        "This tool blocks until the worker completes the task, returning the full result. "
        "Note: desktop-only workers (those with agent_connected=False) cannot receive "
        "delegated tasks. To interact with desktop-only workers, use the VNC tools "
        "instead (take_screenshot, type_text, press_key, click).",
        {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The optimized task prompt for the worker",
                },
                "worker_id": {
                    "type": "string",
                    "description": "Specific worker ID, or omit for auto-assignment",
                },
            },
            "required": ["prompt"],
        },
    )
    async def delegate_to_worker(args: dict[str, Any]) -> dict[str, Any]:
        result = await _request(
            Subjects.API_DELEGATE,
            {
                "prompt": args["prompt"],
                "worker_id": args.get("worker_id"),
                "supervisor_id": client.supervisor_id,
            },
            timeout=30.0,
        )

        if result.get("error") or result.get("queued"):
            return _result(result)

        delegated_task_id = result.get("task_id")
        if not delegated_task_id:
            return _error("Failed to create delegation task")

        logger.info(f"Delegated task {delegated_task_id}, waiting for completion...")

        return await _wait_for_delegation(client, delegated_task_id, result)

    @tool(
        "list_workers",
        "Get list of connected workers and their status. "
        "Returns worker details including desktop credentials (vnc_username, vnc_password) "
        "which can be used to unlock lock screens via the VNC tools (type_text, press_key).",
        {},
    )
    async def list_workers(args: dict[str, Any]) -> dict[str, Any]:
        return _result(await _request(Subjects.API_WORKERS, {}))

    @tool(
        "list_tasks",
        "Get tasks, optionally filtered by status.",
        {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status (pending, assigned, completed, failed)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of tasks to return",
                    "default": 50,
                },
            },
            "required": [],
        },
    )
    async def list_tasks(args: dict[str, Any]) -> dict[str, Any]:
        return _result(
            await _request(
                Subjects.API_TASKS,
                {"status": args.get("status"), "limit": args.get("limit", 50)},
            )
        )

    @tool(
        "get_task",
        "Get a specific task by ID, including full result and messages.",
        {"task_id": str},
    )
    async def get_task(args: dict[str, Any]) -> dict[str, Any]:
        return _result(
            await _request(Subjects.API_TASK_GET, {"task_id": args["task_id"]})
        )

    @tool("search_tasks", "Search tasks by prompt content.", {"q": str})
    async def search_tasks(args: dict[str, Any]) -> dict[str, Any]:
        return _result(await _request(Subjects.API_TASK_SEARCH, {"q": args["q"]}))

    @tool("get_supervisor_status", "Get status of all connected supervisors.", {})
    async def get_supervisor_status(args: dict[str, Any]) -> dict[str, Any]:
        return _result(await _request(Subjects.API_SUPERVISOR_STATUS, {}))

    @tool("list_scheduled_tasks", "Get all scheduled tasks.", {})
    async def list_scheduled_tasks(args: dict[str, Any]) -> dict[str, Any]:
        return _result(await _request(Subjects.API_SCHEDULED_TASKS, {}))

    @tool("get_scheduled_task", "Get scheduled task details.", {"id": str})
    async def get_scheduled_task(args: dict[str, Any]) -> dict[str, Any]:
        return _result(
            await _request(
                Subjects.API_SCHEDULED_TASK_GET,
                {"schedule_id": args["id"]},
            )
        )

    @tool(
        "create_scheduled_task",
        "Create a new scheduled task. Extracts a short name, the starting URL, and interval from the user request.",
        {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Short descriptive name for the task (e.g. 'Google search for Jerry Lewis birthday')",
                },
                "prompt": {
                    "type": "string",
                    "description": "Task prompt to execute on schedule",
                },
                "start_url": {
                    "type": "string",
                    "description": "URL to navigate to before executing the task (e.g. 'https://google.com')",
                },
                "interval_seconds": {
                    "type": "integer",
                    "description": "How often to run the task, in seconds (e.g. 180 for every 3 minutes, 3600 for every hour)",
                },
                "enabled": {
                    "type": "boolean",
                    "description": "Whether the task is enabled (default: true)",
                },
                "parallel_workers": {
                    "type": "integer",
                    "description": "Number of workers to run in parallel (default: 1)",
                },
                "max_runs": {
                    "type": "integer",
                    "description": "Max total runs before the task auto-disables (default: unlimited)",
                },
                "self_learning_max_runs": {
                    "type": "integer",
                    "description": "Max self-learning optimization runs (default: 4)",
                },
            },
            "required": ["name", "prompt", "start_url", "interval_seconds"],
        },
    )
    async def create_scheduled_task(args: dict[str, Any]) -> dict[str, Any]:
        return _result(
            await _request(
                Subjects.API_SCHEDULED_TASK_CREATE,
                {
                    "name": args["name"],
                    "prompt": args["prompt"],
                    "start_url": args["start_url"],
                    "interval_seconds": args["interval_seconds"],
                    "enabled": args.get("enabled", True),
                    "parallel_workers": args.get("parallel_workers", 1),
                    "max_runs": args.get("max_runs"),
                    "notify_on_complete": True,
                    "self_learning": True,
                    "self_healing": True,
                    "self_learning_max_runs": args.get("self_learning_max_runs", 4),
                },
            )
        )

    @tool(
        "update_scheduled_task",
        "Update a scheduled task. Only include fields that should change.",
        {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Scheduled task ID"},
                "name": {"type": "string", "description": "New name"},
                "prompt": {"type": "string", "description": "New prompt"},
                "start_url": {"type": "string", "description": "New starting URL"},
                "interval_seconds": {
                    "type": "integer",
                    "description": "New interval in seconds",
                },
                "enabled": {"type": "boolean", "description": "New enabled state"},
            },
            "required": ["id"],
        },
    )
    async def update_scheduled_task(args: dict[str, Any]) -> dict[str, Any]:
        data: dict[str, Any] = {"schedule_id": args["id"]}
        for key in ("name", "prompt", "start_url", "interval_seconds", "enabled"):
            if key in args:
                data[key] = args[key]
        return _result(
            await _request(
                Subjects.API_SCHEDULED_TASK_UPDATE,
                data,
                timeout=30.0,
            )
        )

    @tool("delete_scheduled_task", "Delete a scheduled task.", {"id": str})
    async def delete_scheduled_task(args: dict[str, Any]) -> dict[str, Any]:
        return _result(
            await _request(
                Subjects.API_SCHEDULED_TASK_DELETE,
                {"schedule_id": args["id"]},
            )
        )

    @tool(
        "toggle_scheduled_task",
        "Toggle a scheduled task's enabled/disabled state.",
        {"id": str},
    )
    async def toggle_scheduled_task(args: dict[str, Any]) -> dict[str, Any]:
        return _result(
            await _request(
                Subjects.API_SCHEDULED_TASK_TOGGLE,
                {"schedule_id": args["id"]},
            )
        )

    @tool(
        "take_screenshot",
        "Take a screenshot of a worker's desktop. The image is resized to fit within 1280x800. Use the coordinates from this image size when calling click.",
        {
            "type": "object",
            "properties": {
                "worker_id": {
                    "type": "string",
                    "description": "The worker ID to screenshot",
                },
            },
            "required": ["worker_id"],
        },
    )
    async def take_screenshot(args: dict[str, Any]) -> dict[str, Any]:
        response = await _request(
            Subjects.API_VNC,
            {
                "action": "screenshot",
                "worker_id": args["worker_id"],
                "max_width": 1280,
                "max_height": 800,
            },
        )
        if response.get("error"):
            return _error(response["error"])

        # Store scale factor for coordinate mapping
        orig_w = response.get("original_width", 0)
        orig_h = response.get("original_height", 0)
        disp_w = response.get("width", orig_w)
        disp_h = response.get("height", orig_h)
        if disp_w and disp_h:
            _worker_scale[args["worker_id"]] = (orig_w / disp_w, orig_h / disp_h)

        return {
            "content": [
                {
                    "type": "image",
                    "data": response["image"],
                    "mimeType": response["mime_type"],
                },
                {
                    "type": "text",
                    "text": f"Screenshot dimensions: {disp_w}x{disp_h} (original: {orig_w}x{orig_h}). Use these dimensions for click coordinates.",
                },
            ]
        }

    @tool(
        "type_text",
        "Type text on a worker's desktop.",
        {
            "type": "object",
            "properties": {
                "worker_id": {
                    "type": "string",
                    "description": "The worker ID to type text on",
                },
                "text": {
                    "type": "string",
                    "description": "The text to type",
                },
            },
            "required": ["worker_id", "text"],
        },
    )
    async def type_text(args: dict[str, Any]) -> dict[str, Any]:
        response = await _request(
            Subjects.API_VNC,
            {"action": "type", "worker_id": args["worker_id"], "text": args["text"]},
        )
        if response.get("error"):
            return _error(response["error"])
        return _result({"ok": True})

    @tool(
        "press_key",
        "Press a key combination on a worker's desktop. Optionally hold the key(s) down for a specified duration.",
        {
            "type": "object",
            "properties": {
                "worker_id": {
                    "type": "string",
                    "description": "The worker ID to press the key on",
                },
                "key": {
                    "type": "string",
                    "description": "The key to press (e.g. 'Enter', 'Tab', 'a')",
                },
                "modifiers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Modifier keys to hold (e.g. ['ctrl', 'shift'])",
                },
                "hold_seconds": {
                    "type": "number",
                    "description": "How long to hold the key(s) down in seconds. If omitted, the key is pressed and released immediately.",
                },
            },
            "required": ["worker_id", "key"],
        },
    )
    async def press_key(args: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "action": "key",
            "worker_id": args["worker_id"],
            "key": args["key"],
            "modifiers": args.get("modifiers") or [],
        }
        if args.get("hold_seconds"):
            payload["hold_seconds"] = args["hold_seconds"]
        response = await _request(Subjects.API_VNC, payload)
        if response.get("error"):
            return _error(response["error"])
        return _result({"ok": True})

    @tool(
        "click",
        "Click at coordinates on a worker's desktop. Coordinates should match the screenshot dimensions (typically 1280x800).",
        {
            "type": "object",
            "properties": {
                "worker_id": {
                    "type": "string",
                    "description": "The worker ID to click on",
                },
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
                    "description": "Mouse button to click (left, right, middle)",
                    "default": "left",
                },
            },
            "required": ["worker_id", "x", "y"],
        },
    )
    async def click(args: dict[str, Any]) -> dict[str, Any]:
        worker_id = args["worker_id"]
        x = args["x"]
        y = args["y"]
        scale = _worker_scale.get(worker_id)
        if scale:
            x = int(x * scale[0])
            y = int(y * scale[1])

        response = await _request(
            Subjects.API_VNC,
            {
                "action": "click",
                "worker_id": worker_id,
                "x": x,
                "y": y,
                "button": args.get("button", "left"),
            },
        )
        if response.get("error"):
            return _error(response["error"])
        return _result({"ok": True})

    @tool(
        "send_screenshot",
        "Take a screenshot of a worker's desktop and send it to the messaging channel "
        "that originated this task. Only works for tasks received from a messaging channel.",
        {
            "type": "object",
            "properties": {
                "worker_id": {
                    "type": "string",
                    "description": "The worker ID to screenshot",
                },
            },
            "required": ["worker_id"],
        },
    )
    async def send_screenshot(args: dict[str, Any]) -> dict[str, Any]:
        if not source_metadata or not source_metadata.get("channel") or not source_metadata.get("chat_id"):
            return _error(
                "No channel context available — this tool only works for tasks received from a messaging channel"
            )

        channel = source_metadata["channel"]
        chat_id = source_metadata["chat_id"]
        worker_id = args["worker_id"]

        response = await _request(
            Subjects.API_VNC,
            {
                "action": "screenshot",
                "worker_id": worker_id,
                "max_width": 1280,
                "max_height": 800,
            },
        )
        if response.get("error"):
            return _error(response["error"])

        await conn.publish(
            Subjects.gateway_send(channel),
            {
                "chat_id": chat_id,
                "image": response["image"],
                "caption": f"Screenshot of {worker_id}",
            },
        )

        return _result(f"Screenshot of {worker_id} sent to {channel}")

    return create_sdk_mcp_server(
        name="orchestrator",
        version="1.0.0",
        tools=[
            delegate_to_worker,
            list_workers,
            list_tasks,
            get_task,
            search_tasks,
            get_supervisor_status,
            list_scheduled_tasks,
            get_scheduled_task,
            create_scheduled_task,
            update_scheduled_task,
            delete_scheduled_task,
            toggle_scheduled_task,
            take_screenshot,
            type_text,
            press_key,
            click,
            send_screenshot,
        ],
    )
