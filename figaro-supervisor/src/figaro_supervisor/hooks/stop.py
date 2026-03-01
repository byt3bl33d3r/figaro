"""Stop hook for cleanup and state persistence."""

import logging
from typing import Any

from claude_agent_sdk.types import HookContext

logger = logging.getLogger(__name__)


async def stop_hook(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: HookContext,
) -> dict[str, Any]:
    """Clean up and persist state before exit.

    This hook fires when the agent is stopping, allowing for:
    - Resource cleanup
    - State persistence
    - Final logging

    Args:
        input_data: Contains stop_hook_active and other context
        tool_use_id: Not used for stop hooks
        context: Hook context with session information

    Returns:
        Empty dict
    """
    logger.info("Stop hook triggered - cleaning up supervisor session...")

    # Add any cleanup logic here if needed
    # For example: closing connections, saving state, etc.

    return {}
