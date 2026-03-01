"""Desktop worker repository for database operations."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from figaro.db.models import DesktopWorkerModel


class DesktopWorkerRepository:
    """Repository for desktop worker database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        worker_id: str,
        novnc_url: str = "",
        vnc_username: str | None = None,
        vnc_password: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DesktopWorkerModel:
        """Create a new desktop worker."""
        model = DesktopWorkerModel(
            worker_id=worker_id,
            novnc_url=novnc_url,
            vnc_username=vnc_username,
            vnc_password=vnc_password,
            metadata_=metadata or {},
        )
        self.session.add(model)
        await self.session.flush()
        return model

    async def get(self, worker_id: str) -> DesktopWorkerModel | None:
        """Get a desktop worker by ID."""
        result = await self.session.execute(
            select(DesktopWorkerModel).where(
                DesktopWorkerModel.worker_id == worker_id
            )
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[DesktopWorkerModel]:
        """Get all desktop workers."""
        result = await self.session.execute(
            select(DesktopWorkerModel).order_by(DesktopWorkerModel.created_at.asc())
        )
        return list(result.scalars().all())

    async def upsert(
        self,
        worker_id: str,
        novnc_url: str = "",
        vnc_username: str | None = None,
        vnc_password: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DesktopWorkerModel:
        """Create or update a desktop worker."""
        existing = await self.get(worker_id)
        if existing:
            existing.novnc_url = novnc_url
            existing.vnc_username = vnc_username
            existing.vnc_password = vnc_password
            existing.metadata_ = metadata or {}
            existing.updated_at = datetime.now(timezone.utc)
            await self.session.flush()
            return existing
        return await self.create(
            worker_id=worker_id,
            novnc_url=novnc_url,
            vnc_username=vnc_username,
            vnc_password=vnc_password,
            metadata=metadata,
        )

    async def update(
        self,
        worker_id: str,
        new_worker_id: str | None = None,
        novnc_url: str | None = None,
        vnc_username: str | None = None,
        vnc_password: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DesktopWorkerModel | None:
        """Update a desktop worker. Handles rename via delete+create."""
        if new_worker_id and new_worker_id != worker_id:
            existing = await self.get(worker_id)
            if not existing:
                return None
            # Rename: delete old, create new
            await self.delete(worker_id)
            return await self.create(
                worker_id=new_worker_id,
                novnc_url=novnc_url if novnc_url is not None else existing.novnc_url,
                vnc_username=vnc_username
                if vnc_username is not None
                else existing.vnc_username,
                vnc_password=vnc_password
                if vnc_password is not None
                else existing.vnc_password,
                metadata=metadata if metadata is not None else existing.metadata_,
            )

        existing = await self.get(worker_id)
        if not existing:
            return None

        if novnc_url is not None:
            existing.novnc_url = novnc_url
        if vnc_username is not None:
            existing.vnc_username = vnc_username
        if vnc_password is not None:
            existing.vnc_password = vnc_password
        if metadata is not None:
            existing.metadata_ = metadata
        existing.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return existing

    async def delete(self, worker_id: str) -> bool:
        """Delete a desktop worker."""
        result = await self.session.execute(
            delete(DesktopWorkerModel).where(
                DesktopWorkerModel.worker_id == worker_id
            )
        )
        return (result.rowcount or 0) > 0
