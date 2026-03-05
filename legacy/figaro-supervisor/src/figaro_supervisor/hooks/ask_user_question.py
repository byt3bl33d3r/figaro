"""PreToolUse hook for intercepting AskUserQuestion and routing via NATS."""

import logging
from typing import Any
from uuid import uuid4

from claude_agent_sdk.types import HookContext

from figaro_supervisor.context import get_client, get_task_id

logger = logging.getLogger(__name__)


async def ask_user_question_hook(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: HookContext,
) -> dict[str, Any]:
    """Intercept AskUserQuestion and route to orchestrator for human response.

    This PreToolUse hook fires BEFORE AskUserQuestion executes. It:
    1. Extracts the questions from the tool input
    2. Publishes a help request via NATS
    3. Waits for a human response (from UI or Telegram)
    4. Returns updatedInput with the answers so AskUserQuestion receives them

    This hook is used instead of can_use_tool because hooks fire regardless
    of permission_mode (bypassPermissions skips can_use_tool entirely).
    """
    tool_name = input_data.get("tool_name", "")
    if tool_name != "AskUserQuestion":
        return {}

    tool_input = input_data.get("tool_input", {})
    questions = tool_input.get("questions", [])

    client = get_client()
    task_id = get_task_id()

    if not client or not task_id:
        logger.warning("AskUserQuestion hook: no client or task_id in context")
        return {}

    request_id = str(uuid4())

    logger.info(
        f"[{task_id[:8]}] AskUserQuestion hook: {len(questions)} question(s), "
        f"request_id={request_id}"
    )

    # Publish help request and wait for response via NATS
    answers = await client.request_help(
        request_id=request_id,
        task_id=task_id,
        questions=questions,
        timeout_seconds=300,
    )

    if answers:
        logger.info(f"[{task_id[:8]}] Received human response for AskUserQuestion")
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "updatedInput": {
                    "questions": questions,
                    "answers": answers,
                },
            }
        }
    else:
        logger.warning(f"[{task_id[:8]}] Timeout waiting for human response")
        return {
            "decision": "block",
            "reason": "Timeout waiting for human response to clarifying question",
        }
