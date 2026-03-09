from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from figaro.db.repositories.desktop_workers import DesktopWorkerRepository

if TYPE_CHECKING:
    from figaro.services.nats.service import NatsService

logger = logging.getLogger(__name__)


async def api_register_desktop_worker(
    svc: NatsService, data: dict[str, Any]
) -> dict[str, Any]:
    """Register a desktop-only worker via NATS API."""
    worker_id = data.get("worker_id", "")
    novnc_url = data.get("novnc_url", "")
    metadata = data.get("metadata", {})
    vnc_username = data.get("vnc_username")
    vnc_password = data.get("vnc_password")
    if vnc_password == "***":
        vnc_password = None  # Sentinel means "no change"

    if not worker_id:
        return {"error": "worker_id is required"}

    await svc._registry.register_desktop_only(
        client_id=worker_id,
        novnc_url=novnc_url,
        metadata=metadata,
        vnc_username=vnc_username,
        vnc_password=vnc_password,
    )
    svc._desktop_worker_ids.add(worker_id)

    # Persist to DB
    if svc._session_factory:
        try:
            async with svc._session_factory() as session:
                repo = DesktopWorkerRepository(session)
                await repo.upsert(
                    worker_id=worker_id,
                    novnc_url=novnc_url,
                    vnc_username=vnc_username,
                    vnc_password=vnc_password,
                    metadata=metadata,
                )
                await session.commit()
        except Exception:
            logger.warning(
                f"Failed to persist desktop worker {worker_id} to DB", exc_info=True
            )

    await svc.broadcast_workers()
    logger.info(f"Registered desktop-only worker via API: {worker_id}")
    return {"status": "ok"}


async def api_remove_desktop_worker(
    svc: NatsService, data: dict[str, Any]
) -> dict[str, Any]:
    """Remove a desktop-only worker via NATS API."""
    worker_id = data.get("worker_id", "")

    if not worker_id:
        return {"error": "worker_id is required"}

    conn = await svc._registry.get_connection(worker_id)
    if conn is None:
        return {"error": f"Worker {worker_id} not found"}

    if conn.agent_connected:
        return {"error": f"Worker {worker_id} has an active agent, cannot remove"}

    await svc._registry.unregister(worker_id)
    svc._desktop_worker_ids.discard(worker_id)

    # Remove from DB
    if svc._session_factory:
        try:
            async with svc._session_factory() as session:
                repo = DesktopWorkerRepository(session)
                await repo.delete(worker_id)
                await session.commit()
        except Exception:
            logger.warning(
                f"Failed to remove desktop worker {worker_id} from DB",
                exc_info=True,
            )

    await svc.broadcast_workers()
    logger.info(f"Removed desktop-only worker via API: {worker_id}")
    return {"status": "ok"}


async def api_update_desktop_worker(
    svc: NatsService, data: dict[str, Any]
) -> dict[str, Any]:
    """Update a desktop-only worker via NATS API."""
    worker_id = data.get("worker_id", "")
    new_worker_id = data.get("new_worker_id") or None
    novnc_url = data.get("novnc_url") or None
    metadata = data.get("metadata") or None
    # Distinguish "not provided" (None = no change) from "explicitly cleared" (empty string = clear)
    _sentinel = object()
    raw_username = data.get("vnc_username", _sentinel)
    raw_password = data.get("vnc_password", _sentinel)
    vnc_username = None if raw_username is _sentinel else (raw_username or "")
    vnc_password = None if raw_password is _sentinel else (raw_password or "")
    if vnc_password == "***":
        vnc_password = None  # Sentinel means "no change"

    if not worker_id:
        return {"error": "worker_id is required"}

    conn = await svc._registry.update_desktop_only(
        client_id=worker_id,
        new_client_id=new_worker_id,
        novnc_url=novnc_url,
        metadata=metadata,
        vnc_username=vnc_username,
        vnc_password=vnc_password,
    )
    if conn is None:
        return {"error": f"Worker {worker_id} not found"}

    if new_worker_id and new_worker_id != worker_id:
        svc._desktop_worker_ids.discard(worker_id)
        svc._desktop_worker_ids.add(new_worker_id)

    # Persist update to DB
    if svc._session_factory:
        try:
            async with svc._session_factory() as session:
                repo = DesktopWorkerRepository(session)
                await repo.update(
                    worker_id=worker_id,
                    new_worker_id=new_worker_id,
                    novnc_url=novnc_url,
                    vnc_username=vnc_username,
                    vnc_password=vnc_password,
                    metadata=metadata,
                )
                await session.commit()
        except Exception:
            logger.warning(
                f"Failed to persist desktop worker update for {worker_id} to DB",
                exc_info=True,
            )

    await svc.broadcast_workers()
    logger.info(f"Updated desktop-only worker via API: {worker_id}")
    return {"status": "ok"}
