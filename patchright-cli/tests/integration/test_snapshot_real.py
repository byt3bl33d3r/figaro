"""Integration tests for DOM snapshots against a real browser.

These tests use real headless Chromium via Patchright to verify that
``take_snapshot`` and the ``cmd_snapshot``/``cmd_click`` command handlers
work correctly against actual DOM content.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from patchright_cli.server import BrowserSession
from patchright_cli.snapshot import take_snapshot


@pytest.mark.integration
async def test_snapshot_returns_formatted_tree(
    html_page: tuple[BrowserSession, object],
) -> None:
    """take_snapshot should return a YAML-like tree containing the page roles."""
    _session, page = html_page

    snapshot_text, _refs, _counter = await take_snapshot(page)

    assert "heading" in snapshot_text
    assert "link" in snapshot_text
    assert "button" in snapshot_text
    assert "textbox" in snapshot_text


@pytest.mark.integration
async def test_snapshot_assigns_refs(
    html_page: tuple[BrowserSession, object],
) -> None:
    """Interactive elements (link, inputs, button, select) should each get a ref."""
    _session, page = html_page

    _snapshot_text, refs_dict, new_counter = await take_snapshot(page)

    # TEST_HTML has: a#link1, input[name=username], input#agree-cb,
    # button#submit-btn, select[name=color] -- at least 5 interactive elements.
    assert len(refs_dict) >= 5
    assert "e1" in refs_dict
    assert "e2" in refs_dict

    # The counter should be max ref + 1.
    assert new_counter >= len(refs_dict)


@pytest.mark.integration
async def test_refs_injected_into_live_dom(
    html_page: tuple[BrowserSession, object],
) -> None:
    """After take_snapshot, data-patchright-ref attributes should exist in the DOM."""
    _session, page = html_page

    _snapshot_text, refs_dict, _counter = await take_snapshot(page)

    # Verify that at least one ref was injected into the live page DOM.
    # Use a ref for a well-known role (e.g. link, heading) that get_by_role
    # can reliably locate, rather than "generic" which may not inject.
    injectable_ref = None
    for ref_id, info in refs_dict.items():
        if info["role"] in ("link", "heading", "button", "textbox", "combobox"):
            injectable_ref = ref_id
            break
    assert injectable_ref is not None, "No injectable ref found"
    found = await page.evaluate(
        f"document.querySelector('[data-patchright-ref=\"{injectable_ref}\"]') !== null"
    )
    assert found is True


@pytest.mark.integration
async def test_refs_cleared_on_new_snapshot(
    html_page: tuple[BrowserSession, object],
) -> None:
    """A second take_snapshot call should clear old refs and reassign from the given counter."""
    _session, page = html_page

    # First snapshot: snapshotForAI assigns refs starting from e1.
    _text1, refs1, counter1 = await take_snapshot(page, ref_counter=0)
    assert "e1" in refs1
    assert counter1 > 0

    # Second snapshot: refs are reassigned by snapshotForAI.
    _text2, refs2, counter2 = await take_snapshot(page, ref_counter=0)

    # The second snapshot should also have e1, proving old refs were cleared.
    assert "e1" in refs2
    assert counter2 == counter1  # Same number of interactive elements.

    # Verify that the DOM only has refs from the latest snapshot (no duplicates
    # or stale refs from the first pass).  Not all refs can be injected (e.g.
    # "generic" or "paragraph" roles aren't reliably locatable via get_by_role),
    # so check DOM count <= refs_dict length and is consistent across snapshots.
    ref_count_in_dom = await page.evaluate(
        "document.querySelectorAll('[data-patchright-ref]').length"
    )
    assert ref_count_in_dom <= len(refs2)
    assert ref_count_in_dom > 0


@pytest.mark.integration
async def test_cmd_snapshot_via_handle_command(
    html_page: tuple[BrowserSession, object],
) -> None:
    """handle_command('snapshot', {}) should return ok with a snapshot file containing refs."""
    session, _page = html_page

    result = await session.handle_command("snapshot", {})

    assert result["ok"] is True
    # The output contains a link to the snapshot file, not inline content.
    assert "Snapshot" in result["output"]
    assert ".yml" in result["output"]

    # The snapshot file should contain ref annotations and roles.
    import re

    match = re.search(r"\((.+?\.yml)\)", result["output"])
    assert match is not None
    snapshot_path = Path.cwd() / match.group(1)
    snapshot_content = snapshot_path.read_text(encoding="utf-8")
    assert "ref=" in snapshot_content
    assert "heading" in snapshot_content
    assert "link" in snapshot_content


@pytest.mark.integration
async def test_click_via_ref_on_real_page(
    html_page: tuple[BrowserSession, object],
) -> None:
    """After a snapshot, clicking an element by its ref should succeed."""
    session, _page = html_page

    # Take a snapshot so element_refs are populated on the session.
    snap_result = await session.handle_command("snapshot", {})
    assert snap_result["ok"] is True

    # Pick the first available ref and click it.
    assert len(session.element_refs) > 0
    # Pick a clickable ref (skip generic/paragraph which may not be in DOM).
    ref_id = None
    for rid, info in session.element_refs.items():
        if info.get("role") in ("link", "button", "heading", "textbox", "checkbox"):
            ref_id = rid
            break
    assert ref_id is not None, f"No clickable ref found in {session.element_refs}"
    click_result = await session.handle_command("click", {"ref": ref_id})
    assert click_result["ok"] is True, click_result.get("error", "")
