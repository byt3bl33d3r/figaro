"""Help request repository for database operations."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from figaro.db.models import HelpRequestModel, HelpRequestStatus


class HelpRequestRepository:
    """Repository for help request database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        task_id: str,
        worker_id: str,
        questions: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
        timeout_seconds: int = 1800,
        request_id: str | None = None,
        telegram_chat_id: int | None = None,
        telegram_message_id: int | None = None,
    ) -> HelpRequestModel:
        """Create a new help request.

        Args:
            task_id: The task requesting help
            worker_id: The worker requesting help
            questions: List of question objects
            context: Optional context data
            timeout_seconds: Timeout in seconds
            request_id: Optional specific request ID
            telegram_chat_id: Optional Telegram chat ID
            telegram_message_id: Optional Telegram message ID

        Returns:
            The created HelpRequestModel
        """
        model = HelpRequestModel(
            task_id=task_id,
            worker_id=worker_id,
            questions=questions,
            context=context,
            timeout_seconds=timeout_seconds,
            telegram_chat_id=telegram_chat_id,
            telegram_message_id=telegram_message_id,
        )
        if request_id:
            model.request_id = request_id

        self.session.add(model)
        await self.session.flush()
        return model

    async def get(self, request_id: str) -> HelpRequestModel | None:
        """Get a help request by ID.

        Args:
            request_id: The request ID to fetch

        Returns:
            HelpRequestModel if found, None otherwise
        """
        result = await self.session.execute(
            select(HelpRequestModel).where(HelpRequestModel.request_id == request_id)
        )
        return result.scalar_one_or_none()

    async def get_by_task(self, task_id: str) -> list[HelpRequestModel]:
        """Get all help requests for a task.

        Args:
            task_id: The task ID to fetch requests for

        Returns:
            List of HelpRequestModel instances
        """
        result = await self.session.execute(
            select(HelpRequestModel)
            .where(HelpRequestModel.task_id == task_id)
            .order_by(HelpRequestModel.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_pending(self) -> list[HelpRequestModel]:
        """Get all pending help requests.

        Returns:
            List of pending HelpRequestModel instances
        """
        result = await self.session.execute(
            select(HelpRequestModel)
            .where(HelpRequestModel.status == HelpRequestStatus.PENDING)
            .order_by(HelpRequestModel.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_recent(self, limit: int = 50) -> list[HelpRequestModel]:
        """Get recent help requests (any status).

        Returns:
            List of recent HelpRequestModel instances
        """
        result = await self.session.execute(
            select(HelpRequestModel)
            .order_by(HelpRequestModel.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def respond(
        self,
        request_id: str,
        answers: dict[str, str],
        response_source: str = "ui",
    ) -> HelpRequestModel | None:
        """Mark a help request as responded.

        Args:
            request_id: The request ID to respond to
            answers: The answers to the questions
            response_source: Source of the response (ui, telegram)

        Returns:
            Updated HelpRequestModel if successful
        """
        result = await self.session.execute(
            update(HelpRequestModel)
            .where(HelpRequestModel.request_id == request_id)
            .where(HelpRequestModel.status == HelpRequestStatus.PENDING)
            .values(
                status=HelpRequestStatus.RESPONDED,
                answers=answers,
                response_source=response_source,
                responded_at=datetime.now(timezone.utc),
            )
            .returning(HelpRequestModel)
        )
        return result.scalar_one_or_none()

    async def timeout(self, request_id: str) -> HelpRequestModel | None:
        """Mark a help request as timed out.

        Args:
            request_id: The request ID to timeout

        Returns:
            Updated HelpRequestModel if successful
        """
        result = await self.session.execute(
            update(HelpRequestModel)
            .where(HelpRequestModel.request_id == request_id)
            .where(HelpRequestModel.status == HelpRequestStatus.PENDING)
            .values(status=HelpRequestStatus.TIMEOUT)
            .returning(HelpRequestModel)
        )
        return result.scalar_one_or_none()

    async def cancel(self, request_id: str) -> HelpRequestModel | None:
        """Mark a help request as cancelled.

        Args:
            request_id: The request ID to cancel

        Returns:
            Updated HelpRequestModel if successful
        """
        result = await self.session.execute(
            update(HelpRequestModel)
            .where(HelpRequestModel.request_id == request_id)
            .where(HelpRequestModel.status == HelpRequestStatus.PENDING)
            .values(status=HelpRequestStatus.CANCELLED)
            .returning(HelpRequestModel)
        )
        return result.scalar_one_or_none()

    async def update_telegram_info(
        self,
        request_id: str,
        chat_id: int,
        message_id: int,
    ) -> HelpRequestModel | None:
        """Update Telegram message info for a help request.

        Args:
            request_id: The request ID to update
            chat_id: The Telegram chat ID
            message_id: The Telegram message ID

        Returns:
            Updated HelpRequestModel if successful
        """
        result = await self.session.execute(
            update(HelpRequestModel)
            .where(HelpRequestModel.request_id == request_id)
            .values(
                telegram_chat_id=chat_id,
                telegram_message_id=message_id,
            )
            .returning(HelpRequestModel)
        )
        return result.scalar_one_or_none()
