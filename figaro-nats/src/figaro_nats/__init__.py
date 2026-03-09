"""Shared NATS messaging library for Figaro."""

from figaro_nats.client import NatsConnection
from figaro_nats.jaeger import JaegerSpan, get_trace_spans
from figaro_nats.streams import ensure_streams
from figaro_nats.subjects import Subjects
from figaro_nats.trace_chain import SpanEntry, assert_span_chain, get_span_chain
from figaro_nats.tracing import (
    extract_trace_context,
    init_tracing,
    inject_trace_context,
    traced,
)

__all__ = [
    "JaegerSpan",
    "NatsConnection",
    "SpanEntry",
    "Subjects",
    "assert_span_chain",
    "ensure_streams",
    "extract_trace_context",
    "get_span_chain",
    "get_trace_spans",
    "init_tracing",
    "inject_trace_context",
    "traced",
]
