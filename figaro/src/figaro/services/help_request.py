"""Help request management for human-in-the-loop assistance."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker

from figaro.db.repositories.help_requests import HelpRequestRepository

if TYPE_CHECKING:
    from figaro.services.nats_service import NatsService

logger = logging.getLogger(__name__)


class HelpRequestStatus(str, Enum):
    PENDING = "pending"
    RESPONDED = "responded"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class HelpRequest:
    """Tracks a pending help request from a worker."""

    request_id: str
    worker_id: str
    task_id: str
    questions: list[dict[str, Any]]
    created_at: datetime
    timeout_seconds: int
    channel: str | None = None
    channel_message_id: int | None = None
    channel_chat_id: int | None = None
    answers: dict[str, str] | None = None
    status: HelpRequestStatus = HelpRequestStatus.PENDING
    responded_at: datetime | None = None
    response_source: str | None = None


class HelpRequestManager:
    """Manages help requests and routes responses to workers."""

    def __init__(
        self,
        default_timeout: int = 1800,
        session_factory: async_sessionmaker | None = None,
    ) -> None:
        self._default_timeout = default_timeout
        self._session_factory = session_factory
        self._nats_service: "NatsService | None" = None
        self._requests: dict[str, HelpRequest] = {}
        self._channel_message_map: dict[
            tuple[int, int], str
        ] = {}  # (chat_id, msg_id) -> request_id
        self._timeout_tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    def set_nats_service(self, nats_service: "NatsService") -> None:
        """Set the NATS service for publishing responses."""
        self._nats_service = nats_service

    async def load_pending_requests(self) -> None:
        """Load help requests from the database on startup.

        Loads all recent requests so the UI can show notification history,
        and restarts timeout timers for pending ones.
        """
        if not self._session_factory:
            return

        try:
            async with self._session_factory() as session:
                repo = HelpRequestRepository(session)
                recent = await repo.list_recent(limit=50)

                pending_count = 0
                for model in recent:
                    status = HelpRequestStatus(model.status.value)
                    request = HelpRequest(
                        request_id=model.request_id,
                        worker_id=model.worker_id,
                        task_id=model.task_id,
                        questions=model.questions,
                        created_at=model.created_at,
                        timeout_seconds=model.timeout_seconds,
                        channel_chat_id=model.telegram_chat_id,
                        channel_message_id=model.telegram_message_id,
                        status=status,
                    )
                    self._requests[request.request_id] = request

                    # Only process pending requests for timeouts and channel maps
                    if status == HelpRequestStatus.PENDING:
                        pending_count += 1

                        # Rebuild channel message map
                        if model.telegram_chat_id and model.telegram_message_id:
                            self._channel_message_map[
                                (model.telegram_chat_id, model.telegram_message_id)
                            ] = request.request_id

                        # Restart timeout with remaining time
                        elapsed = (
                            datetime.now(timezone.utc) - model.created_at
                        ).total_seconds()
                        remaining = max(0, model.timeout_seconds - elapsed)
                        if remaining > 0:
                            self._timeout_tasks[request.request_id] = asyncio.create_task(
                                self._handle_timeout(request.request_id, int(remaining))
                            )
                        else:
                            # Already expired, timeout immediately
                            self._timeout_tasks[request.request_id] = asyncio.create_task(
                                self._handle_timeout(request.request_id, 0)
                            )

                logger.info(
                    f"Loaded {len(recent)} help requests from database "
                    f"({pending_count} pending)"
                )
        except Exception as e:
            logger.error(f"Failed to load help requests: {e}")

    async def _persist_create(self, request: HelpRequest) -> None:
        """Persist a new help request to the database."""
        if not self._session_factory:
            return
        try:
            async with self._session_factory() as session:
                repo = HelpRequestRepository(session)
                await repo.create(
                    request_id=request.request_id,
                    task_id=request.task_id,
                    worker_id=request.worker_id,
                    questions=request.questions,
                    timeout_seconds=request.timeout_seconds,
                )
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to persist help request {request.request_id}: {e}")

    async def _persist_status(
        self, request_id: str, status: HelpRequestStatus, **kwargs: Any
    ) -> None:
        """Update help request status in the database."""
        if not self._session_factory:
            return
        try:
            async with self._session_factory() as session:
                repo = HelpRequestRepository(session)
                if status == HelpRequestStatus.RESPONDED:
                    await repo.respond(
                        request_id,
                        answers=kwargs.get("answers", {}),
                        response_source=kwargs.get("source", "ui"),
                    )
                elif status == HelpRequestStatus.TIMEOUT:
                    await repo.timeout(request_id)
                elif status == HelpRequestStatus.CANCELLED:
                    await repo.cancel(request_id)
                await session.commit()
        except Exception as e:
            logger.error(
                f"Failed to persist help request {request_id} status {status}: {e}"
            )

    async def create_request(
        self,
        worker_id: str,
        task_id: str,
        questions: list[dict[str, Any]],
        timeout_seconds: int | None = None,
        request_id: str | None = None,
    ) -> HelpRequest:
        """Create a new help request and start timeout timer."""
        request_id = request_id or str(uuid4())
        timeout = timeout_seconds or self._default_timeout

        request = HelpRequest(
            request_id=request_id,
            worker_id=worker_id,
            task_id=task_id,
            questions=questions,
            created_at=datetime.now(timezone.utc),
            timeout_seconds=timeout,
        )

        async with self._lock:
            self._requests[request_id] = request
            # Start timeout task
            self._timeout_tasks[request_id] = asyncio.create_task(
                self._handle_timeout(request_id, timeout)
            )

        await self._persist_create(request)

        logger.info(
            f"Created help request {request_id} for worker {worker_id}, task {task_id}"
        )
        return request

    async def set_channel_message_id(
        self,
        request_id: str,
        chat_id: int,
        message_id: int,
    ) -> None:
        """Associate a channel message with a help request for reply tracking."""
        async with self._lock:
            if request_id in self._requests:
                self._requests[request_id].channel_message_id = message_id
                self._requests[request_id].channel_chat_id = chat_id
                self._channel_message_map[(chat_id, message_id)] = request_id
                logger.debug(
                    f"Linked channel message {message_id} to request {request_id}"
                )

    async def get_by_channel_message_id(
        self,
        chat_id: int,
        message_id: int,
    ) -> HelpRequest | None:
        """Look up a help request by its channel message ID."""
        async with self._lock:
            request_id = self._channel_message_map.get((chat_id, message_id))
            if request_id:
                return self._requests.get(request_id)
            return None

    async def get_request(self, request_id: str) -> HelpRequest | None:
        """Get a help request by ID."""
        async with self._lock:
            return self._requests.get(request_id)

    async def get_pending_requests(self) -> list[HelpRequest]:
        """Get all pending help requests."""
        async with self._lock:
            return [
                req
                for req in self._requests.values()
                if req.status == HelpRequestStatus.PENDING
            ]

    async def get_all_requests(self) -> list[HelpRequest]:
        """Get all help requests (any status)."""
        async with self._lock:
            return list(self._requests.values())

    async def get_pending_by_worker(self, worker_id: str) -> list[HelpRequest]:
        """Get all pending requests for a specific worker."""
        async with self._lock:
            return [
                req
                for req in self._requests.values()
                if req.worker_id == worker_id
                and req.status == HelpRequestStatus.PENDING
            ]

    async def respond(
        self,
        request_id: str,
        answers: dict[str, str],
        source: str = "telegram",
    ) -> bool:
        """
        Process a response to a help request.

        Publishes the response via NATS to the worker.
        Returns True if successful, False if request not found or already responded.
        """
        async with self._lock:
            request = self._requests.get(request_id)
            if not request:
                logger.warning(f"Help request {request_id} not found")
                return False

            if request.status != HelpRequestStatus.PENDING:
                logger.warning(
                    f"Help request {request_id} already {request.status.value}"
                )
                return False

            # Update request state
            request.answers = answers
            request.status = HelpRequestStatus.RESPONDED
            request.responded_at = datetime.now(timezone.utc)
            request.response_source = source

            # Cancel timeout task
            if request_id in self._timeout_tasks:
                self._timeout_tasks[request_id].cancel()
                del self._timeout_tasks[request_id]

        await self._persist_status(
            request_id, HelpRequestStatus.RESPONDED, answers=answers, source=source
        )

        # Publish response via NATS (outside lock)
        if self._nats_service:
            try:
                await self._nats_service.publish_help_response(
                    request_id=request_id,
                    task_id=request.task_id,
                    worker_id=request.worker_id,
                    answers=answers,
                    source=source,
                )
                logger.info(f"Published help response for {request_id}")
            except Exception as e:
                logger.error(f"Failed to publish help response for {request_id}: {e}")
                return False
        else:
            logger.warning(
                f"No NatsService set, cannot publish help response for {request_id}"
            )

        # Broadcast to UI via NATS
        if self._nats_service:
            await self._nats_service.conn.publish(
                "figaro.broadcast.help_request_responded",
                {
                    "request_id": request_id,
                    "worker_id": request.worker_id,
                    "task_id": request.task_id,
                    "source": source,
                    "answers": answers,
                    "questions": request.questions,
                },
            )

        return True

    async def cancel_request(self, request_id: str) -> bool:
        """Cancel a pending request (e.g., task completed/failed)."""
        async with self._lock:
            request = self._requests.get(request_id)
            if not request:
                return False

            if request.status != HelpRequestStatus.PENDING:
                return False

            request.status = HelpRequestStatus.CANCELLED

            # Cancel timeout task
            if request_id in self._timeout_tasks:
                self._timeout_tasks[request_id].cancel()
                del self._timeout_tasks[request_id]

            # Clean up channel mapping
            if request.channel_chat_id and request.channel_message_id:
                self._channel_message_map.pop(
                    (request.channel_chat_id, request.channel_message_id), None
                )

        await self._persist_status(request_id, HelpRequestStatus.CANCELLED)

        logger.info(f"Cancelled help request {request_id}")
        return True

    async def dismiss_request(
        self,
        request_id: str,
        source: str = "ui",
        notify_worker: bool = True,
    ) -> bool:
        """
        Dismiss a pending help request from UI or other source.

        Unlike cancel_request, this also:
        - Notifies the worker with an error response via NATS
        - Broadcasts dismissal to UI

        Returns True if successful, False if request not found or not pending.
        """
        async with self._lock:
            request = self._requests.get(request_id)
            if not request:
                return False

            if request.status != HelpRequestStatus.PENDING:
                return False

            request.status = HelpRequestStatus.CANCELLED

            # Cancel timeout task
            if request_id in self._timeout_tasks:
                self._timeout_tasks[request_id].cancel()
                del self._timeout_tasks[request_id]

            # Clean up channel mapping
            if request.channel_chat_id and request.channel_message_id:
                self._channel_message_map.pop(
                    (request.channel_chat_id, request.channel_message_id), None
                )

        await self._persist_status(request_id, HelpRequestStatus.CANCELLED)

        # Send dismissal notification to worker via NATS (outside lock)
        if notify_worker and self._nats_service:
            await self._nats_service.publish_help_response(
                request_id=request_id,
                task_id=request.task_id,
                worker_id=request.worker_id,
                error="dismissed",
            )

        # Broadcast to UI via NATS
        if self._nats_service:
            await self._nats_service.conn.publish(
                "figaro.broadcast.help_request_dismissed",
                {
                    "request_id": request_id,
                    "worker_id": request.worker_id,
                    "task_id": request.task_id,
                    "source": source,
                },
            )

        logger.info(f"Dismissed help request {request_id} from {source}")
        return True

    async def cancel_requests_for_worker(self, worker_id: str) -> int:
        """Cancel all pending requests for a worker (e.g., worker disconnected)."""
        pending = await self.get_pending_by_worker(worker_id)
        cancelled = 0
        for request in pending:
            if await self.cancel_request(request.request_id):
                cancelled += 1
        return cancelled

    async def _handle_timeout(self, request_id: str, timeout_seconds: int) -> None:
        """Handle timeout for a help request."""
        try:
            await asyncio.sleep(timeout_seconds)
        except asyncio.CancelledError:
            return

        async with self._lock:
            request = self._requests.get(request_id)
            if not request or request.status != HelpRequestStatus.PENDING:
                return

            request.status = HelpRequestStatus.TIMEOUT

            # Clean up timeout task reference
            self._timeout_tasks.pop(request_id, None)

            # Clean up channel mapping
            if request.channel_chat_id and request.channel_message_id:
                self._channel_message_map.pop(
                    (request.channel_chat_id, request.channel_message_id), None
                )

        await self._persist_status(request_id, HelpRequestStatus.TIMEOUT)

        # Publish timeout notification to worker via NATS (outside lock)
        if self._nats_service:
            await self._nats_service.publish_help_response(
                request_id=request_id,
                task_id=request.task_id,
                worker_id=request.worker_id,
                error="timeout",
            )

        # Broadcast to UI via NATS
        if self._nats_service:
            await self._nats_service.conn.publish(
                "figaro.broadcast.help_request_timeout",
                {
                    "request_id": request_id,
                    "worker_id": request.worker_id,
                    "task_id": request.task_id,
                },
            )

        logger.info(f"Help request {request_id} timed out after {timeout_seconds}s")
