from __future__ import annotations

import json
import logging
from typing import Any, TYPE_CHECKING

from figaro.db.repositories.desktop_workers import DesktopWorkerRepository
from figaro.db.repositories.settings import SettingsRepository

if TYPE_CHECKING:
    from figaro.services.nats.service import NatsService

logger = logging.getLogger(__name__)


async def register_desktop_workers(svc: NatsService) -> None:
    """Register desktop workers from DB (seeded by env var) or env var fallback."""
    raw = svc._settings.desktop_workers
    env_entries: list[dict[str, Any]] = []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            env_entries = parsed
    except (json.JSONDecodeError, TypeError):
        pass

    if svc._session_factory:
        # Phase 1: seed env-var entries into DB
        try:
            async with svc._session_factory() as session:
                repo = DesktopWorkerRepository(session)
                for entry in env_entries:
                    worker_id = entry.get("id", "")
                    if not worker_id:
                        continue
                    await repo.upsert(
                        worker_id=worker_id,
                        novnc_url=entry.get("novnc_url", ""),
                        vnc_username=entry.get("vnc_username"),
                        vnc_password=entry.get("vnc_password"),
                        metadata=entry.get("metadata", {}),
                    )
                await session.commit()

                # Phase 2: load all desktop workers from DB
                workers = await repo.list_all()
                for w in workers:
                    await svc._registry.register_desktop_only(
                        client_id=w.worker_id,
                        novnc_url=w.novnc_url,
                        metadata=w.metadata_,
                        vnc_username=w.vnc_username,
                        vnc_password=w.vnc_password,
                    )
                    svc._desktop_worker_ids.add(w.worker_id)
                    logger.info(f"Registered desktop worker from DB: {w.worker_id}")
        except Exception:
            logger.warning(
                "Failed to load desktop workers from DB, falling back to env var",
                exc_info=True,
            )
            await register_desktop_workers_from_env(svc, env_entries)
    else:
        await register_desktop_workers_from_env(svc, env_entries)


async def register_desktop_workers_from_env(
    svc: NatsService, entries: list[dict[str, Any]]
) -> None:
    """Fallback: register desktop workers from parsed env var entries."""
    for entry in entries:
        worker_id = entry.get("id", "")
        if not worker_id:
            logger.warning("Skipping desktop worker entry with no id")
            continue
        await svc._registry.register_desktop_only(
            client_id=worker_id,
            novnc_url=entry.get("novnc_url", ""),
            metadata=entry.get("metadata", {}),
            vnc_username=entry.get("vnc_username"),
            vnc_password=entry.get("vnc_password"),
        )
        svc._desktop_worker_ids.add(worker_id)
        logger.info(f"Registered desktop-only worker from config: {worker_id}")


async def load_settings_vnc_password(svc: NatsService) -> None:
    """Load VNC password from settings table, overriding env var default."""
    if not svc._session_factory:
        return
    try:
        async with svc._session_factory() as session:
            repo = SettingsRepository(session)
            password = await repo.get_vnc_password()
            if password is not None:
                svc._settings.vnc_password = password
                logger.info("Loaded VNC password from settings table")
    except Exception:
        logger.warning("Failed to load VNC password from settings table", exc_info=True)
