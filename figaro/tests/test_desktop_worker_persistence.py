"""Integration tests for desktop worker DB persistence in NatsService."""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from figaro.db.repositories.desktop_workers import DesktopWorkerRepository
from figaro.services.nats_service import NatsService
from figaro.services.registry import Registry


@pytest.fixture
def registry():
    """Create a fresh Registry for each test."""
    return Registry()


def _make_settings(desktop_workers: str = "[]", nats_url: str = "nats://localhost:4222"):
    """Build a minimal Settings-like mock."""
    settings = MagicMock()
    settings.desktop_workers = desktop_workers
    settings.nats_url = nats_url
    return settings


def _make_nats_service(
    registry: Registry,
    session_factory=None,
    desktop_workers: str = "[]",
) -> NatsService:
    """Construct a NatsService with mocked dependencies."""
    settings = _make_settings(desktop_workers=desktop_workers)
    task_manager = MagicMock()
    scheduler = MagicMock()
    help_request_manager = MagicMock()

    svc = NatsService(
        registry=registry,
        task_manager=task_manager,
        scheduler=scheduler,
        help_request_manager=help_request_manager,
        settings=settings,
        session_factory=session_factory,
    )
    # API handlers call broadcast_workers after mutations
    svc.broadcast_workers = AsyncMock()
    return svc


# ── 1. Startup loads workers from DB ────────────────────────────


@pytest.mark.asyncio
async def test_startup_loads_from_db(session_factory, db_session, registry):
    """Pre-populate DB with a desktop worker, then verify _register_desktop_workers
    loads it into the in-memory registry and _desktop_worker_ids."""
    # Seed DB directly via repository
    repo = DesktopWorkerRepository(db_session)
    await repo.create(
        worker_id="db-w1",
        novnc_url="http://db-w1:6080",
        metadata={"os": "linux"},
    )
    await db_session.commit()

    # Create service with empty env setting so only DB workers are loaded
    svc = _make_nats_service(registry, session_factory=session_factory, desktop_workers="[]")

    await svc._register_desktop_workers()

    # Verify in-memory registry
    conn = await registry.get_connection("db-w1")
    assert conn is not None
    assert conn.novnc_url == "http://db-w1:6080"
    assert conn.metadata == {"os": "linux"}

    # Verify tracked set
    assert "db-w1" in svc._desktop_worker_ids


# ── 2. Startup seeds env entries into DB ─────────────────────────


@pytest.mark.asyncio
async def test_startup_seeds_env_to_db(session_factory, db_session, registry):
    """Env-var entries should be upserted into DB during startup and registered
    in the in-memory registry."""
    env_json = json.dumps([{"id": "env-1", "novnc_url": "http://env1:6080"}])
    svc = _make_nats_service(registry, session_factory=session_factory, desktop_workers=env_json)

    await svc._register_desktop_workers()

    # Verify in-memory registry
    conn = await registry.get_connection("env-1")
    assert conn is not None
    assert conn.novnc_url == "http://env1:6080"

    # Verify DB persistence
    repo = DesktopWorkerRepository(db_session)
    row = await repo.get("env-1")
    assert row is not None
    assert row.novnc_url == "http://env1:6080"


# ── 3. Startup fallback without DB ──────────────────────────────


@pytest.mark.asyncio
async def test_startup_fallback_without_db(registry):
    """When session_factory is None, workers should still be registered from
    env var into the in-memory registry (no DB interaction)."""
    env_json = json.dumps([{"id": "env-2", "novnc_url": "http://env2:6080"}])
    svc = _make_nats_service(registry, session_factory=None, desktop_workers=env_json)

    await svc._register_desktop_workers()

    conn = await registry.get_connection("env-2")
    assert conn is not None
    assert conn.novnc_url == "http://env2:6080"
    assert "env-2" in svc._desktop_worker_ids


# ── 4. API register persists to DB ──────────────────────────────


@pytest.mark.asyncio
async def test_api_register_persists_to_db(session_factory, db_session, registry):
    """_api_register_desktop_worker should persist the new worker to the DB."""
    svc = _make_nats_service(registry, session_factory=session_factory)

    result = await svc._api_register_desktop_worker({
        "worker_id": "d1",
        "novnc_url": "http://d1:6080",
    })

    assert result == {"status": "ok"}

    # Verify DB
    repo = DesktopWorkerRepository(db_session)
    row = await repo.get("d1")
    assert row is not None
    assert row.novnc_url == "http://d1:6080"


# ── 5. API remove deletes from DB ───────────────────────────────


@pytest.mark.asyncio
async def test_api_remove_deletes_from_db(session_factory, db_session, registry):
    """_api_remove_desktop_worker should delete the worker from DB."""
    # Pre-register in-memory so registry.get_connection succeeds
    await registry.register_desktop_only(client_id="d1", novnc_url="http://d1:6080")

    svc = _make_nats_service(registry, session_factory=session_factory)
    svc._desktop_worker_ids.add("d1")

    # Also persist to DB so there is something to delete
    async with session_factory() as session:
        repo = DesktopWorkerRepository(session)
        await repo.create(worker_id="d1", novnc_url="http://d1:6080")
        await session.commit()

    result = await svc._api_remove_desktop_worker({"worker_id": "d1"})
    assert result == {"status": "ok"}

    # Verify DB is empty
    repo = DesktopWorkerRepository(db_session)
    row = await repo.get("d1")
    assert row is None

    # Verify in-memory tracking
    assert "d1" not in svc._desktop_worker_ids


# ── 6. API update persists to DB ────────────────────────────────


@pytest.mark.asyncio
async def test_api_update_persists_to_db(session_factory, db_session, registry):
    """_api_update_desktop_worker should persist the updated novnc_url to DB."""
    # Pre-register in-memory
    await registry.register_desktop_only(client_id="d1", novnc_url="http://d1:6080")

    svc = _make_nats_service(registry, session_factory=session_factory)
    svc._desktop_worker_ids.add("d1")

    # Also persist to DB so there is something to update
    async with session_factory() as session:
        repo = DesktopWorkerRepository(session)
        await repo.create(worker_id="d1", novnc_url="http://d1:6080")
        await session.commit()

    result = await svc._api_update_desktop_worker({
        "worker_id": "d1",
        "novnc_url": "http://new:6080",
    })
    assert result == {"status": "ok"}

    # Verify DB has the updated URL
    repo = DesktopWorkerRepository(db_session)
    row = await repo.get("d1")
    assert row is not None
    assert row.novnc_url == "http://new:6080"
