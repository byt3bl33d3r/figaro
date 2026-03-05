"""Worker-side help request handler for human-in-the-loop assistance."""

import asyncio
import logging
from typing import Any
from uuid import uuid4

from figaro_nats import Subjects

from .client import NatsClient

logger = logging.getLogger(__name__)


class HelpRequestHandler:
    """
    Handles help requests from the worker to the orchestrator.

    Subscribes per-request to the specific Core NATS response subject
    (figaro.help.{request_id}.response) for reliable delivery. JetStream
    publish also delivers to Core NATS subscribers, so this works with
    the orchestrator's js_publish without needing a JetStream consumer.
    """

    def __init__(self, client: NatsClient) -> None:
        self._client = client
        self._pending_futures: dict[str, asyncio.Future[dict[str, str] | None]] = {}

    async def request_help(
        self,
        task_id: str,
        questions: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
        timeout_seconds: int = 1800,
    ) -> dict[str, str] | None:
        """
        Request human help and wait for a response.

        Subscribes to the specific response subject via Core NATS before
        sending the request, ensuring no race conditions with delivery.

        Args:
            task_id: The ID of the current task
            questions: List of questions in AskUserQuestion format
            context: Optional context to include with the request
            timeout_seconds: How long to wait for a response (default 30 min)

        Returns:
            A dict mapping question text to answers, or None if timeout/error
        """
        request_id = str(uuid4())

        response_event = asyncio.Event()
        response_data: dict[str, Any] = {}

        async def _on_response(data: dict[str, Any]) -> None:
            if data.get("request_id") == request_id:
                response_data.update(data)
                response_event.set()

        # Subscribe to the specific response subject BEFORE sending the request
        sub = await self._client.conn.subscribe(
            Subjects.help_response(request_id),
            _on_response,
        )

        try:
            # Send the help request via NATS
            await self._client.publish_help_request(
                request_id=request_id,
                task_id=task_id,
                questions=questions,
                timeout_seconds=timeout_seconds,
            )

            logger.info(f"Sent help request {request_id} for task {task_id}, waiting for response...")

            try:
                await asyncio.wait_for(response_event.wait(), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                logger.warning(f"Help request {request_id} timed out after {timeout_seconds}s")
                return None
            except asyncio.CancelledError:
                logger.info(f"Help request {request_id} was cancelled")
                return None

            # Check for errors
            error = response_data.get("error")
            if error:
                logger.warning(f"Help request {request_id} failed: {error}")
                return None

            answers = response_data.get("answers")
            logger.info(f"Received response for help request {request_id}")
            return answers
        finally:
            await sub.unsubscribe()

    def cancel_pending_requests(self) -> int:
        """Cancel all pending help requests. Returns count of cancelled requests."""
        # No-op: subscriptions are cleaned up in request_help's finally block
        return 0
