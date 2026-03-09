"""Jaeger trace retrieval utilities."""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError

logger = logging.getLogger(__name__)


@dataclass
class JaegerSpan:
    """A span retrieved from the Jaeger API."""

    name: str
    span_id: str
    parent_span_id: str | None
    start_time: int
    duration: int
    service_name: str
    tags: dict[str, Any] = field(default_factory=dict)


def _parse_jaeger_spans(data: dict[str, Any]) -> list[JaegerSpan]:
    """Parse Jaeger API response JSON into JaegerSpan objects."""
    spans: list[JaegerSpan] = []
    traces = data.get("data", [])

    for trace_data in traces:
        # Build process map for service names
        processes = trace_data.get("processes", {})
        process_service_map: dict[str, str] = {}
        for process_id, process_info in processes.items():
            process_service_map[process_id] = process_info.get("serviceName", "unknown")

        for span_data in trace_data.get("spans", []):
            # Extract parent span ID from references
            parent_span_id: str | None = None
            for ref in span_data.get("references", []):
                if ref.get("refType") == "CHILD_OF":
                    parent_span_id = ref.get("spanID")
                    break

            # Extract tags as a flat dict
            tags: dict[str, Any] = {}
            for tag in span_data.get("tags", []):
                tags[tag["key"]] = tag["value"]

            process_id = span_data.get("processID", "")
            service_name = process_service_map.get(process_id, "unknown")

            spans.append(
                JaegerSpan(
                    name=span_data["operationName"],
                    span_id=span_data["spanID"],
                    parent_span_id=parent_span_id,
                    start_time=span_data["startTime"],
                    duration=span_data["duration"],
                    service_name=service_name,
                    tags=tags,
                )
            )

    return spans


def _fetch_trace(trace_id: str, jaeger_url: str) -> list[JaegerSpan] | None:
    """Attempt a single fetch of a trace from Jaeger. Returns None if not found yet."""
    url = f"{jaeger_url}/api/traces/{trace_id}"
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read()
            data = json.loads(body)
            spans = _parse_jaeger_spans(data)
            if spans:
                return spans
    except HTTPError as exc:
        if exc.code == 404:
            return None
        logger.warning(f"Jaeger HTTP error {exc.code} fetching trace {trace_id}")
    except URLError as exc:
        logger.warning(f"Jaeger connection error fetching trace {trace_id}: {exc}")
    except json.JSONDecodeError:
        logger.warning(f"Jaeger returned invalid JSON for trace {trace_id}")

    return None


async def get_trace_spans(
    trace_id: str,
    jaeger_url: str = "http://localhost:16686",
    timeout: float = 30.0,
    poll_interval: float = 2.0,
    stable_count: int = 3,
) -> list[JaegerSpan]:
    """Poll Jaeger API until the trace stabilizes or timeout is reached.

    Spans arrive incrementally as BatchSpanProcessors flush across services.
    This function waits until the span count remains unchanged for
    ``stable_count`` consecutive polls before returning.

    Args:
        trace_id: The trace ID to look up.
        jaeger_url: Base URL of the Jaeger UI/API.
        timeout: Maximum seconds to wait for the trace to appear and stabilize.
        poll_interval: Seconds between poll attempts.
        stable_count: Number of consecutive polls with an unchanged span count
            required before the trace is considered stable.

    Returns:
        List of JaegerSpan objects from the trace.

    Raises:
        TimeoutError: If the trace doesn't appear within the timeout.
    """
    elapsed = 0.0
    last_spans: list[JaegerSpan] | None = None
    unchanged_polls = 0

    while elapsed < timeout:
        loop = asyncio.get_running_loop()
        spans = await loop.run_in_executor(None, _fetch_trace, trace_id, jaeger_url)

        if spans is not None:
            if last_spans is not None and len(spans) == len(last_spans):
                unchanged_polls += 1
                if unchanged_polls >= stable_count:
                    return spans
            else:
                unchanged_polls = 0
            last_spans = spans

        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    if last_spans is not None:
        return last_spans

    raise TimeoutError(f"Trace {trace_id} not found in Jaeger after {timeout}s")
