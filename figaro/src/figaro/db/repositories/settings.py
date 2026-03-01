"""Settings repository for system-level configuration."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from figaro.db.models import FigaroSettingsModel


class SettingsRepository:
    """Repository for figaro_settings single-row table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _get_or_create(self) -> FigaroSettingsModel:
        """Get the settings row (id=1), creating it if missing."""
        result = await self.session.execute(
            select(FigaroSettingsModel).where(FigaroSettingsModel.id == 1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = FigaroSettingsModel(id=1)
            self.session.add(row)
            await self.session.flush()
        return row

    async def get_vnc_password(self) -> str | None:
        """Get the system-level VNC password."""
        row = await self._get_or_create()
        return row.vnc_password

    async def set_vnc_password(self, password: str | None) -> None:
        """Set the system-level VNC password."""
        row = await self._get_or_create()
        row.vnc_password = password
        await self.session.flush()

    async def get_vnc_username(self) -> str | None:
        """Get the system-level VNC username."""
        row = await self._get_or_create()
        return row.vnc_username

    async def set_vnc_username(self, username: str | None) -> None:
        """Set the system-level VNC username."""
        row = await self._get_or_create()
        row.vnc_username = username
        await self.session.flush()
