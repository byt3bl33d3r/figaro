"""PostToolUse hooks for audit trail and result streaming."""

import logging
from typing import Any

from claude_agent_sdk.types import HookContext

from figaro_supervisor.context import get_client, get_task_id

logger = logging.getLogger(__name__)


async def post_tool_use_hook(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: HookContext,
) -> dict[str, Any]:
    """Log tool results and stream to orchestrator.

    This hook fires after tool execution completes, allowing for:
    - Audit logging of tool results
    - Streaming tool completion events to UI
    - Performance monitoring

    Args:
        input_data: Contains tool_name, tool_input, tool_response
        tool_use_id: Unique identifier for this tool invocation
        context: Hook context with session information

    Returns:
        Empty dict (no modifications to tool result)
    """
    tool_name = input_data.get("tool_name", "unknown")
    tool_response = input_data.get("tool_response")

    logger.info(f"PostToolUse: {tool_name} completed (id={tool_use_id})")

    # Stream tool result notification to orchestrator for UI
    client = get_client()
    task_id = get_task_id()
    if client and task_id:
        try:
            await client.publish_task_message(
                task_id,
                {
                    "tool_name": tool_name,
                    "tool_use_id": tool_use_id,
                    # Include truncated response for summary
                    "result_summary": str(tool_response)[:500]
                    if tool_response
                    else None,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to stream tool result: {e}")

    return {}
