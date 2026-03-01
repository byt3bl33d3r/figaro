"""Worker session repository for database operations."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from figaro.db.models import WorkerSessionModel


class WorkerSessionRepository:
    """Repository for worker session database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        worker_id: str,
        capabilities: list[str] | None = None,
        novnc_url: str | None = None,
    ) -> WorkerSessionModel:
        """Create a new worker session record.

        Args:
            worker_id: The worker ID
            capabilities: List of worker capabilities
            novnc_url: Optional noVNC URL

        Returns:
            The created WorkerSessionModel
        """
        model = WorkerSessionModel(
            worker_id=worker_id,
            capabilities=capabilities or [],
            novnc_url=novnc_url,
        )
        self.session.add(model)
        await self.session.flush()
        return model

    async def get_active(self, worker_id: str) -> WorkerSessionModel | None:
        """Get the active session for a worker.

        Args:
            worker_id: The worker ID to fetch

        Returns:
            Active WorkerSessionModel if found, None otherwise
        """
        result = await self.session.execute(
            select(WorkerSessionModel)
            .where(WorkerSessionModel.worker_id == worker_id)
            .where(WorkerSessionModel.disconnected_at.is_(None))
            .order_by(WorkerSessionModel.connected_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_active(self) -> list[WorkerSessionModel]:
        """Get all active worker sessions.

        Returns:
            List of active WorkerSessionModel instances
        """
        result = await self.session.execute(
            select(WorkerSessionModel)
            .where(WorkerSessionModel.disconnected_at.is_(None))
            .order_by(WorkerSessionModel.connected_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_worker(
        self,
        worker_id: str,
        limit: int = 10,
    ) -> list[WorkerSessionModel]:
        """Get recent sessions for a worker.

        Args:
            worker_id: The worker ID to fetch sessions for
            limit: Maximum number of sessions to return

        Returns:
            List of WorkerSessionModel instances
        """
        result = await self.session.execute(
            select(WorkerSessionModel)
            .where(WorkerSessionModel.worker_id == worker_id)
            .order_by(WorkerSessionModel.connected_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def disconnect(
        self,
        worker_id: str,
        reason: str | None = None,
    ) -> WorkerSessionModel | None:
        """Mark a worker session as disconnected.

        Args:
            worker_id: The worker ID to disconnect
            reason: Optional disconnect reason

        Returns:
            Updated WorkerSessionModel if successful
        """
        # Find the active session
        active_session = await self.get_active(worker_id)
        if not active_session:
            return None

        result = await self.session.execute(
            update(WorkerSessionModel)
            .where(WorkerSessionModel.session_id == active_session.session_id)
            .values(
                disconnected_at=datetime.now(timezone.utc),
                disconnect_reason=reason,
            )
            .returning(WorkerSessionModel)
        )
        return result.scalar_one_or_none()

    async def increment_completed(self, worker_id: str) -> WorkerSessionModel | None:
        """Increment the completed task count for a worker session.

        Args:
            worker_id: The worker ID

        Returns:
            Updated WorkerSessionModel if successful
        """
        active_session = await self.get_active(worker_id)
        if not active_session:
            return None

        result = await self.session.execute(
            update(WorkerSessionModel)
            .where(WorkerSessionModel.session_id == active_session.session_id)
            .values(tasks_completed=WorkerSessionModel.tasks_completed + 1)
            .returning(WorkerSessionModel)
        )
        return result.scalar_one_or_none()

    async def increment_failed(self, worker_id: str) -> WorkerSessionModel | None:
        """Increment the failed task count for a worker session.

        Args:
            worker_id: The worker ID

        Returns:
            Updated WorkerSessionModel if successful
        """
        active_session = await self.get_active(worker_id)
        if not active_session:
            return None

        result = await self.session.execute(
            update(WorkerSessionModel)
            .where(WorkerSessionModel.session_id == active_session.session_id)
            .values(tasks_failed=WorkerSessionModel.tasks_failed + 1)
            .returning(WorkerSessionModel)
        )
        return result.scalar_one_or_none()

    async def get_stats(self, worker_id: str) -> dict[str, Any]:
        """Get aggregate stats for a worker.

        Args:
            worker_id: The worker ID to get stats for

        Returns:
            Dictionary with worker stats
        """
        sessions = await self.list_by_worker(worker_id, limit=100)

        total_completed = sum(s.tasks_completed for s in sessions)
        total_failed = sum(s.tasks_failed for s in sessions)
        session_count = len(sessions)

        return {
            "worker_id": worker_id,
            "total_sessions": session_count,
            "total_tasks_completed": total_completed,
            "total_tasks_failed": total_failed,
            "current_session_active": any(s.disconnected_at is None for s in sessions),
        }
