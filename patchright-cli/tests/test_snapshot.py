"""Comprehensive tests for the snapshot module (snapshotForAI-based)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from patchright_cli.snapshot import (
    _REF_RE,
    _ROLE_NAME_RE,
    take_snapshot,
)


# ---------------------------------------------------------------------------
# _REF_RE regex tests
# ---------------------------------------------------------------------------


class TestRefRegex:
    """Tests for the _REF_RE regex pattern."""

    def test_matches_ref_with_e_prefix(self):
        m = _REF_RE.search("[ref=e0]")
        assert m is not None
        assert m.group(1) == "e0"

    def test_matches_ref_with_s_prefix(self):
        m = _REF_RE.search("[ref=s10]")
        assert m is not None
        assert m.group(1) == "s10"

    def test_matches_ref_in_context(self):
        m = _REF_RE.search('- link "About" [ref=e2] [cursor=pointer]')
        assert m is not None
        assert m.group(1) == "e2"

    def test_matches_ref_with_large_number(self):
        m = _REF_RE.search("[ref=e999]")
        assert m is not None
        assert m.group(1) == "e999"

    def test_no_match_without_ref(self):
        m = _REF_RE.search('- link "About"')
        assert m is None

    def test_no_match_empty_string(self):
        m = _REF_RE.search("")
        assert m is None

    def test_no_match_similar_but_wrong_format(self):
        m = _REF_RE.search("[level=1]")
        assert m is None

    def test_matches_first_ref_in_line(self):
        m = _REF_RE.search("[ref=e1] [ref=e2]")
        assert m is not None
        assert m.group(1) == "e1"


# ---------------------------------------------------------------------------
# _ROLE_NAME_RE regex tests
# ---------------------------------------------------------------------------


class TestRoleNameRegex:
    """Tests for the _ROLE_NAME_RE regex pattern."""

    def test_matches_role_with_name(self):
        m = _ROLE_NAME_RE.match('  - link "About" ')
        assert m is not None
        assert m.group(1) == "link"
        assert m.group(2) == "About"

    def test_matches_role_without_name(self):
        m = _ROLE_NAME_RE.match("- navigation ")
        assert m is not None
        assert m.group(1) == "navigation"
        assert m.group(2) is None

    def test_matches_deeply_nested(self):
        m = _ROLE_NAME_RE.match('      - button "Submit" ')
        assert m is not None
        assert m.group(1) == "button"
        assert m.group(2) == "Submit"

    def test_matches_name_with_spaces(self):
        m = _ROLE_NAME_RE.match('  - button "Search by voice" ')
        assert m is not None
        assert m.group(1) == "button"
        assert m.group(2) == "Search by voice"

    def test_no_match_property_line(self):
        m = _ROLE_NAME_RE.match("    - /url: https://example.com")
        assert m is None

    def test_no_match_empty_line(self):
        m = _ROLE_NAME_RE.match("")
        assert m is None

    def test_matches_role_with_colon(self):
        m = _ROLE_NAME_RE.match("- navigation:")
        assert m is not None
        assert m.group(1) == "navigation"

    def test_matches_role_with_name_and_colon(self):
        m = _ROLE_NAME_RE.match('  - link "About":')
        assert m is not None
        assert m.group(1) == "link"
        assert m.group(2) == "About"


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_mock_page(snapshot_text: str) -> MagicMock:
    """Create a mock page with snapshotForAI returning the given text.

    Mocks:
    - page._impl_obj._channel.send_return_as_dict -> {'full': snapshot_text}
    """
    page = MagicMock()

    # page._impl_obj._channel.send_return_as_dict for snapshotForAI
    impl = MagicMock()
    channel = MagicMock()
    channel.send_return_as_dict = AsyncMock(
        return_value={"full": snapshot_text}
    )
    impl._channel = channel
    page._impl_obj = impl

    return page


# ---------------------------------------------------------------------------
# take_snapshot (async) tests
# ---------------------------------------------------------------------------


class TestTakeSnapshot:
    """Tests for the async take_snapshot function."""

    async def test_calls_snapshot_for_ai(self):
        """take_snapshot calls snapshotForAI via the channel."""
        page = _make_mock_page('- heading "Welcome" [ref=e0]')
        await take_snapshot(page)
        page._impl_obj._channel.send_return_as_dict.assert_awaited_once_with(
            "snapshotForAI",
            page._impl_obj._channel.send_return_as_dict.call_args[0][1],
            {"timeout": 30000},
            is_internal=True,
        )

    async def test_returns_snapshot_text_unchanged(self):
        """The snapshot text from snapshotForAI is returned as-is."""
        original = '- link "About" [ref=e0] [cursor=pointer]'
        page = _make_mock_page(original)
        text, _, _ = await take_snapshot(page)
        assert text == original

    async def test_parses_single_ref(self):
        """A single element with ref is parsed into refs_dict."""
        page = _make_mock_page('- link "About" [ref=e0]')
        _, refs, counter = await take_snapshot(page)
        assert "e0" in refs
        assert refs["e0"]["selector"] == "aria-ref=e0"
        assert refs["e0"]["role"] == "link"
        assert refs["e0"]["name"] == "About"
        assert counter == 1

    async def test_parses_multiple_refs(self):
        """Multiple elements with refs are all parsed."""
        snapshot = (
            '- link "Home" [ref=e0]\n'
            '- button "Submit" [ref=e1]\n'
            '- textbox "Search" [ref=e2]'
        )
        page = _make_mock_page(snapshot)
        _, refs, counter = await take_snapshot(page)
        assert len(refs) == 3
        assert "e0" in refs
        assert "e1" in refs
        assert "e2" in refs
        assert counter == 3

    async def test_parses_non_sequential_refs(self):
        """Refs from snapshotForAI may not be sequential (e.g., e2, e5)."""
        snapshot = '- link "A" [ref=e2]\n- button "B" [ref=e5]'
        page = _make_mock_page(snapshot)
        _, refs, counter = await take_snapshot(page)
        assert "e2" in refs
        assert "e5" in refs
        assert counter == 6  # max(2,5) + 1

    async def test_parses_unnamed_element(self):
        """Elements without names have name=None in refs_dict."""
        page = _make_mock_page("- navigation [ref=e0]:")
        _, refs, _ = await take_snapshot(page)
        assert refs["e0"]["role"] == "navigation"
        assert refs["e0"]["name"] is None

    async def test_skips_text_content_lines(self):
        """Text content lines (no ref) are not parsed into refs_dict."""
        snapshot = '- paragraph [ref=e0]:\n  - text: Hello world'
        page = _make_mock_page(snapshot)
        _, refs, _ = await take_snapshot(page)
        assert len(refs) == 1
        assert refs["e0"]["role"] == "paragraph"

    async def test_skips_property_lines(self):
        """Property lines (- /url: ...) are not parsed into refs_dict."""
        snapshot = '- link "About" [ref=e0]:\n  - /url: https://example.com'
        page = _make_mock_page(snapshot)
        _, refs, _ = await take_snapshot(page)
        assert len(refs) == 1

    async def test_empty_snapshot(self):
        """Empty snapshotForAI returns empty text and no refs."""
        page = _make_mock_page("")
        text, refs, counter = await take_snapshot(page)
        assert text == ""
        assert refs == {}
        assert counter == 0

    async def test_ref_counter_input_ignored(self):
        """The ref_counter input parameter is ignored."""
        page = _make_mock_page('- button "OK" [ref=e0]')
        _, refs1, c1 = await take_snapshot(page, ref_counter=0)
        page2 = _make_mock_page('- button "OK" [ref=e0]')
        _, refs2, c2 = await take_snapshot(page2, ref_counter=100)
        assert refs1 == refs2
        assert c1 == c2

    async def test_refs_dict_uses_aria_ref_selector(self):
        """refs_dict uses aria-ref=eN selectors (no DOM injection)."""
        snapshot = '- link "A" [ref=e0]\n- button "B" [ref=e1]'
        page = _make_mock_page(snapshot)
        _, refs, _ = await take_snapshot(page)
        assert refs == {
            "e0": {
                "selector": "aria-ref=e0",
                "role": "link",
                "name": "A",
            },
            "e1": {
                "selector": "aria-ref=e1",
                "role": "button",
                "name": "B",
            },
        }

    async def test_complex_snapshot(self):
        """Test a realistic multi-element snapshotForAI output."""
        snapshot = (
            "- banner [ref=e0]:\n"
            '  - heading "My Site" [ref=e1] [level=1]\n'
            "  - navigation [ref=e2]:\n"
            '    - link "Home" [ref=e3] [cursor=pointer]:\n'
            "      - /url: /\n"
            '    - link "About" [ref=e4] [cursor=pointer]:\n'
            "      - /url: /about\n"
            "- main [ref=e5]:\n"
            '  - heading "Welcome" [ref=e6] [level=2]\n'
            '  - textbox "Search" [ref=e7] [active]\n'
            '  - button "Go" [ref=e8] [cursor=pointer]'
        )
        page = _make_mock_page(snapshot)
        text, refs, counter = await take_snapshot(page)

        # All 9 role elements have refs
        assert counter == 9
        assert len(refs) == 9

        # Snapshot text is returned unchanged
        assert text == snapshot

        # Verify some refs
        assert refs["e0"]["role"] == "banner"
        assert refs["e3"]["role"] == "link"
        assert refs["e3"]["name"] == "Home"
        assert refs["e7"]["role"] == "textbox"
        assert refs["e7"]["name"] == "Search"
        assert refs["e8"]["role"] == "button"

    async def test_cursor_and_active_in_snapshot(self):
        """Cursor and active annotations are already in snapshotForAI output."""
        snapshot = (
            '- link "About" [ref=e0] [cursor=pointer]\n'
            '- textbox "Search" [ref=e1] [active]\n'
            '- button "Go" [ref=e2] [cursor=pointer]'
        )
        page = _make_mock_page(snapshot)
        text, _, _ = await take_snapshot(page)
        assert "[cursor=pointer]" in text.split("\n")[0]
        assert "[active]" in text.split("\n")[1]
        assert "[cursor=pointer]" in text.split("\n")[2]

    async def test_combined_cursor_and_active(self):
        """An element can have both cursor=pointer and active."""
        snapshot = '- link "About" [ref=e0] [cursor=pointer] [active]'
        page = _make_mock_page(snapshot)
        text, _, _ = await take_snapshot(page)
        assert "[cursor=pointer]" in text
        assert "[active]" in text

    async def test_preserves_attributes_in_snapshot(self):
        """Attributes like [level=1] are preserved in the snapshot text."""
        snapshot = '- heading "Welcome" [ref=e0] [level=1]'
        page = _make_mock_page(snapshot)
        text, _, _ = await take_snapshot(page)
        assert "[level=1]" in text

    async def test_all_elements_get_refs(self):
        """snapshotForAI gives refs to ALL elements, not just interactive."""
        snapshot = (
            "- navigation [ref=e0]:\n"
            '  - heading "Title" [ref=e1] [level=1]\n'
            '  - link "Home" [ref=e2]'
        )
        page = _make_mock_page(snapshot)
        _, refs, _ = await take_snapshot(page)
        assert len(refs) == 3
        assert refs["e0"]["role"] == "navigation"
        assert refs["e1"]["role"] == "heading"
        assert refs["e2"]["role"] == "link"

    async def test_indentation_preserved(self):
        """Indentation from snapshotForAI is preserved in output."""
        snapshot = (
            "- navigation [ref=e0]:\n"
            '  - link "Home" [ref=e1]:\n'
            "    - /url: /"
        )
        page = _make_mock_page(snapshot)
        text, _, _ = await take_snapshot(page)
        lines = text.split("\n")
        assert lines[0].startswith("- navigation")
        assert lines[1].startswith("  - link")
        assert lines[2] == "    - /url: /"

    async def test_s_prefix_refs(self):
        """Refs with 's' prefix (Playwright style) are also handled."""
        snapshot = '- button "OK" [ref=s5]'
        page = _make_mock_page(snapshot)
        _, refs, _ = await take_snapshot(page)
        assert "s5" in refs
        assert refs["s5"]["role"] == "button"
        assert refs["s5"]["name"] == "OK"

    async def test_counter_from_non_sequential_refs(self):
        """Counter is max ref number + 1, regardless of gaps."""
        snapshot = (
            '- link "A" [ref=e3]\n'
            '- link "B" [ref=e7]\n'
            '- link "C" [ref=e5]'
        )
        page = _make_mock_page(snapshot)
        _, _, counter = await take_snapshot(page)
        assert counter == 8  # max(3,7,5) + 1

    async def test_generic_wrapper_elements(self):
        """Generic wrapper elements from snapshotForAI get refs."""
        snapshot = (
            "- generic [ref=e0]:\n"
            '  - button "Submit" [ref=e1]'
        )
        page = _make_mock_page(snapshot)
        _, refs, _ = await take_snapshot(page)
        assert len(refs) == 2
        assert refs["e0"]["role"] == "generic"
        assert refs["e1"]["role"] == "button"

    async def test_no_dom_interaction(self):
        """take_snapshot does not call page.evaluate or page.get_by_role."""
        page = _make_mock_page('- button "OK" [ref=e0]')
        page.evaluate = AsyncMock()
        page.get_by_role = MagicMock()
        await take_snapshot(page)
        page.evaluate.assert_not_awaited()
        page.get_by_role.assert_not_called()

    async def test_snapshot_for_ai_timeout_parameter(self):
        """snapshotForAI is called with timeout=30000."""
        page = _make_mock_page('- button "OK" [ref=e0]')
        await take_snapshot(page)
        call_args = page._impl_obj._channel.send_return_as_dict.call_args
        assert call_args[0][0] == "snapshotForAI"
        assert call_args[0][2] == {"timeout": 30000}
        assert call_args[1]["is_internal"] is True
