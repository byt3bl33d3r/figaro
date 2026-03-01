"""Tests for figaro_supervisor.supervisor.tools module."""

import asyncio
import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from figaro_supervisor.supervisor.tools import _wait_for_delegation, _result
from figaro_nats import Subjects


def _make_client():
    """Create a mock SupervisorNatsClient with the methods _wait_for_delegation needs."""
    client = MagicMock()
    client.supervisor_id = "test-supervisor"

    # Track subscriptions so tests can fire callbacks
    subs = {}

    async def fake_subscribe_task_complete(task_id, handler):
        sub = AsyncMock()
        subs["complete"] = handler
        return sub

    async def fake_js_subscribe(subject, handler, deliver_policy="new"):
        if "error" in subject:
            subs["error"] = handler
        elif "message" in subject:
            subs["message"] = handler
        sub = AsyncMock()
        return sub

    client.subscribe_task_complete = AsyncMock(side_effect=fake_subscribe_task_complete)
    client.conn = MagicMock()
    client.conn.js_subscribe = AsyncMock(side_effect=fake_js_subscribe)

    return client, subs


@pytest.mark.asyncio
async def test_completion_fires_returns_completed():
    """When a completion event fires, _wait_for_delegation returns status=completed."""
    client, subs = _make_client()
    api_result = {"task_id": "task-1", "worker_id": "w1"}

    async def fire_complete():
        # Give subscriptions time to be set up
        await asyncio.sleep(0.01)
        await subs["complete"]({"result": "done!", "task_id": "task-1"})

    asyncio.create_task(fire_complete())

    result = await _wait_for_delegation(client, "task-1", api_result, inactivity_timeout=2.0)
    parsed = json.loads(result["content"][0]["text"])

    assert parsed["status"] == "completed"
    assert parsed["worker_result"] == "done!"
    assert parsed["task_id"] == "task-1"


@pytest.mark.asyncio
async def test_error_fires_returns_failed():
    """When an error event fires, _wait_for_delegation returns status=failed."""
    client, subs = _make_client()
    api_result = {"task_id": "task-2"}

    async def fire_error():
        await asyncio.sleep(0.01)
        await subs["error"]({"error": "something broke", "task_id": "task-2"})

    asyncio.create_task(fire_error())

    result = await _wait_for_delegation(client, "task-2", api_result, inactivity_timeout=2.0)
    parsed = json.loads(result["content"][0]["text"])

    assert parsed["status"] == "failed"
    assert parsed["error"] == "something broke"


@pytest.mark.asyncio
async def test_no_activity_returns_timeout():
    """When no messages arrive within the inactivity timeout, returns timeout."""
    client, subs = _make_client()
    api_result = {"task_id": "task-3"}

    result = await _wait_for_delegation(client, "task-3", api_result, inactivity_timeout=0.1)
    parsed = json.loads(result["content"][0]["text"])

    assert parsed["status"] == "timeout"
    assert "no activity" in parsed["message"].lower()


@pytest.mark.asyncio
async def test_activity_resets_timeout():
    """Activity messages reset the inactivity timer, preventing false timeouts."""
    client, subs = _make_client()
    api_result = {"task_id": "task-4"}

    async def send_activity_then_complete():
        # Send activity messages to keep the timeout resetting
        for _ in range(3):
            await asyncio.sleep(0.05)
            if "message" in subs:
                await subs["message"]({"type": "progress"})
        # Then fire completion
        await asyncio.sleep(0.05)
        await subs["complete"]({"result": "finally done", "task_id": "task-4"})

    asyncio.create_task(send_activity_then_complete())

    # inactivity_timeout=0.1s, but total wall time ~0.2s
    # Without activity resetting, this would timeout
    result = await _wait_for_delegation(client, "task-4", api_result, inactivity_timeout=0.1)
    parsed = json.loads(result["content"][0]["text"])

    assert parsed["status"] == "completed"
    assert parsed["worker_result"] == "finally done"


@pytest.mark.asyncio
async def test_result_helper():
    """Test the _result helper formats correctly."""
    result = _result({"status": "ok"})
    assert result["content"][0]["type"] == "text"
    parsed = json.loads(result["content"][0]["text"])
    assert parsed["status"] == "ok"


# ---------------------------------------------------------------------------
# VNC tool tests
# ---------------------------------------------------------------------------


def _make_vnc_tools_client(request_return_value):
    """Create a mock client and extract VNC tool handlers from create_tools_server.

    Returns a dict mapping tool name -> handler coroutine function,
    plus the mock client so callers can inspect conn.request calls.
    """
    client = MagicMock()
    client.supervisor_id = "test-supervisor"
    client.conn = MagicMock()
    client.conn.request = AsyncMock(return_value=request_return_value)

    captured_tools = []

    def fake_create_sdk_mcp_server(**kwargs):
        captured_tools.extend(kwargs.get("tools", []))
        return {"type": "sdk", "name": kwargs.get("name")}

    with patch(
        "figaro_supervisor.supervisor.tools.create_sdk_mcp_server",
        side_effect=fake_create_sdk_mcp_server,
    ):
        from figaro_supervisor.supervisor.tools import create_tools_server

        create_tools_server(client)

    tools = {t.name: t.handler for t in captured_tools}
    return tools, client


@pytest.mark.asyncio
async def test_take_screenshot():
    """take_screenshot returns image content and dimensions text from a successful response."""
    tools, client = _make_vnc_tools_client(
        {
            "image": "base64data",
            "mime_type": "image/jpeg",
            "original_width": 1920,
            "original_height": 1080,
            "width": 1280,
            "height": 720,
        }
    )
    result = await tools["take_screenshot"]({"worker_id": "w1"})

    assert result == {
        "content": [
            {"type": "image", "data": "base64data", "mimeType": "image/jpeg"},
            {
                "type": "text",
                "text": "Screenshot dimensions: 1280x720 (original: 1920x1080). Use these dimensions for click coordinates.",
            },
        ]
    }
    client.conn.request.assert_awaited_once_with(
        Subjects.API_VNC,
        {
            "action": "screenshot",
            "worker_id": "w1",
            "max_width": 1280,
            "max_height": 800,
        },
        timeout=10.0,
    )


@pytest.mark.asyncio
async def test_take_screenshot_error():
    """take_screenshot propagates an error response."""
    tools, _client = _make_vnc_tools_client({"error": "Worker not found"})
    result = await tools["take_screenshot"]({"worker_id": "w1"})

    assert result["content"][0]["type"] == "text"
    assert "Worker not found" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_type_text():
    """type_text sends the correct NATS payload and returns ok."""
    tools, client = _make_vnc_tools_client({"ok": True})
    result = await tools["type_text"]({"worker_id": "w1", "text": "hello world"})

    parsed = json.loads(result["content"][0]["text"])
    assert parsed["ok"] is True
    client.conn.request.assert_awaited_once_with(
        Subjects.API_VNC,
        {"action": "type", "worker_id": "w1", "text": "hello world"},
        timeout=10.0,
    )


@pytest.mark.asyncio
async def test_press_key():
    """press_key sends key and modifiers in the NATS payload."""
    tools, client = _make_vnc_tools_client({"ok": True})
    result = await tools["press_key"](
        {"worker_id": "w1", "key": "c", "modifiers": ["ctrl", "shift"]}
    )

    parsed = json.loads(result["content"][0]["text"])
    assert parsed["ok"] is True
    client.conn.request.assert_awaited_once_with(
        Subjects.API_VNC,
        {
            "action": "key",
            "worker_id": "w1",
            "key": "c",
            "modifiers": ["ctrl", "shift"],
        },
        timeout=10.0,
    )


@pytest.mark.asyncio
async def test_press_key_no_modifiers():
    """press_key without modifiers defaults to an empty list."""
    tools, client = _make_vnc_tools_client({"ok": True})
    result = await tools["press_key"]({"worker_id": "w1", "key": "Enter"})

    parsed = json.loads(result["content"][0]["text"])
    assert parsed["ok"] is True
    client.conn.request.assert_awaited_once_with(
        Subjects.API_VNC,
        {"action": "key", "worker_id": "w1", "key": "Enter", "modifiers": []},
        timeout=10.0,
    )


@pytest.mark.asyncio
async def test_press_key_hold_seconds():
    """press_key with hold_seconds includes it in the NATS payload."""
    tools, client = _make_vnc_tools_client({"ok": True})
    result = await tools["press_key"](
        {"worker_id": "w1", "key": "a", "hold_seconds": 3.0}
    )

    parsed = json.loads(result["content"][0]["text"])
    assert parsed["ok"] is True
    client.conn.request.assert_awaited_once_with(
        Subjects.API_VNC,
        {
            "action": "key",
            "worker_id": "w1",
            "key": "a",
            "modifiers": [],
            "hold_seconds": 3.0,
        },
        timeout=10.0,
    )


@pytest.mark.asyncio
async def test_press_key_without_hold_seconds_omits_field():
    """press_key without hold_seconds does not include it in the payload."""
    tools, client = _make_vnc_tools_client({"ok": True})
    await tools["press_key"]({"worker_id": "w1", "key": "Enter"})

    call_args = client.conn.request.call_args
    payload = call_args[0][1]
    assert "hold_seconds" not in payload


@pytest.mark.asyncio
async def test_click():
    """click sends x, y, and button in the NATS payload."""
    tools, client = _make_vnc_tools_client({"ok": True})
    result = await tools["click"](
        {"worker_id": "w1", "x": 100, "y": 200, "button": "right"}
    )

    parsed = json.loads(result["content"][0]["text"])
    assert parsed["ok"] is True
    client.conn.request.assert_awaited_once_with(
        Subjects.API_VNC,
        {"action": "click", "worker_id": "w1", "x": 100, "y": 200, "button": "right"},
        timeout=10.0,
    )


@pytest.mark.asyncio
async def test_click_default_button():
    """click without button parameter defaults to 'left'."""
    tools, client = _make_vnc_tools_client({"ok": True})
    result = await tools["click"]({"worker_id": "w1", "x": 50, "y": 75})

    parsed = json.loads(result["content"][0]["text"])
    assert parsed["ok"] is True
    client.conn.request.assert_awaited_once_with(
        Subjects.API_VNC,
        {"action": "click", "worker_id": "w1", "x": 50, "y": 75, "button": "left"},
        timeout=10.0,
    )


@pytest.mark.asyncio
async def test_click_scales_coordinates_after_screenshot():
    """click scales coordinates based on the scale factor from a prior screenshot."""
    # First, take a screenshot to store scale factors (3x scale)
    tools, client = _make_vnc_tools_client(
        {
            "image": "base64data",
            "mime_type": "image/jpeg",
            "original_width": 3840,
            "original_height": 2160,
            "width": 1280,
            "height": 720,
        }
    )
    await tools["take_screenshot"]({"worker_id": "w1"})

    # Now click — coordinates should be scaled from 1280x720 to 3840x2160
    client.conn.request = AsyncMock(return_value={"ok": True})
    await tools["click"]({"worker_id": "w1", "x": 100, "y": 200})

    client.conn.request.assert_awaited_once_with(
        Subjects.API_VNC,
        {"action": "click", "worker_id": "w1", "x": 300, "y": 600, "button": "left"},
        timeout=10.0,
    )


# ---------------------------------------------------------------------------
# send_screenshot tool tests
# ---------------------------------------------------------------------------


def _make_tools_client_with_metadata(request_return_value, source_metadata=None):
    """Create a mock client with source_metadata and extract tool handlers.

    Like _make_vnc_tools_client but passes source_metadata to create_tools_server.
    Returns a dict mapping tool name -> handler coroutine function,
    plus the mock client so callers can inspect conn.request and conn.publish calls.
    """
    client = MagicMock()
    client.supervisor_id = "test-supervisor"
    client.conn = MagicMock()
    client.conn.request = AsyncMock(return_value=request_return_value)
    client.conn.publish = AsyncMock()

    captured_tools = []

    def fake_create_sdk_mcp_server(**kwargs):
        captured_tools.extend(kwargs.get("tools", []))
        return {"type": "sdk", "name": kwargs.get("name")}

    with patch(
        "figaro_supervisor.supervisor.tools.create_sdk_mcp_server",
        side_effect=fake_create_sdk_mcp_server,
    ):
        from figaro_supervisor.supervisor.tools import create_tools_server

        create_tools_server(client, source_metadata=source_metadata)

    tools = {t.name: t.handler for t in captured_tools}
    return tools, client


@pytest.mark.asyncio
async def test_send_screenshot_no_source_metadata():
    """send_screenshot returns error when no source_metadata is provided."""
    tools, _client = _make_tools_client_with_metadata(
        {"image": "base64data", "mime_type": "image/jpeg"},
        source_metadata=None,
    )
    result = await tools["send_screenshot"]({"worker_id": "w1"})

    assert result["content"][0]["type"] == "text"
    assert "Error" in result["content"][0]["text"]
    assert "No channel context" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_send_screenshot_success():
    """send_screenshot takes a screenshot via VNC API and publishes to gateway."""
    tools, client = _make_tools_client_with_metadata(
        {
            "image": "base64data",
            "mime_type": "image/jpeg",
            "original_width": 1920,
            "original_height": 1080,
            "width": 1280,
            "height": 720,
        },
        source_metadata={"channel": "telegram", "chat_id": "12345"},
    )
    result = await tools["send_screenshot"]({"worker_id": "w1"})

    # Should return a success result (plain text, not JSON, since _result receives a string)
    assert result["content"][0]["type"] == "text"
    assert "sent to telegram" in result["content"][0]["text"]

    # Should have called VNC API for the screenshot
    client.conn.request.assert_awaited_once_with(
        Subjects.API_VNC,
        {
            "action": "screenshot",
            "worker_id": "w1",
            "max_width": 1280,
            "max_height": 800,
        },
        timeout=10.0,
    )

    # Should have published the screenshot to the gateway
    client.conn.publish.assert_awaited_once_with(
        Subjects.gateway_send("telegram"),
        {
            "chat_id": "12345",
            "image": "base64data",
            "caption": "Screenshot of w1",
        },
    )


@pytest.mark.asyncio
async def test_send_screenshot_vnc_error():
    """send_screenshot handles VNC API error gracefully."""
    tools, client = _make_tools_client_with_metadata(
        {"error": "Worker not found"},
        source_metadata={"channel": "telegram", "chat_id": "12345"},
    )
    result = await tools["send_screenshot"]({"worker_id": "w1"})

    # Should return an error result
    assert result["content"][0]["type"] == "text"
    assert "Error" in result["content"][0]["text"]
    assert "Worker not found" in result["content"][0]["text"]

    # Should NOT have published to gateway
    client.conn.publish.assert_not_awaited()


# ---------------------------------------------------------------------------
# Scheduled task tool tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_scheduled_task_sends_all_fields():
    """create_scheduled_task sends name, start_url, interval_seconds, and
    enables notify_on_complete, self_learning, self_healing by default."""
    api_response = {"schedule_id": "sched-1", "name": "Test task"}
    tools, client = _make_vnc_tools_client(api_response)

    result = await tools["create_scheduled_task"](
        {
            "name": "Google search for Jerry Lewis birthday",
            "prompt": "Go to google.com and search for Jerry Lewis birthday",
            "start_url": "https://google.com",
            "interval_seconds": 180,
        }
    )

    client.conn.request.assert_awaited_once_with(
        Subjects.API_SCHEDULED_TASK_CREATE,
        {
            "name": "Google search for Jerry Lewis birthday",
            "prompt": "Go to google.com and search for Jerry Lewis birthday",
            "start_url": "https://google.com",
            "interval_seconds": 180,
            "enabled": True,
            "parallel_workers": 1,
            "max_runs": None,
            "notify_on_complete": True,
            "self_learning": True,
            "self_healing": True,
            "self_learning_max_runs": 4,
        },
        timeout=10.0,
    )

    parsed = json.loads(result["content"][0]["text"])
    assert parsed["schedule_id"] == "sched-1"


@pytest.mark.asyncio
async def test_create_scheduled_task_enabled_override():
    """create_scheduled_task respects an explicit enabled=False."""
    tools, client = _make_vnc_tools_client({"schedule_id": "sched-2"})

    await tools["create_scheduled_task"](
        {
            "name": "Disabled task",
            "prompt": "do something",
            "start_url": "https://example.com",
            "interval_seconds": 3600,
            "enabled": False,
        }
    )

    payload = client.conn.request.call_args[0][1]
    assert payload["enabled"] is False
    assert payload["notify_on_complete"] is True
    assert payload["self_learning"] is True
    assert payload["self_healing"] is True


@pytest.mark.asyncio
async def test_create_scheduled_task_no_schedule_field():
    """Regression: create_scheduled_task must NOT send a 'schedule' field.
    The old tool sent 'schedule' (a cron string) which the handler silently
    ignored, causing interval_seconds to default to 3600."""
    tools, client = _make_vnc_tools_client({"schedule_id": "sched-3"})

    await tools["create_scheduled_task"](
        {
            "name": "Test",
            "prompt": "do something",
            "start_url": "https://example.com",
            "interval_seconds": 180,
        }
    )

    payload = client.conn.request.call_args[0][1]
    assert "schedule" not in payload
    assert payload["interval_seconds"] == 180


@pytest.mark.asyncio
async def test_update_scheduled_task_sends_interval_seconds():
    """update_scheduled_task sends interval_seconds (not 'schedule') to the API."""
    tools, client = _make_vnc_tools_client({"schedule_id": "sched-4"})

    await tools["update_scheduled_task"](
        {
            "id": "sched-4",
            "interval_seconds": 300,
        }
    )

    payload = client.conn.request.call_args[0][1]
    assert payload["schedule_id"] == "sched-4"
    assert payload["interval_seconds"] == 300
    assert "schedule" not in payload


@pytest.mark.asyncio
async def test_update_scheduled_task_sends_name_and_start_url():
    """update_scheduled_task can update name and start_url."""
    tools, client = _make_vnc_tools_client({"schedule_id": "sched-5"})

    await tools["update_scheduled_task"](
        {
            "id": "sched-5",
            "name": "Updated name",
            "start_url": "https://new-url.com",
        }
    )

    payload = client.conn.request.call_args[0][1]
    assert payload["schedule_id"] == "sched-5"
    assert payload["name"] == "Updated name"
    assert payload["start_url"] == "https://new-url.com"


@pytest.mark.asyncio
async def test_update_scheduled_task_only_sends_provided_fields():
    """update_scheduled_task only includes fields that were provided in args."""
    tools, client = _make_vnc_tools_client({"schedule_id": "sched-6"})

    await tools["update_scheduled_task"](
        {
            "id": "sched-6",
            "prompt": "new prompt",
        }
    )

    payload = client.conn.request.call_args[0][1]
    assert payload == {"schedule_id": "sched-6", "prompt": "new prompt"}


@pytest.mark.asyncio
async def test_create_scheduled_task_default_self_learning_max_runs():
    """create_scheduled_task defaults self_learning_max_runs to 4."""
    tools, client = _make_vnc_tools_client({"schedule_id": "sched-7"})

    await tools["create_scheduled_task"](
        {
            "name": "Test",
            "prompt": "do something",
            "start_url": "https://example.com",
            "interval_seconds": 600,
        }
    )

    payload = client.conn.request.call_args[0][1]
    assert payload["self_learning_max_runs"] == 4


@pytest.mark.asyncio
async def test_create_scheduled_task_custom_self_learning_max_runs():
    """create_scheduled_task respects an explicit self_learning_max_runs value."""
    tools, client = _make_vnc_tools_client({"schedule_id": "sched-8"})

    await tools["create_scheduled_task"](
        {
            "name": "Test",
            "prompt": "do something",
            "start_url": "https://example.com",
            "interval_seconds": 600,
            "self_learning_max_runs": 10,
        }
    )

    payload = client.conn.request.call_args[0][1]
    assert payload["self_learning_max_runs"] == 10


@pytest.mark.asyncio
async def test_create_scheduled_task_default_parallel_workers():
    """create_scheduled_task defaults parallel_workers to 1."""
    tools, client = _make_vnc_tools_client({"schedule_id": "sched-9"})

    await tools["create_scheduled_task"](
        {
            "name": "Test",
            "prompt": "do something",
            "start_url": "https://example.com",
            "interval_seconds": 600,
        }
    )

    payload = client.conn.request.call_args[0][1]
    assert payload["parallel_workers"] == 1


@pytest.mark.asyncio
async def test_create_scheduled_task_custom_parallel_workers():
    """create_scheduled_task respects an explicit parallel_workers value."""
    tools, client = _make_vnc_tools_client({"schedule_id": "sched-10"})

    await tools["create_scheduled_task"](
        {
            "name": "Test",
            "prompt": "do something",
            "start_url": "https://example.com",
            "interval_seconds": 600,
            "parallel_workers": 3,
        }
    )

    payload = client.conn.request.call_args[0][1]
    assert payload["parallel_workers"] == 3


@pytest.mark.asyncio
async def test_create_scheduled_task_default_max_runs():
    """create_scheduled_task defaults max_runs to None (unlimited)."""
    tools, client = _make_vnc_tools_client({"schedule_id": "sched-11"})

    await tools["create_scheduled_task"](
        {
            "name": "Test",
            "prompt": "do something",
            "start_url": "https://example.com",
            "interval_seconds": 600,
        }
    )

    payload = client.conn.request.call_args[0][1]
    assert payload["max_runs"] is None


@pytest.mark.asyncio
async def test_create_scheduled_task_custom_max_runs():
    """create_scheduled_task respects an explicit max_runs value."""
    tools, client = _make_vnc_tools_client({"schedule_id": "sched-12"})

    await tools["create_scheduled_task"](
        {
            "name": "Test",
            "prompt": "do something",
            "start_url": "https://example.com",
            "interval_seconds": 600,
            "max_runs": 5,
        }
    )

    payload = client.conn.request.call_args[0][1]
    assert payload["max_runs"] == 5
