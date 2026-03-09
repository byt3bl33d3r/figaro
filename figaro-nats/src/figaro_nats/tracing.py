"""OpenTelemetry tracing utilities for Figaro services."""

from __future__ import annotations

import asyncio
import functools
import os
from typing import Any, Callable

from opentelemetry import context, propagate, trace
from opentelemetry.context import Context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import StatusCode

TRACER_NAME = "figaro"


def init_tracing(
    service_name: str,
    exporter: SpanExporter | None = None,
) -> None:
    """Set up TracerProvider with OTLP exporter.

    No-op when OTEL_EXPORTER_OTLP_ENDPOINT is not set and no exporter is provided.
    Accepts an optional exporter (e.g. InMemorySpanExporter) for testing.
    """
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint and exporter is None:
        return

    from opentelemetry.sdk.resources import Resource

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    if exporter is not None:
        provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))

    trace.set_tracer_provider(provider)


def inject_trace_context(headers: dict[str, str] | None = None) -> dict[str, str]:
    """Inject current span's W3C traceparent into a headers dict."""
    if headers is None:
        headers = {}
    propagate.inject(headers)
    return headers


def extract_trace_context(headers: dict[str, str] | None) -> Context:
    """Extract trace context from headers dict. Returns Context object."""
    if headers is None:
        return context.get_current()
    return propagate.extract(headers)


def _run_with_span(
    tracer: trace.Tracer,
    name: str,
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Any:
    """Execute a sync function within a span."""
    with tracer.start_as_current_span(name) as span:
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise
        return result


async def _run_with_span_async(
    tracer: trace.Tracer,
    name: str,
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Any:
    """Execute an async function within a span."""
    with tracer.start_as_current_span(name) as span:
        try:
            result = await func(*args, **kwargs)
        except Exception as exc:
            span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise
        return result


def traced(name: str) -> Callable[..., Any]:
    """Decorator that wraps a function with an OpenTelemetry span.

    Works with both sync and async functions.
    """
    tracer = trace.get_tracer(TRACER_NAME)

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                return await _run_with_span_async(tracer, name, func, args, kwargs)

            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            return _run_with_span(tracer, name, func, args, kwargs)

        return sync_wrapper

    return decorator
