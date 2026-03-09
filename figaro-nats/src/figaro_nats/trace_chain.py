"""Span chain utilities for tracing assertions in tests and diagnostics."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Any

# Prefixes that identify manually instrumented spans
MANUAL_SPAN_PREFIXES = (
    "orchestrator.",
    "worker.",
    "task_manager.",
    "registry.",
    "supervisor.",
    "ui.",
    "gateway.",
)


@dataclass(frozen=True)
class SpanEntry:
    """A single entry in a span chain with name and tree depth."""

    name: str
    depth: int


def _get_span_attr(span: Any, attr: str) -> Any:
    """Get an attribute from a span-like object, supporting both attribute and dict access."""
    if isinstance(span, dict):
        return span.get(attr)
    return getattr(span, attr, None)


def _build_tree(spans: list[Any]) -> dict[str | None, list[Any]]:
    """Build a parent_id -> children mapping from a list of spans."""
    children_map: dict[str | None, list[Any]] = {}
    for span in spans:
        parent_id = _get_span_attr(span, "parent_span_id")
        if parent_id not in children_map:
            children_map[parent_id] = []
        children_map[parent_id].append(span)

    # Sort children by start_time at each level
    for parent_id in children_map:
        children_map[parent_id].sort(key=lambda s: _get_span_attr(s, "start_time") or 0)

    return children_map


def _dfs_collect(
    children_map: dict[str | None, list[Any]],
    parent_id: str | None,
    depth: int,
) -> list[SpanEntry]:
    """DFS traversal collecting SpanEntry items."""
    result: list[SpanEntry] = []
    children = children_map.get(parent_id, [])
    for span in children:
        name = _get_span_attr(span, "name")
        span_id = _get_span_attr(span, "span_id")
        result.append(SpanEntry(name=name, depth=depth))
        result.extend(_dfs_collect(children_map, span_id, depth + 1))
    return result


def _is_manual_span(name: str) -> bool:
    """Check if a span name matches the manual instrumentation naming convention."""
    return any(name.startswith(prefix) for prefix in MANUAL_SPAN_PREFIXES)


def _normalize_repeats(entries: list[SpanEntry]) -> list[SpanEntry]:
    """Collapse consecutive spans with the same name and depth into one with (repeat) suffix."""
    if not entries:
        return []

    result: list[SpanEntry] = []
    prev = entries[0]
    count = 1

    for entry in entries[1:]:
        if entry.name == prev.name and entry.depth == prev.depth:
            count += 1
        else:
            if count > 1:
                result.append(SpanEntry(name=f"{prev.name} (repeat)", depth=prev.depth))
            else:
                result.append(prev)
            prev = entry
            count = 1

    # Flush the last group
    if count > 1:
        result.append(SpanEntry(name=f"{prev.name} (repeat)", depth=prev.depth))
    else:
        result.append(prev)

    return result


def get_span_chain(
    spans: list[Any],
    include_auto: bool = False,
) -> list[SpanEntry]:
    """Build a deterministic span chain from a list of finished spans.

    Args:
        spans: List of span-like objects with name, span_id, parent_span_id, start_time.
        include_auto: If False, filter to only manually instrumented spans (those with
            known prefixes like "orchestrator.", "worker.", etc.).

    Returns:
        List of SpanEntry tuples representing the DFS traversal of the span tree,
        with consecutive duplicate spans normalized to a single entry with " (repeat)" suffix.
    """
    children_map = _build_tree(spans)

    # Find root parent IDs (parent_span_id values that are not any span's span_id)
    all_span_ids = {_get_span_attr(s, "span_id") for s in spans}
    root_parent_ids = [
        pid for pid in children_map if pid is None or pid not in all_span_ids
    ]

    entries: list[SpanEntry] = []
    for root_pid in sorted(root_parent_ids, key=lambda x: (x is not None, x)):
        entries.extend(_dfs_collect(children_map, root_pid, 0))

    if not include_auto:
        entries = [e for e in entries if _is_manual_span(e.name)]

    return _normalize_repeats(entries)


def _format_chain(chain: list[SpanEntry]) -> list[str]:
    """Format a span chain as indented lines for diff display."""
    lines: list[str] = []
    for entry in chain:
        indent = "  " * entry.depth
        lines.append(f"{indent}{entry.name}")
    return lines


def assert_span_chain(
    actual_spans: list[Any],
    expected_chain: list[SpanEntry],
    include_auto: bool = False,
) -> None:
    """Assert that actual spans produce the expected span chain.

    On mismatch, raises AssertionError with a unified diff showing the difference.
    """
    actual_chain = get_span_chain(actual_spans, include_auto=include_auto)

    if actual_chain == expected_chain:
        return

    actual_lines = _format_chain(actual_chain)
    expected_lines = _format_chain(expected_chain)

    diff = list(
        difflib.unified_diff(
            expected_lines,
            actual_lines,
            fromfile="expected",
            tofile="actual",
            lineterm="",
        )
    )
    diff_text = "\n".join(diff)
    raise AssertionError(f"Span chain mismatch:\n{diff_text}")
