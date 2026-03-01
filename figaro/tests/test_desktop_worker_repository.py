"""Tests for DesktopWorkerRepository CRUD operations."""

import pytest

from figaro.db.repositories.desktop_workers import DesktopWorkerRepository


@pytest.mark.asyncio
async def test_create_and_get(db_session):
    repo = DesktopWorkerRepository(db_session)

    worker = await repo.create(
        worker_id="worker-1",
        novnc_url="http://localhost:6080",
        vnc_username="user1",
        vnc_password="pass1",
        metadata={"key": "value"},
    )

    assert worker.worker_id == "worker-1"
    assert worker.novnc_url == "http://localhost:6080"
    assert worker.vnc_username == "user1"
    assert worker.vnc_password == "pass1"
    assert worker.metadata_ == {"key": "value"}

    fetched = await repo.get("worker-1")
    assert fetched is not None
    assert fetched.worker_id == "worker-1"
    assert fetched.novnc_url == "http://localhost:6080"
    assert fetched.vnc_username == "user1"
    assert fetched.vnc_password == "pass1"
    assert fetched.metadata_ == {"key": "value"}
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


@pytest.mark.asyncio
async def test_get_not_found(db_session):
    repo = DesktopWorkerRepository(db_session)

    result = await repo.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_list_all(db_session):
    repo = DesktopWorkerRepository(db_session)

    await repo.create(worker_id="worker-a", novnc_url="http://a:6080")
    await repo.create(worker_id="worker-b", novnc_url="http://b:6080")

    workers = await repo.list_all()
    assert len(workers) == 2
    worker_ids = {w.worker_id for w in workers}
    assert worker_ids == {"worker-a", "worker-b"}


@pytest.mark.asyncio
async def test_list_all_empty(db_session):
    repo = DesktopWorkerRepository(db_session)

    workers = await repo.list_all()
    assert workers == []


@pytest.mark.asyncio
async def test_upsert_creates_new(db_session):
    repo = DesktopWorkerRepository(db_session)

    worker = await repo.upsert(
        worker_id="worker-new",
        novnc_url="http://new:6080",
        vnc_username="admin",
        vnc_password="secret",
        metadata={"source": "upsert"},
    )

    assert worker.worker_id == "worker-new"
    assert worker.novnc_url == "http://new:6080"
    assert worker.vnc_username == "admin"
    assert worker.vnc_password == "secret"
    assert worker.metadata_ == {"source": "upsert"}

    fetched = await repo.get("worker-new")
    assert fetched is not None
    assert fetched.worker_id == "worker-new"


@pytest.mark.asyncio
async def test_upsert_updates_existing(db_session):
    repo = DesktopWorkerRepository(db_session)

    await repo.create(worker_id="worker-x", novnc_url="http://old:6080")

    updated = await repo.upsert(
        worker_id="worker-x",
        novnc_url="http://new:6080",
    )

    assert updated.worker_id == "worker-x"
    assert updated.novnc_url == "http://new:6080"

    fetched = await repo.get("worker-x")
    assert fetched is not None
    assert fetched.novnc_url == "http://new:6080"


@pytest.mark.asyncio
async def test_update_fields(db_session):
    repo = DesktopWorkerRepository(db_session)

    await repo.create(worker_id="worker-u", novnc_url="http://old:6080")

    updated = await repo.update(worker_id="worker-u", novnc_url="http://updated:6080")

    assert updated is not None
    assert updated.worker_id == "worker-u"
    assert updated.novnc_url == "http://updated:6080"

    fetched = await repo.get("worker-u")
    assert fetched is not None
    assert fetched.novnc_url == "http://updated:6080"


@pytest.mark.asyncio
async def test_update_rename(db_session):
    repo = DesktopWorkerRepository(db_session)

    await repo.create(
        worker_id="old-id",
        novnc_url="http://host:6080",
        vnc_username="user",
    )

    renamed = await repo.update(worker_id="old-id", new_worker_id="new-id")

    assert renamed is not None
    assert renamed.worker_id == "new-id"
    assert renamed.novnc_url == "http://host:6080"
    assert renamed.vnc_username == "user"

    old = await repo.get("old-id")
    assert old is None

    new = await repo.get("new-id")
    assert new is not None
    assert new.worker_id == "new-id"


@pytest.mark.asyncio
async def test_update_not_found(db_session):
    repo = DesktopWorkerRepository(db_session)

    result = await repo.update(worker_id="nonexistent", novnc_url="http://x:6080")
    assert result is None


@pytest.mark.asyncio
async def test_delete_existing(db_session):
    repo = DesktopWorkerRepository(db_session)

    await repo.create(worker_id="worker-del", novnc_url="http://del:6080")

    deleted = await repo.delete("worker-del")
    assert deleted is True

    fetched = await repo.get("worker-del")
    assert fetched is None


@pytest.mark.asyncio
async def test_delete_not_found(db_session):
    repo = DesktopWorkerRepository(db_session)

    deleted = await repo.delete("nonexistent")
    assert deleted is False
