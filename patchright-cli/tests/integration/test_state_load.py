"""Integration tests for cmd_state_save() and cmd_state_load().

These tests exercise saving and restoring browser storage state using real
headless Chromium. They require isolated mode (isolated=True) because
cmd_state_load calls browser.new_context(), which is only available when the
browser and context are separate objects.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patchright_cli.server import BrowserSession


@pytest.mark.integration
async def test_state_save_creates_json(
    browser_session_real: BrowserSession,
    tmp_path: Path,
) -> None:
    """cmd_state_save with an explicit filename should create a valid JSON
    file containing 'cookies' and 'origins' keys."""
    save_path = str(tmp_path / "state.json")
    result = await browser_session_real.cmd_state_save(filename=save_path)

    assert result["ok"] is True
    assert "Storage state saved to" in result["output"]

    data = json.loads(Path(save_path).read_text())
    assert "cookies" in data
    assert "origins" in data


@pytest.mark.integration
async def test_state_load_swaps_context(
    browser_session_real: BrowserSession,
    tmp_path: Path,
) -> None:
    """cmd_state_load should replace the browser context, reset pages and
    element refs, and return ok."""
    save_path = str(tmp_path / "state.json")
    await browser_session_real.cmd_state_save(filename=save_path)

    old_context = browser_session_real.context
    result = await browser_session_real.cmd_state_load(filename=save_path)

    assert result["ok"] is True
    assert browser_session_real.context is not old_context
    assert len(browser_session_real.pages) == 1
    assert browser_session_real.element_refs == {}
    assert browser_session_real.ref_counter == 0


@pytest.mark.integration
async def test_state_load_nonexistent_file(
    browser_session_real: BrowserSession,
) -> None:
    """cmd_state_load with a path that does not exist should return an error."""
    result = await browser_session_real.cmd_state_load(
        filename="/nonexistent/state.json"
    )

    assert result["ok"] is False
    assert "File not found" in result["error"]


@pytest.mark.integration
async def test_state_save_with_filename(
    browser_session_real: BrowserSession,
    tmp_path: Path,
) -> None:
    """cmd_state_save with an explicit custom filename should write the file
    at exactly that path."""
    custom_path = tmp_path / "custom-state.json"
    result = await browser_session_real.cmd_state_save(filename=str(custom_path))

    assert result["ok"] is True
    assert custom_path.exists()
    assert custom_path.stat().st_size > 0
