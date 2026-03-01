"""Accessibility snapshot module for patchright-cli.

Uses Patchright's built-in ``snapshotForAI`` to generate accessibility trees
with element references (ref=eN) that can be used to target elements in
subsequent browser automation commands.

``snapshotForAI`` produces the exact playwright-cli format, including refs on
all elements, ``[cursor=pointer]`` on clickable elements, ``[active]`` on
focused elements, and generic wrapper elements.  Refs are persistent across
calls (cached via ``_ariaRef`` internally).

Elements are resolved at action time using the built-in ``aria-ref=eN``
selector engine — no DOM attribute injection is needed.
"""

from __future__ import annotations

import re
from typing import Any

# Regex to extract ref ids from snapshotForAI output lines.
# Matches [ref=e2], [ref=s10], etc.
_REF_RE = re.compile(r"\[ref=([\w]+)\]")

# Regex to extract role and optional name from the beginning of a snapshot line.
# Groups: (role), (optional quoted name)
_ROLE_NAME_RE = re.compile(r"^\s*- (\w+)(?:\s+\"([^\"]*)\")?\s*")


async def take_snapshot(
    page: Any,
    ref_counter: int = 0,
) -> tuple[str, dict[str, dict[str, str | None]], int]:
    """Take an accessibility snapshot using Patchright's ``snapshotForAI``.

    Calls the built-in ``snapshotForAI`` channel method which produces a
    complete snapshot with refs already assigned.  Elements can then be
    located using the ``aria-ref=eN`` selector engine at action time,
    so no DOM injection is needed.

    Parameters
    ----------
    page:
        A patchright async ``Page`` object.
    ref_counter:
        Ignored.  Kept for API compatibility.  ``snapshotForAI`` manages its
        own ref numbering internally.

    Returns
    -------
    tuple[str, dict[str, dict[str, str | None]], int]
        - **snapshot_text**: Formatted accessibility snapshot with refs.
        - **refs_dict**: Mapping of ref ids to dicts with ``selector``,
          ``role``, and ``name`` keys.
        - **new_ref_counter**: Max ref number + 1 from parsed refs.
    """
    # 1. Get snapshot via the snapshotForAI channel call
    impl = page._impl_obj
    result = await impl._channel.send_return_as_dict(
        "snapshotForAI",
        lambda kw: 30000,
        {"timeout": 30000},
        is_internal=True,
    )
    snapshot_text = result["full"]

    # 2. Parse refs from the snapshot text and build refs dictionary
    #    using aria-ref=eN selectors (resolved by Playwright's built-in
    #    selector engine — no DOM attribute injection needed).
    refs: list[tuple[str, str, str | None]] = []  # (ref_id, role, name)
    for line in snapshot_text.split("\n"):
        ref_match = _REF_RE.search(line)
        if not ref_match:
            continue
        ref_id = ref_match.group(1)
        role_match = _ROLE_NAME_RE.match(line)
        if not role_match:
            continue
        refs.append((ref_id, role_match.group(1), role_match.group(2)))

    refs_dict: dict[str, dict[str, str | None]] = {
        ref_id: {
            "selector": f"aria-ref={ref_id}",
            "role": role,
            "name": name,
        }
        for ref_id, role, name in refs
    }

    # 3. Compute max ref counter from parsed refs
    max_ref_num = -1
    for ref_id, _, _ in refs:
        try:
            num = int(ref_id[1:])  # strip prefix letter (e.g. 'e')
            if num > max_ref_num:
                max_ref_num = num
        except (ValueError, IndexError):
            pass

    return snapshot_text, refs_dict, max_ref_num + 1
