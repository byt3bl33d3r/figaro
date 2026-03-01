"""Help request handler for routing AskUserQuestion to orchestrator."""

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from figaro_supervisor.supervisor.client import SupervisorNatsClient

logger = logging.getLogger(__name__)


class HelpRequestHandler:
    """Handles AskUserQuestion routing to orchestrator for human responses.

    When Claude calls AskUserQuestion, this handler:
    1. Sends the questions via NATS publish
    2. The orchestrator routes to UI and available channels
    3. Waits for the first response from either channel
    4. Returns the answers to Claude

    Uses the SupervisorNatsClient.request_help() method which does
    the request/reply pattern with NATS subscriptions.
    """

    def __init__(self, client: "SupervisorNatsClient") -> None:
        """Initialize the help request handler.

        Args:
            client: SupervisorNatsClient for NATS communication
        """
        self._client = client

    async def request_help(
        self,
        task_id: str,
        questions: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
        timeout_seconds: int = 300,
    ) -> dict[str, str] | None:
        """Request human help and wait for a response.

        Args:
            task_id: The ID of the current task
            questions: List of questions in AskUserQuestion format:
                       [{"question": "...", "header": "...", "options": [...], "multiSelect": bool}]
            context: Optional context to include with the request
            timeout_seconds: How long to wait for a response (default 5 min)

        Returns:
            A dict mapping question text to answers, or None if timeout/error
        """
        from uuid import uuid4

        request_id = str(uuid4())

        logger.info(
            f"Sending help request {request_id} for task {task_id}, "
            f"waiting for response (timeout={timeout_seconds}s)..."
        )

        result = await self._client.request_help(
            request_id=request_id,
            task_id=task_id,
            questions=questions,
            timeout_seconds=timeout_seconds,
        )

        if result is not None:
            logger.info(f"Received response for help request {request_id}")
        else:
            logger.warning(
                f"Help request {request_id} timed out after {timeout_seconds}s"
            )

        return result
