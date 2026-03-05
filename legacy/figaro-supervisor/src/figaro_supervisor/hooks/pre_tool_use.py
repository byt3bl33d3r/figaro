"""PreToolUse hooks for logging and monitoring."""

import logging
from typing import Any

from claude_agent_sdk.types import HookContext

logger = logging.getLogger(__name__)


async def pre_tool_use_hook(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: HookContext,
) -> dict[str, Any]:
    """Log all tool calls before execution.

    This hook fires before any tool is executed, allowing for:
    - Audit logging of tool usage
    - Debugging tool call parameters
    - Security monitoring

    Args:
        input_data: Contains tool_name, tool_input, and other context
        tool_use_id: Unique identifier for this tool invocation
        context: Hook context with session information

    Returns:
        Empty dict to allow the tool to proceed
    """
    tool_name = input_data.get("tool_name", "unknown")
    tool_input = input_data.get("tool_input", {})

    logger.info(f"PreToolUse: {tool_name} (id={tool_use_id})")
    logger.debug(f"Tool input: {tool_input}")

    # Return empty dict to allow tool execution to proceed
    return {}
