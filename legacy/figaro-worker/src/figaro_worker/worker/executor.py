import dataclasses
import logging
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from claude_agent_sdk._errors import MessageParseError
from claude_agent_sdk.types import (
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    ToolPermissionContext,
)

from .client import NatsClient
from .help_request import HelpRequestHandler
from .prompt_formatter import format_task_prompt
from .tools import create_desktop_tools_server

logger = logging.getLogger(__name__)

def serialize_message(msg: Any) -> dict[str, Any]:
    """Serialize a claude-agent-sdk message to a dict."""
    if dataclasses.is_dataclass(msg) and not isinstance(msg, type):
        result = dataclasses.asdict(msg)
        result["__type__"] = type(msg).__name__
        return result
    elif isinstance(msg, dict):
        return msg
    else:
        return {"value": str(msg), "__type__": type(msg).__name__}


class TaskExecutor:
    def __init__(self, client: NatsClient, model: str = "claude-opus-4-6") -> None:
        self.client = client
        self.model = model
        self.help_handler = HelpRequestHandler(client)
        self._current_task_id: str | None = None

    async def handle_task(self, payload: dict[str, Any]) -> None:
        task_id = payload.get("task_id")
        prompt = payload.get("prompt", "")
        options_dict = payload.get("options", {})

        if not task_id:
            logger.error("Received task without task_id")
            return

        logger.info(f"Executing task {task_id}: {prompt[:50]}...")

        # Note: Status is managed by the orchestrator. It sets BUSY when claiming
        # a worker for a task, and sets IDLE when task_complete/error is received.
        # We don't send status messages here to avoid race conditions.

        try:
            await self._execute_task(task_id, prompt, options_dict)
        except Exception as e:
            logger.exception(f"Task {task_id} failed: {e}")
            await self.client.publish_task_error(task_id, str(e))
        finally:
            self._current_task_id = None

    async def _can_use_tool(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:
        """Handle tool permission requests.

        Intercepts AskUserQuestion to route questions to humans via NATS
        (UI/Telegram). All other tools are auto-approved.

        See: https://platform.claude.com/docs/en/agent-sdk/user-input
        """
        if tool_name != "AskUserQuestion":
            return PermissionResultAllow(updated_input=input_data)

        questions = input_data.get("questions", [])

        if not self._current_task_id:
            logger.warning("AskUserQuestion: no current task ID")
            return PermissionResultDeny(message="No active task context")

        logger.info(f"AskUserQuestion: {len(questions)} question(s)")

        # Request human help via orchestrator (Telegram/UI)
        answers = await self.help_handler.request_help(
            task_id=self._current_task_id,
            questions=questions,
            timeout_seconds=1800,  # 30 minute timeout
        )

        if answers:
            logger.info("Received human response for AskUserQuestion")
            return PermissionResultAllow(
                updated_input={
                    "questions": questions,
                    "answers": answers,
                }
            )
        else:
            logger.warning("Timeout or error waiting for human response")
            return PermissionResultDeny(
                message="Timeout waiting for human response. Proceed with your best judgment."
            )

    async def _execute_task(
        self,
        task_id: str,
        prompt: str,
        options_dict: dict[str, Any],
    ) -> None:
        # Track current task for AskUserQuestion handling
        self._current_task_id = task_id

        # Format the prompt with XML structure and clarification instructions
        start_url = options_dict.get("start_url")
        formatted_prompt = format_task_prompt(prompt, start_url)

        logger.debug(f"Formatted prompt for task {task_id}")

        desktop_tools = create_desktop_tools_server()

        options = ClaudeAgentOptions(
            permission_mode=options_dict.get("permission_mode", "bypassPermissions"),
            max_turns=options_dict.get("max_turns"),
            model=self.model,
            setting_sources=["user", "project"],
            can_use_tool=self._can_use_tool,
            mcp_servers={"desktop": desktop_tools},
        )

        result_message = None

        try:
            async with ClaudeSDKClient(options) as client:
                await client.query(formatted_prompt)

                async for message in client.receive_response():
                    serialized = serialize_message(message)
                    serialized["task_id"] = task_id

                    await self.client.publish_task_message(task_id, serialized)

                    if isinstance(message, ResultMessage):
                        result_message = serialized
        except MessageParseError as e:
            logger.warning(f"SDK message parse error during task {task_id} (completing with partial results): {e}")

        await self.client.publish_task_complete(task_id, result_message)
        logger.info(f"Task {task_id} completed")
