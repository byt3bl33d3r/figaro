"""Tests for span chain utilities."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from figaro_nats.trace_chain import SpanEntry, assert_span_chain, get_span_chain


@dataclass
class FakeSpan:
    """Synthetic span for testing."""

    name: str
    span_id: str
    parent_span_id: str | None
    start_time: int


class TestSpanChainDeterministic:
    """Same spans in different order should produce the same chain."""

    def test_span_chain_deterministic(self) -> None:
        spans_order_a = [
            FakeSpan(
                name="orchestrator.handle_task",
                span_id="a",
                parent_span_id=None,
                start_time=100,
            ),
            FakeSpan(
                name="worker.execute", span_id="b", parent_span_id="a", start_time=200
            ),
            FakeSpan(
                name="worker.complete", span_id="c", parent_span_id="a", start_time=300
            ),
        ]
        spans_order_b = [
            FakeSpan(
                name="worker.complete", span_id="c", parent_span_id="a", start_time=300
            ),
            FakeSpan(
                name="orchestrator.handle_task",
                span_id="a",
                parent_span_id=None,
                start_time=100,
            ),
            FakeSpan(
                name="worker.execute", span_id="b", parent_span_id="a", start_time=200
            ),
        ]

        chain_a = get_span_chain(spans_order_a, include_auto=True)
        chain_b = get_span_chain(spans_order_b, include_auto=True)

        assert chain_a == chain_b
        assert chain_a == [
            SpanEntry(name="orchestrator.handle_task", depth=0),
            SpanEntry(name="worker.execute", depth=1),
            SpanEntry(name="worker.complete", depth=1),
        ]


class TestSpanChainNormalizesRepeats:
    """N consecutive same-name spans at the same depth collapse to one with (repeat)."""

    def test_span_chain_normalizes_repeats(self) -> None:
        spans = [
            FakeSpan(
                name="orchestrator.root",
                span_id="root",
                parent_span_id=None,
                start_time=100,
            ),
            FakeSpan(
                name="worker.poll", span_id="p1", parent_span_id="root", start_time=200
            ),
            FakeSpan(
                name="worker.poll", span_id="p2", parent_span_id="root", start_time=300
            ),
            FakeSpan(
                name="worker.poll", span_id="p3", parent_span_id="root", start_time=400
            ),
            FakeSpan(
                name="worker.done", span_id="d1", parent_span_id="root", start_time=500
            ),
        ]

        chain = get_span_chain(spans, include_auto=True)

        assert chain == [
            SpanEntry(name="orchestrator.root", depth=0),
            SpanEntry(name="worker.poll (repeat)", depth=1),
            SpanEntry(name="worker.done", depth=1),
        ]

    def test_single_span_not_marked_repeat(self) -> None:
        spans = [
            FakeSpan(
                name="orchestrator.root",
                span_id="root",
                parent_span_id=None,
                start_time=100,
            ),
            FakeSpan(
                name="worker.step", span_id="s1", parent_span_id="root", start_time=200
            ),
        ]

        chain = get_span_chain(spans, include_auto=True)

        assert chain == [
            SpanEntry(name="orchestrator.root", depth=0),
            SpanEntry(name="worker.step", depth=1),
        ]


class TestSpanChainIgnoresTiming:
    """Different durations should produce the same chain."""

    def test_span_chain_ignores_timing(self) -> None:
        spans_fast = [
            FakeSpan(
                name="orchestrator.process",
                span_id="a",
                parent_span_id=None,
                start_time=100,
            ),
            FakeSpan(
                name="worker.run", span_id="b", parent_span_id="a", start_time=110
            ),
        ]
        spans_slow = [
            FakeSpan(
                name="orchestrator.process",
                span_id="a",
                parent_span_id=None,
                start_time=100,
            ),
            FakeSpan(
                name="worker.run", span_id="b", parent_span_id="a", start_time=99999
            ),
        ]

        chain_fast = get_span_chain(spans_fast, include_auto=True)
        chain_slow = get_span_chain(spans_slow, include_auto=True)

        assert chain_fast == chain_slow
        assert chain_fast == [
            SpanEntry(name="orchestrator.process", depth=0),
            SpanEntry(name="worker.run", depth=1),
        ]


class TestAssertSpanChainShowsDiff:
    """Mismatch produces a readable diff in AssertionError."""

    def test_assert_span_chain_shows_diff(self) -> None:
        spans = [
            FakeSpan(
                name="orchestrator.a", span_id="1", parent_span_id=None, start_time=100
            ),
            FakeSpan(name="worker.b", span_id="2", parent_span_id="1", start_time=200),
        ]
        expected = [
            SpanEntry(name="orchestrator.a", depth=0),
            SpanEntry(name="worker.c", depth=1),  # Wrong name
        ]

        with pytest.raises(AssertionError, match="Span chain mismatch") as exc_info:
            assert_span_chain(spans, expected, include_auto=True)

        error_text = str(exc_info.value)
        assert "worker.b" in error_text
        assert "worker.c" in error_text

    def test_assert_span_chain_passes_on_match(self) -> None:
        spans = [
            FakeSpan(
                name="orchestrator.x", span_id="1", parent_span_id=None, start_time=100
            ),
        ]
        expected = [
            SpanEntry(name="orchestrator.x", depth=0),
        ]

        # Should not raise
        assert_span_chain(spans, expected, include_auto=True)


class TestSpanChainFiltersAutoInstrumented:
    """include_auto=False filters out spans without known prefixes."""

    def test_span_chain_filters_auto_instrumented(self) -> None:
        spans = [
            FakeSpan(
                name="orchestrator.handle",
                span_id="1",
                parent_span_id=None,
                start_time=100,
            ),
            FakeSpan(
                name="HTTP GET /api/tasks",
                span_id="2",
                parent_span_id="1",
                start_time=200,
            ),
            FakeSpan(
                name="worker.execute", span_id="3", parent_span_id="1", start_time=300
            ),
            FakeSpan(name="pg.query", span_id="4", parent_span_id="3", start_time=400),
            FakeSpan(
                name="task_manager.assign",
                span_id="5",
                parent_span_id="3",
                start_time=500,
            ),
        ]

        chain_filtered = get_span_chain(spans, include_auto=False)
        chain_all = get_span_chain(spans, include_auto=True)

        # Filtered should only have spans with known prefixes
        assert chain_filtered == [
            SpanEntry(name="orchestrator.handle", depth=0),
            SpanEntry(name="worker.execute", depth=1),
            SpanEntry(name="task_manager.assign", depth=2),
        ]

        # All spans should include the auto-instrumented ones
        assert len(chain_all) == 5

    def test_empty_spans_returns_empty(self) -> None:
        assert get_span_chain([], include_auto=True) == []
        assert get_span_chain([], include_auto=False) == []
