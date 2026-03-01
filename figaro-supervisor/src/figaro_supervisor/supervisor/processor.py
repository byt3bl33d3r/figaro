"""Task processor using ClaudeSDKClient for streaming, hooks, and in-process MCP tools."""

import asyncio
import dataclasses
import functools
import logging
from typing import TYPE_CHECKING, Any, cast

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    HookMatcher,
)
from claude_agent_sdk.types import (
    HookCallback,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    ToolPermissionContext,
)

from figaro_supervisor.context import (
    SupervisorContext,
    set_context,
    update_task_context,
)
from figaro_supervisor.hooks import (
    pre_tool_use_hook,
    post_tool_use_hook,
    stop_hook,
)

from .help_request import HelpRequestHandler
from .tools import create_tools_server

if TYPE_CHECKING:
    from figaro_supervisor.supervisor.client import SupervisorNatsClient

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class TaskSession:
    """Encapsulates state for a single task being processed.

    Each task gets its own session with isolated state, allowing
    concurrent task processing with independent Claude SDK clients.
    """

    task_id: str
    prompt: str
    options: dict[str, Any] = dataclasses.field(default_factory=dict)
    source_metadata: dict[str, Any] | None = None
    asyncio_task: asyncio.Task[None] | None = None  # The running task

SUPERVISOR_SYSTEM_PROMPT = """You are a task supervisor for the Figaro orchestration system. Your role is to:

1. **Analyze** incoming task requests from users
2. **Clarify** if the request is ambiguous by asking questions via the AskUserQuestion tool
3. **Optimize** the task prompt with specific, actionable instructions
4. **Delegate** the optimized task to an available worker

## Available Tools

### Worker Management
- `delegate_to_worker` - Delegate an optimized task to a worker
  - Parameters:
    - `prompt` (required): The optimized task prompt for the worker
    - `worker_id` (optional): Specific worker to use, or leave empty for auto-assignment
  - This tool BLOCKS until the worker completes and returns the full result
- `list_workers` - Get list of connected workers and their status, including desktop credentials (vnc_username, vnc_password)

### Task Queries
- `list_tasks` - Get tasks by status (pending, assigned, completed, failed)
- `get_task` - Get a specific task by ID (including full result and messages)
- `search_tasks` - Search tasks by prompt content

### User Communication
- `AskUserQuestion` - Ask the user clarifying questions (built-in tool)

### VNC Tools (Direct Desktop Interaction)
- `take_screenshot(worker_id)` — Takes a screenshot of a worker's desktop (returns image)
- `send_screenshot(worker_id)` — Takes a screenshot of the worker's desktop and sends it to the requesting user's messaging channel (only available for tasks from messaging channels like Telegram)
- `type_text(worker_id, text)` — Types text on a worker's desktop keyboard
- `press_key(worker_id, key, modifiers=[])` — Presses a key combination on a worker's desktop
- `click(worker_id, x, y, button="left")` — Clicks at coordinates on a worker's desktop

### Scheduled Task Management
- `list_scheduled_tasks` - Get all scheduled tasks
- `get_scheduled_task` - Get scheduled task details
- `create_scheduled_task` - Create a scheduled task with cron expression
- `update_scheduled_task` - Update a scheduled task
- `delete_scheduled_task` - Delete a scheduled task
- `toggle_scheduled_task` - Toggle enabled/disabled state

## Workflow

1. When you receive a task, first analyze what the user wants
2. If unclear, use AskUserQuestion to get clarification (be specific about what you need)
3. Once clear, optimize the prompt:
   - Add specific steps if helpful
   - Include any context gathered from clarification
   - Specify start URL if known
4. Delegate to a worker using `delegate_to_worker`
5. Review the worker's result and summarize it for the user

## Important Notes

- Workers perform browser automation tasks
- Always provide clear, actionable instructions when delegating
- `delegate_to_worker` blocks until the worker finishes - you will receive the full result
- If a task doesn't require browser automation, handle it yourself if possible
- For scheduled tasks, you can update prompts based on learnings from past executions
- Workers may have desktop credentials (vnc_username, vnc_password) available via `list_workers`. If you encounter a lock screen on a worker's desktop, use these credentials with the VNC tools to unlock it (e.g. type the password using `type_text` and press Enter using `press_key`)
- Workers may have `patchright-cli` installed for browser automation. When delegating tasks that involve navigating to specific websites and searching for or extracting information, include instructions to use `patchright-cli` for browser automation if the skill is available (key commands: `patchright-cli open <url>`, `patchright-cli snapshot`, `patchright-cli click`, `patchright-cli fill`, `patchright-cli type`, `patchright-cli press`)
- Instruct workers to refresh or redo searches if the browser page already shows stale results from a previous task
"""


def serialize_message(msg: Any) -> dict[str, Any]:
    """Serialize a claude-agent-sdk message to a dict for transmission."""
    if dataclasses.is_dataclass(msg) and not isinstance(msg, type):
        result = dataclasses.asdict(msg)
        result["__type__"] = type(msg).__name__
        return result
    elif isinstance(msg, dict):
        return msg
    else:
        return {"value": str(msg), "__type__": type(msg).__name__}


class TaskProcessor:
    """Processes tasks using ClaudeSDKClient with in-process MCP tools.

    This processor uses the Claude Agent SDK's ClaudeSDKClient for:
    - In-process MCP tools backed by NATS request/reply
    - Hooks for logging and audit (PreToolUse, PostToolUse, Stop)
    - can_use_tool callback for AskUserQuestion interception
    - Session continuity and interrupt support
    """

    def __init__(
        self,
        client: "SupervisorNatsClient",
        model: str = "claude-opus-4-6",
        max_turns: int | None = None,
    ) -> None:
        """Initialize the task processor.

        Args:
            client: SupervisorNatsClient for NATS communication
            model: Claude model to use
            max_turns: Maximum conversation turns (optional)
        """
        self.client = client
        self.model = model
        self.max_turns = max_turns

        # Track active sessions by task_id (for concurrent task processing)
        self._sessions: dict[str, TaskSession] = {}

        # Initialize context for hooks
        ctx = SupervisorContext(
            client=client,
        )
        set_context(ctx)

        # Help request handler for AskUserQuestion routing
        self.help_handler = HelpRequestHandler(client)

    async def handle_task(self, payload: dict[str, Any]) -> None:
        """Handle incoming task from orchestrator (via UI).

        Spawns a new concurrent session for the task, allowing multiple
        tasks to be processed simultaneously.

        Args:
            payload: Task payload with task_id, prompt, options
        """
        task_id = payload.get("task_id")
        prompt = payload.get("prompt", "")
        options_dict = payload.get("options", {})
        source_metadata = payload.get("source_metadata")

        if not task_id:
            logger.error("Received task without task_id")
            return

        logger.info(f"Processing task {task_id}: {prompt[:50]}...")

        # Create session for this task
        session = TaskSession(
            task_id=task_id,
            prompt=prompt,
            options=options_dict,
            source_metadata=source_metadata,
        )
        self._sessions[task_id] = session

        # Spawn as concurrent task (don't await - allows parallel processing)
        session.asyncio_task = asyncio.create_task(
            self._run_session(session),
            name=f"supervisor-session-{task_id[:8]}",
        )

    def _format_supervisor_prompt(
        self,
        user_prompt: str,
        options: dict[str, Any],
        source_metadata: dict[str, Any] | None = None,
    ) -> str:
        """Format the prompt with supervisor instructions and context.

        Args:
            user_prompt: The raw user request
            options: Task options including source, etc.
            source_metadata: Optional metadata about the task source (e.g. channel info)

        Returns:
            Formatted prompt with context XML tags
        """
        source = options.get("source", "unknown")
        context_parts = [
            f"Source: {source}",
            f"Supervisor ID: {self.client.supervisor_id}",
        ]

        # Add channel context for gateway-sourced tasks
        channel = source_metadata.get("channel") if source_metadata else None
        if channel:
            context_parts.append(f"Channel: {channel}")

        context = "\n".join(context_parts)

        # Optimization and healer tasks already contain full instructions
        if source in ("optimizer", "healer"):
            return f"""<task_context>
{context}
</task_context>

{user_prompt}"""

        # Build gateway-specific instructions when task comes from a messaging channel
        channel_instructions = ""
        if channel:
            channel_instructions = (
                "\n\nThis task was received from a messaging channel. "
                "You can use send_screenshot to send screenshots directly to the user."
            )

        return f"""<task_context>
{context}
</task_context>

<user_request>
{user_prompt}
</user_request>

Analyze this request and either:
1. Ask clarifying questions if needed (use AskUserQuestion tool)
2. Delegate to a worker with an optimized prompt (use delegate_to_worker)
3. Handle it directly if it doesn't require browser automation{channel_instructions}"""

    async def _can_use_tool_for_session(
        self,
        session: TaskSession,
        tool_name: str,
        input_data: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:
        """Handle tool permission requests with session context."""
        if tool_name == "AskUserQuestion":
            questions = input_data.get("questions", [])
            logger.info(
                f"[{session.task_id[:8]}] Intercepted AskUserQuestion with "
                f"{len(questions)} question(s)"
            )
            answers = await self.help_handler.request_help(
                task_id=session.task_id,
                questions=questions,
                timeout_seconds=300,
            )
            if answers:
                logger.info(f"[{session.task_id[:8]}] Received human response")
                return PermissionResultAllow(
                    updated_input={"questions": questions, "answers": answers}
                )
            else:
                logger.warning(f"[{session.task_id[:8]}] Timeout waiting for response")
                return PermissionResultDeny(
                    message="Timeout waiting for human response to clarifying question"
                )
        return PermissionResultAllow(updated_input=input_data)

    async def _run_session(self, session: TaskSession) -> None:
        """Run a single task session with its own ClaudeSDKClient.

        Each session runs in its own asyncio.Task, allowing concurrent
        task processing. The session has isolated state and its own
        SDK client instance.

        Args:
            session: The TaskSession to run
        """
        task_id = session.task_id
        logger.info(f"[{task_id[:8]}] Starting session")

        try:
            # Update context with task-specific information for hooks
            update_task_context(self.client, task_id)

            # Notify we're busy
            await self.client.send_status("busy")

            # Format the prompt with supervisor instructions
            formatted_prompt = self._format_supervisor_prompt(
                session.prompt, session.options, source_metadata=session.source_metadata
            )

            # Create a fresh MCP server per session to avoid lifecycle
            # issues when ClaudeSDKClient cleanup corrupts shared state
            tools_server = create_tools_server(
                self.client, source_metadata=session.source_metadata
            )

            # Build options with remote MCP server, hooks, and can_use_tool
            options = ClaudeAgentOptions(
                permission_mode=session.options.get(
                    "permission_mode", "bypassPermissions"
                ),
                max_turns=session.options.get("max_turns", self.max_turns),
                system_prompt=SUPERVISOR_SYSTEM_PROMPT,
                model=self.model,
                mcp_servers={"orchestrator": tools_server},
                # can_use_tool handles AskUserQuestion routing to humans
                # via NATS and auto-approves all other tools.
                can_use_tool=functools.partial(self._can_use_tool_for_session, session),
                # Hooks for logging/audit (NOT AskUserQuestion — that's via can_use_tool).
                # The keepalive hook is required to keep the stream open for can_use_tool.
                hooks={
                    "PreToolUse": [
                        HookMatcher(hooks=[cast(HookCallback, pre_tool_use_hook)]),
                    ],
                    "PostToolUse": [
                        HookMatcher(hooks=[cast(HookCallback, post_tool_use_hook)])
                    ],
                    "Stop": [HookMatcher(hooks=[cast(HookCallback, stop_hook)])],
                },
            )

            result_message = None

            # Use ClaudeSDKClient for streaming, hooks, and custom MCP tools
            async with ClaudeSDKClient(options=options) as sdk_client:
                # Send the formatted prompt
                await sdk_client.query(formatted_prompt)

                # Stream all messages back to orchestrator for UI
                async for message in sdk_client.receive_response():
                    msg_type = type(message).__name__
                    logger.debug(f"[{task_id[:8]}] Received message type: {msg_type}")

                    serialized = serialize_message(message)
                    serialized["task_id"] = task_id

                    # Send to orchestrator via NATS for UI streaming
                    try:
                        await self.client.publish_task_message(task_id, serialized)
                    except Exception as e:
                        logger.warning(
                            f"[{task_id[:8]}] Failed to publish message: {e}"
                        )

                    # Capture the final result message
                    if isinstance(message, ResultMessage):
                        result_message = serialized
                        logger.debug(f"[{task_id[:8]}] Captured result message")

            logger.debug(f"[{task_id[:8]}] SDK client context exited")

            # Send task completion notification via JetStream
            await self.client.publish_task_complete(task_id, result_message)
            logger.info(f"[{task_id[:8]}] Session completed successfully")

        except Exception as e:
            logger.exception(f"[{task_id[:8]}] Session failed: {e}")
            await self.client.publish_task_error(task_id, str(e))
        finally:
            # Cleanup session
            self._sessions.pop(task_id, None)
            # Notify we're idle if no more sessions
            if not self._sessions:
                await self.client.send_status("idle")
            logger.debug(f"[{task_id[:8]}] Session cleaned up")
