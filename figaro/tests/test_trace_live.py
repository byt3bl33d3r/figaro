"""Live tracing integration tests.

These tests require a running NATS server and Jaeger instance.
They are skipped automatically when the infrastructure is not available.
Run with: uv run pytest -m live --record  (to record snapshots)
Run with: uv run pytest -m live           (to verify against snapshots)
"""

import asyncio
import json
import uuid

import pytest
from nats.aio.client import Client as NatsClient
from opentelemetry import propagate, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from figaro_nats import (
    SpanEntry,
    assert_span_chain,
    get_span_chain,
    get_trace_spans,
)

NATS_URL = "nats://nats:4222"
JAEGER_URL = "http://jaeger:16686"
JAEGER_OTLP_URL = "http://jaeger:4318"

# Set up TracerProviders that export to Jaeger so tests can emit root spans
# mirroring what the real services do.
# SimpleSpanProcessor ensures spans are flushed immediately (no batching delay).
_otlp_endpoint = f"{JAEGER_OTLP_URL}/v1/traces"

_ui_provider = TracerProvider(resource=Resource.create({"service.name": "figaro-ui"}))
_ui_provider.add_span_processor(
    SimpleSpanProcessor(OTLPSpanExporter(endpoint=_otlp_endpoint))
)
trace.set_tracer_provider(_ui_provider)

_gateway_provider = TracerProvider(
    resource=Resource.create({"service.name": "figaro-gateway"})
)
_gateway_provider.add_span_processor(
    SimpleSpanProcessor(OTLPSpanExporter(endpoint=_otlp_endpoint))
)

EXPECTED_TASK_SUBMISSION_CHAIN = [
    SpanEntry("ui.task_submission", 0),
    SpanEntry("orchestrator.api_create_task", 1),
    SpanEntry("task_manager.create_task", 2),
    SpanEntry("registry.claim_idle_worker", 2),
    SpanEntry("task_manager.assign_task", 2),
    SpanEntry("orchestrator.publish_task_assignment", 2),
    SpanEntry("worker.handle_task", 1),
    SpanEntry("worker.execute_task", 2),
    SpanEntry("worker.format_task_prompt", 3),
    SpanEntry("worker.publish_task_message (repeat)", 3),
    SpanEntry("worker.publish_task_complete", 3),
    SpanEntry("orchestrator.handle_task_complete", 1),
    SpanEntry("task_manager.complete_task", 2),
    SpanEntry("registry.set_worker_status", 2),
    SpanEntry("orchestrator.process_pending_queue", 2),
]


async def _connect_nats() -> NatsClient:
    """Connect to NATS, raising pytest.skip if unavailable."""
    nc = NatsClient()
    try:
        await nc.connect(NATS_URL, connect_timeout=5)
    except Exception as exc:
        pytest.skip(f"NATS not available at {NATS_URL}: {exc}")
    return nc


async def _submit_task(
    nc: NatsClient, prompt: str, options: dict | None = None
) -> dict:
    """Submit a task via NATS request/reply and return the response.

    Creates a ``ui.task_submission`` root span and injects the W3C
    ``traceparent`` header into the NATS request, mirroring what the
    real UI does in ``figaro-ui/src/api/nats.ts``.
    """
    tracer = trace.get_tracer("figaro")
    with tracer.start_as_current_span(
        "ui.task_submission", attributes={"task.prompt": prompt}
    ):
        payload = {"prompt": prompt, "options": options or {}}

        carrier: dict[str, str] = {}
        propagate.inject(carrier)

        msg = await nc.request(
            "figaro.api.tasks.create",
            json.dumps(payload).encode(),
            timeout=30,
            headers=carrier,
        )
        return json.loads(msg.data)


async def _wait_for_task_complete(
    nc: NatsClient, task_id: str, timeout: float = 120.0
) -> dict:
    """Subscribe to task completion and wait for it."""
    result_future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
    subject = f"figaro.task.{task_id}.complete"

    sub = await nc.subscribe(subject)

    async def _listener() -> None:
        async for msg in sub.messages:
            data = json.loads(msg.data)
            if not result_future.done():
                result_future.set_result(data)
            break

    listener_task = asyncio.create_task(_listener())

    try:
        return await asyncio.wait_for(result_future, timeout=timeout)
    finally:
        await sub.unsubscribe()
        listener_task.cancel()


async def _wait_for_task_event(
    nc: NatsClient, task_id: str, event: str, timeout: float = 120.0
) -> dict:
    """Subscribe to a task event and wait for it."""
    result_future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
    subject = f"figaro.task.{task_id}.{event}"

    sub = await nc.subscribe(subject)

    async def _listener() -> None:
        async for msg in sub.messages:
            data = json.loads(msg.data)
            if not result_future.done():
                result_future.set_result(data)
            break

    listener_task = asyncio.create_task(_listener())

    try:
        return await asyncio.wait_for(result_future, timeout=timeout)
    finally:
        await sub.unsubscribe()
        listener_task.cancel()


def _chain_to_dicts(chain: list[SpanEntry]) -> list[dict]:
    """Convert SpanEntry list to serializable dicts for snapshot storage."""
    return [{"name": e.name, "depth": e.depth} for e in chain]


def _dicts_to_chain(dicts: list[dict]) -> list[SpanEntry]:
    """Convert snapshot dicts back to SpanEntry list."""
    return [SpanEntry(name=d["name"], depth=d["depth"]) for d in dicts]


@pytest.mark.live
async def test_task_submission_span_chain(record_mode, span_chain_snapshot):
    """Submit a real task, wait for completion, assert span chain via Jaeger."""
    nc = await _connect_nats()
    try:
        task_id = str(uuid.uuid4())
        prompt = f"Test task for tracing verification: {task_id}"

        # Subscribe to completion before submitting
        complete_task = asyncio.create_task(
            _wait_for_task_complete(nc, task_id, timeout=120.0)
        )

        response = await _submit_task(
            nc, prompt, options={"task_id": task_id, "target": "worker"}
        )
        assert response.get("task_id") == task_id

        # Wait for task to complete
        await complete_task

        # Query Jaeger for the trace
        spans = await get_trace_spans(
            response.get("trace_id", ""),
            jaeger_url=JAEGER_URL,
            timeout=30.0,
        )

        chain = get_span_chain(spans)

        if span_chain_snapshot.is_recording:
            span_chain_snapshot.save(_chain_to_dicts(chain))
            pytest.skip("Recorded snapshot")
        else:
            saved = span_chain_snapshot.load()
            if saved is not None:
                expected = _dicts_to_chain(saved)
                assert_span_chain(spans, expected)
            else:
                assert_span_chain(spans, EXPECTED_TASK_SUBMISSION_CHAIN)
    finally:
        await nc.close()


@pytest.mark.live
async def test_supervisor_delegation_span_chain(record_mode, span_chain_snapshot):
    """Submit task to supervisor, verify delegation and worker execution chain."""
    nc = await _connect_nats()
    try:
        task_id = str(uuid.uuid4())
        prompt = (
            f"Open https://example.com in the browser and report the page title. "
            f"Trace ID: {task_id}"
        )

        complete_task = asyncio.create_task(
            _wait_for_task_complete(nc, task_id, timeout=180.0)
        )

        response = await _submit_task(
            nc,
            prompt,
            options={"task_id": task_id, "target": "supervisor"},
        )
        assert response.get("task_id") == task_id

        await complete_task

        spans = await get_trace_spans(
            response.get("trace_id", ""),
            jaeger_url=JAEGER_URL,
            timeout=30.0,
        )

        chain = get_span_chain(spans)

        if span_chain_snapshot.is_recording:
            span_chain_snapshot.save(_chain_to_dicts(chain))
            pytest.skip("Recorded snapshot")
        else:
            saved = span_chain_snapshot.load()
            if saved is not None:
                expected = _dicts_to_chain(saved)
                assert_span_chain(spans, expected)
            else:
                # Basic structural assertions when no snapshot exists
                chain_names = [e.name for e in chain]
                assert "orchestrator.api_create_task" in chain_names
                assert "orchestrator.publish_task_assignment" in chain_names
    finally:
        await nc.close()


@pytest.mark.live
async def test_gateway_task_span_chain(record_mode, span_chain_snapshot):
    """Simulate a gateway-originated task (like Telegram), verify full trace chain.

    Publishes directly to figaro.gateway.telegram.task (mimicking what the
    gateway does), waits for the task to complete and for the result to be
    sent back via figaro.gateway.telegram.send, then asserts the span chain.
    """
    nc = await _connect_nats()
    try:
        task_id = str(uuid.uuid4())
        prompt = (
            "Create a scheduled task that runs tomorrow only, at 3pm "
            "and looks up Will Smith's birthday on Google."
        )
        chat_id = "test-chat-123"
        channel = "telegram"

        # Subscribe to completion + gateway send-back before publishing
        complete_task = asyncio.create_task(
            _wait_for_task_complete(nc, task_id, timeout=180.0)
        )
        gateway_send_future: asyncio.Future[dict] = (
            asyncio.get_running_loop().create_future()
        )
        send_sub = await nc.subscribe(f"figaro.gateway.{channel}.send")

        async def _send_listener() -> None:
            async for msg in send_sub.messages:
                data = json.loads(msg.data)
                if data.get("chat_id") == chat_id and not gateway_send_future.done():
                    gateway_send_future.set_result(data)
                break

        send_listener_task = asyncio.create_task(_send_listener())

        # Create root span mimicking the gateway's handle_channel_message
        gateway_tracer = _gateway_provider.get_tracer("figaro")
        with gateway_tracer.start_as_current_span(
            "gateway.handle_channel_message",
            attributes={"gateway.channel": channel, "gateway.chat_id": chat_id},
        ) as span:
            trace_id = format(span.get_span_context().trace_id, "032x")

            carrier: dict[str, str] = {}
            propagate.inject(carrier)

            payload = {
                "channel": channel,
                "chat_id": chat_id,
                "text": prompt,
                "task_id": task_id,
            }
            await nc.publish(
                f"figaro.gateway.{channel}.task",
                json.dumps(payload).encode(),
                headers=carrier,
            )

        # Wait for task completion
        await complete_task

        # Wait for the gateway send-back (orchestrator sends result to channel)
        try:
            await asyncio.wait_for(gateway_send_future, timeout=10.0)
        except asyncio.TimeoutError:
            pass  # send-back is best-effort; trace is still valid without it
        finally:
            await send_sub.unsubscribe()
            send_listener_task.cancel()

        # Query Jaeger for the trace
        spans = await get_trace_spans(
            trace_id,
            jaeger_url=JAEGER_URL,
            timeout=30.0,
        )

        chain = get_span_chain(spans)

        if span_chain_snapshot.is_recording:
            span_chain_snapshot.save(_chain_to_dicts(chain))
            pytest.skip("Recorded snapshot")
        else:
            saved = span_chain_snapshot.load()
            if saved is not None:
                expected = _dicts_to_chain(saved)
                assert_span_chain(spans, expected)
            else:
                # Basic structural assertions when no snapshot exists
                chain_names = [e.name for e in chain]
                assert "gateway.handle_channel_message" in chain_names
                assert "task_manager.create_task" in chain_names
                assert any(
                    name in chain_names
                    for name in [
                        "orchestrator.handle_task_complete",
                        "orchestrator.handle_task_error",
                    ]
                )
    finally:
        await nc.close()


@pytest.mark.live
async def test_failed_task_self_healing_span_chain(record_mode, span_chain_snapshot):
    """Submit a task to a worker that should fail, verify error/healing chain in trace.

    Targets a worker directly (not supervisor) and uses a prompt designed to
    trigger an SDK-level error. If the agent completes gracefully instead of
    erroring, we wait for the complete event and verify the trace chain.
    """
    nc = await _connect_nats()
    try:
        task_id = str(uuid.uuid4())
        prompt = (
            f"This task should fail for healing test: {task_id}. "
            "Navigate to http://nonexistent.invalid and click the submit button."
        )

        # Wait for either error or complete — Claude agents often complete
        # gracefully even on failures (explaining why it couldn't succeed)
        error_future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        complete_future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()

        error_sub = await nc.subscribe(f"figaro.task.{task_id}.error")
        complete_sub = await nc.subscribe(f"figaro.task.{task_id}.complete")

        async def _error_listener() -> None:
            async for msg in error_sub.messages:
                if not error_future.done():
                    error_future.set_result(json.loads(msg.data))
                break

        async def _complete_listener() -> None:
            async for msg in complete_sub.messages:
                if not complete_future.done():
                    complete_future.set_result(json.loads(msg.data))
                break

        error_task = asyncio.create_task(_error_listener())
        complete_task = asyncio.create_task(_complete_listener())

        response = await _submit_task(
            nc,
            prompt,
            options={
                "task_id": task_id,
                "self_healing": True,
                "target": "worker",
            },
        )
        assert response.get("task_id") == task_id

        # Wait for whichever comes first
        done, _ = await asyncio.wait(
            [error_future, complete_future],
            timeout=180.0,
            return_when=asyncio.FIRST_COMPLETED,
        )
        assert done, "Task neither completed nor errored within timeout"

        await error_sub.unsubscribe()
        await complete_sub.unsubscribe()
        error_task.cancel()
        complete_task.cancel()

        # Give time for any healing task to be created and traced
        await asyncio.sleep(5)

        spans = await get_trace_spans(
            response.get("trace_id", ""),
            jaeger_url=JAEGER_URL,
            timeout=30.0,
        )

        chain = get_span_chain(spans)

        if span_chain_snapshot.is_recording:
            span_chain_snapshot.save(_chain_to_dicts(chain))
            pytest.skip("Recorded snapshot")
        else:
            saved = span_chain_snapshot.load()
            if saved is not None:
                expected = _dicts_to_chain(saved)
                assert_span_chain(spans, expected)
            else:
                # Verify we got meaningful spans regardless of error vs complete
                chain_names = [e.name for e in chain]
                assert "task_manager.create_task" in chain_names
                assert any(
                    name in chain_names
                    for name in [
                        "orchestrator.handle_task_error",
                        "orchestrator.handle_task_complete",
                    ]
                )
    finally:
        await nc.close()
