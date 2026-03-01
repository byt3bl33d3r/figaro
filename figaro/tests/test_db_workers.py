"""Tests for WorkerSessionRepository database operations."""

import pytest

from figaro.db.repositories.workers import WorkerSessionRepository


class TestWorkerSessionRepository:
    """Tests for WorkerSessionRepository."""

    @pytest.fixture
    async def repo(self, db_session):
        """Create a WorkerSessionRepository instance."""
        return WorkerSessionRepository(db_session)

    async def test_create_worker_session(self, repo, db_session):
        """Test creating a new worker session."""
        session = await repo.create(
            worker_id="worker-1",
            capabilities=["browser", "screenshot"],
            novnc_url="http://localhost:6080",
        )
        await db_session.commit()

        assert session.session_id is not None
        assert session.worker_id == "worker-1"
        assert session.capabilities == ["browser", "screenshot"]
        assert session.novnc_url == "http://localhost:6080"
        assert session.connected_at is not None
        assert session.disconnected_at is None
        assert session.tasks_completed == 0
        assert session.tasks_failed == 0

    async def test_create_minimal_session(self, repo, db_session):
        """Test creating a worker session with minimal info."""
        session = await repo.create(worker_id="worker-1")
        await db_session.commit()

        assert session.worker_id == "worker-1"
        assert session.capabilities == []
        assert session.novnc_url is None

    async def test_get_active_session(self, repo, db_session):
        """Test getting the active session for a worker."""
        await repo.create(worker_id="worker-1")
        await db_session.commit()

        active = await repo.get_active("worker-1")
        assert active is not None
        assert active.worker_id == "worker-1"
        assert active.disconnected_at is None

    async def test_get_active_session_not_found(self, repo):
        """Test getting active session for non-existent worker."""
        active = await repo.get_active("nonexistent")
        assert active is None

    async def test_get_active_returns_none_when_disconnected(self, repo, db_session):
        """Test that get_active returns None for disconnected sessions."""
        await repo.create(worker_id="worker-1")
        await db_session.commit()

        await repo.disconnect("worker-1")
        await db_session.commit()

        active = await repo.get_active("worker-1")
        assert active is None

    async def test_list_active(self, repo, db_session):
        """Test listing all active worker sessions."""
        await repo.create(worker_id="worker-1")
        await repo.create(worker_id="worker-2")
        await repo.create(worker_id="worker-3")
        await db_session.commit()

        # Disconnect one
        await repo.disconnect("worker-2")
        await db_session.commit()

        active = await repo.list_active()
        assert len(active) == 2
        worker_ids = [s.worker_id for s in active]
        assert "worker-1" in worker_ids
        assert "worker-3" in worker_ids
        assert "worker-2" not in worker_ids

    async def test_list_by_worker(self, repo, db_session):
        """Test listing sessions for a specific worker."""
        # Create multiple sessions for the same worker
        await repo.create(worker_id="worker-1")
        await db_session.commit()
        await repo.disconnect("worker-1")
        await db_session.commit()

        await repo.create(worker_id="worker-1")
        await db_session.commit()
        await repo.disconnect("worker-1")
        await db_session.commit()

        await repo.create(worker_id="worker-1")
        await db_session.commit()

        # Different worker
        await repo.create(worker_id="worker-2")
        await db_session.commit()

        sessions = await repo.list_by_worker("worker-1")
        assert len(sessions) == 3
        assert all(s.worker_id == "worker-1" for s in sessions)

    async def test_list_by_worker_limit(self, repo, db_session):
        """Test listing sessions with limit."""
        for _ in range(5):
            await repo.create(worker_id="worker-1")
            await db_session.commit()
            await repo.disconnect("worker-1")
            await db_session.commit()

        sessions = await repo.list_by_worker("worker-1", limit=3)
        assert len(sessions) == 3

    async def test_disconnect(self, repo, db_session):
        """Test disconnecting a worker session."""
        await repo.create(worker_id="worker-1")
        await db_session.commit()

        disconnected = await repo.disconnect("worker-1", reason="manual")
        await db_session.commit()

        assert disconnected is not None
        assert disconnected.disconnected_at is not None
        assert disconnected.disconnect_reason == "manual"

    async def test_disconnect_no_active_session_returns_none(self, repo):
        """Test disconnecting when no active session exists."""
        result = await repo.disconnect("nonexistent")
        assert result is None

    async def test_disconnect_already_disconnected_returns_none(self, repo, db_session):
        """Test disconnecting an already disconnected session."""
        await repo.create(worker_id="worker-1")
        await db_session.commit()

        await repo.disconnect("worker-1")
        await db_session.commit()

        result = await repo.disconnect("worker-1")
        assert result is None

    async def test_increment_completed(self, repo, db_session):
        """Test incrementing the completed task count."""
        await repo.create(worker_id="worker-1")
        await db_session.commit()

        updated = await repo.increment_completed("worker-1")
        await db_session.commit()

        assert updated is not None
        assert updated.tasks_completed == 1

        # Increment again
        updated = await repo.increment_completed("worker-1")
        await db_session.commit()

        assert updated.tasks_completed == 2

    async def test_increment_completed_no_session_returns_none(self, repo):
        """Test incrementing completed for non-existent session."""
        result = await repo.increment_completed("nonexistent")
        assert result is None

    async def test_increment_failed(self, repo, db_session):
        """Test incrementing the failed task count."""
        await repo.create(worker_id="worker-1")
        await db_session.commit()

        updated = await repo.increment_failed("worker-1")
        await db_session.commit()

        assert updated is not None
        assert updated.tasks_failed == 1

        # Increment again
        updated = await repo.increment_failed("worker-1")
        await db_session.commit()

        assert updated.tasks_failed == 2

    async def test_increment_failed_no_session_returns_none(self, repo):
        """Test incrementing failed for non-existent session."""
        result = await repo.increment_failed("nonexistent")
        assert result is None

    async def test_get_stats(self, repo, db_session):
        """Test getting worker stats."""
        # Session 1: completed 3, failed 1
        await repo.create(worker_id="worker-1")
        await db_session.commit()
        for _ in range(3):
            await repo.increment_completed("worker-1")
        await repo.increment_failed("worker-1")
        await db_session.commit()
        await repo.disconnect("worker-1")
        await db_session.commit()

        # Session 2: completed 2, failed 0
        await repo.create(worker_id="worker-1")
        await db_session.commit()
        for _ in range(2):
            await repo.increment_completed("worker-1")
        await db_session.commit()

        stats = await repo.get_stats("worker-1")

        assert stats["worker_id"] == "worker-1"
        assert stats["total_sessions"] == 2
        assert stats["total_tasks_completed"] == 5
        assert stats["total_tasks_failed"] == 1
        assert stats["current_session_active"] is True

    async def test_get_stats_no_sessions(self, repo):
        """Test getting stats for worker with no sessions."""
        stats = await repo.get_stats("nonexistent")

        assert stats["worker_id"] == "nonexistent"
        assert stats["total_sessions"] == 0
        assert stats["total_tasks_completed"] == 0
        assert stats["total_tasks_failed"] == 0
        assert stats["current_session_active"] is False

    async def test_worker_session_lifecycle(self, repo, db_session):
        """Test complete worker session lifecycle."""
        # Worker connects
        await repo.create(
            worker_id="worker-1",
            capabilities=["browser"],
            novnc_url="http://localhost:6080",
        )
        await db_session.commit()

        # Verify active
        active = await repo.list_active()
        assert len(active) == 1

        # Worker completes some tasks
        await repo.increment_completed("worker-1")
        await repo.increment_completed("worker-1")
        await repo.increment_failed("worker-1")
        await db_session.commit()

        # Check session
        current = await repo.get_active("worker-1")
        assert current.tasks_completed == 2
        assert current.tasks_failed == 1

        # Worker disconnects
        disconnected = await repo.disconnect("worker-1", reason="websocket_disconnect")
        await db_session.commit()

        assert disconnected.disconnected_at is not None
        assert disconnected.disconnect_reason == "websocket_disconnect"

        # Verify no longer active
        active = await repo.list_active()
        assert len(active) == 0

        # Worker reconnects (new session)
        await repo.create(
            worker_id="worker-1",
            capabilities=["browser"],
            novnc_url="http://localhost:6080",
        )
        await db_session.commit()

        # Now active again
        active = await repo.list_active()
        assert len(active) == 1

        # Stats include both sessions
        stats = await repo.get_stats("worker-1")
        assert stats["total_sessions"] == 2
        assert stats["total_tasks_completed"] == 2
        assert stats["total_tasks_failed"] == 1

    async def test_multiple_workers(self, repo, db_session):
        """Test tracking multiple workers simultaneously."""
        # Connect 3 workers
        await repo.create(worker_id="worker-1", capabilities=["browser"])
        await repo.create(worker_id="worker-2", capabilities=["browser"])
        await repo.create(worker_id="worker-3", capabilities=["browser"])
        await db_session.commit()

        # All active
        active = await repo.list_active()
        assert len(active) == 3

        # Each completes different numbers of tasks
        await repo.increment_completed("worker-1")
        await repo.increment_completed("worker-2")
        await repo.increment_completed("worker-2")
        await repo.increment_completed("worker-3")
        await repo.increment_completed("worker-3")
        await repo.increment_completed("worker-3")
        await db_session.commit()

        # Check individual stats
        stats1 = await repo.get_stats("worker-1")
        stats2 = await repo.get_stats("worker-2")
        stats3 = await repo.get_stats("worker-3")

        assert stats1["total_tasks_completed"] == 1
        assert stats2["total_tasks_completed"] == 2
        assert stats3["total_tasks_completed"] == 3

        # Disconnect worker-2
        await repo.disconnect("worker-2")
        await db_session.commit()

        active = await repo.list_active()
        assert len(active) == 2
