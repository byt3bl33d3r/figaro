"""Tests for worker/supervisor registration and heartbeat auto-registration."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from figaro.models import ClientType
from figaro.models.messages import WorkerStatus
from figaro.services import Registry, TaskManager


@pytest.fixture
def registry():
    return Registry()


@pytest.fixture
def task_manager():
    return TaskManager()


@pytest.fixture
def mock_scheduler():
    scheduler = MagicMock()
    scheduler.get_scheduled_task = AsyncMock()
    return scheduler


@pytest.fixture
def mock_help_request_manager():
    return MagicMock()


@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.nats_url = "nats://localhost:4222"
    settings.nats_ws_url = "ws://localhost:8443"
    settings.self_healing_enabled = True
    settings.self_healing_max_retries = 2
    settings.vnc_pool_idle_timeout = 60
    settings.vnc_pool_sweep_interval = 15
    return settings


@pytest.fixture
def nats_service(
    registry, task_manager, mock_scheduler, mock_help_request_manager, mock_settings
):
    """Create a real NatsService with mocked external dependencies."""
    from figaro.services.nats_service import NatsService

    mock_sf = MagicMock()

    service = NatsService(
        registry=registry,
        task_manager=task_manager,
        scheduler=mock_scheduler,
        help_request_manager=mock_help_request_manager,
        settings=mock_settings,
        session_factory=mock_sf,
    )

    # Mock the NATS connection so broadcast methods work
    mock_conn = MagicMock()
    mock_conn.publish = AsyncMock()
    mock_conn.is_connected = True
    service._conn = mock_conn

    return service


class TestHandleWorkerRegister:
    """Tests for NatsService._handle_worker_register."""

    @pytest.mark.asyncio
    async def test_handle_worker_register(self, nats_service, registry):
        """Calls handler with worker registration data, verifies worker is in
        registry with correct type and capabilities."""

        data = {
            "worker_id": "worker-1",
            "capabilities": ["browser", "desktop"],
            "novnc_url": "http://worker-1:6080",
            "metadata": {"version": "1.0"},
        }

        await nats_service._handle_worker_register(data)

        conn = await registry.get_connection("worker-1")
        assert conn is not None
        assert conn.client_type == ClientType.WORKER
        assert conn.capabilities == ["browser", "desktop"]
        assert conn.novnc_url == "http://worker-1:6080"
        assert conn.metadata == {"version": "1.0"}

    @pytest.mark.asyncio
    async def test_handle_worker_register_returns_ok(self, nats_service):
        """Verifies handler returns {"status": "ok"} dict."""

        data = {
            "worker_id": "worker-2",
            "capabilities": [],
        }

        result = await nats_service._handle_worker_register(data)

        assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_handle_worker_register_idempotent(self, nats_service, registry):
        """Calling handler twice with same worker_id doesn't error,
        worker still registered."""

        data = {
            "worker_id": "worker-1",
            "capabilities": ["browser"],
            "novnc_url": "http://worker-1:6080",
        }

        # Register twice
        result1 = await nats_service._handle_worker_register(data)
        result2 = await nats_service._handle_worker_register(data)

        assert result1 == {"status": "ok"}
        assert result2 == {"status": "ok"}

        conn = await registry.get_connection("worker-1")
        assert conn is not None
        assert conn.client_type == ClientType.WORKER
        assert conn.capabilities == ["browser"]


class TestHandleSupervisorRegister:
    """Tests for NatsService._handle_supervisor_register."""

    @pytest.mark.asyncio
    async def test_handle_supervisor_register(self, nats_service, registry):
        """Calls handler with supervisor registration data, verifies supervisor
        is in registry with correct type and capabilities."""

        data = {
            "worker_id": "supervisor-1",
            "capabilities": ["delegation", "optimization"],
        }

        await nats_service._handle_supervisor_register(data)

        conn = await registry.get_connection("supervisor-1")
        assert conn is not None
        assert conn.client_type == ClientType.SUPERVISOR
        assert conn.capabilities == ["delegation", "optimization"]

    @pytest.mark.asyncio
    async def test_handle_supervisor_register_returns_ok(self, nats_service):
        """Verifies supervisor handler returns {"status": "ok"}."""

        data = {
            "worker_id": "supervisor-2",
            "capabilities": [],
        }

        result = await nats_service._handle_supervisor_register(data)

        assert result == {"status": "ok"}


class TestHandleHeartbeat:
    """Tests for NatsService._handle_heartbeat."""

    @pytest.mark.asyncio
    async def test_heartbeat_auto_registers_unknown_supervisor(
        self, nats_service, registry
    ):
        """Heartbeat with client_type=supervisor for unknown client_id
        auto-registers it."""

        # No supervisor registered yet
        conn = await registry.get_connection("supervisor-new")
        assert conn is None

        data = {
            "client_id": "supervisor-new",
            "client_type": "supervisor",
            "status": "idle",
        }

        await nats_service._handle_heartbeat(data)

        # Should now be registered
        conn = await registry.get_connection("supervisor-new")
        assert conn is not None
        assert conn.client_type == ClientType.SUPERVISOR

    @pytest.mark.asyncio
    async def test_heartbeat_auto_registers_unknown_worker(
        self, nats_service, registry
    ):
        """Heartbeat with client_type=worker for unknown client_id
        auto-registers it."""

        # No worker registered yet
        conn = await registry.get_connection("worker-new")
        assert conn is None

        data = {
            "client_id": "worker-new",
            "client_type": "worker",
            "status": "idle",
        }

        await nats_service._handle_heartbeat(data)

        # Should now be registered
        conn = await registry.get_connection("worker-new")
        assert conn is not None
        assert conn.client_type == ClientType.WORKER

    @pytest.mark.asyncio
    async def test_heartbeat_updates_known_client(self, nats_service, registry):
        """Heartbeat for already-registered client updates heartbeat timestamp."""

        # Pre-register a worker
        await registry.register(
            client_id="worker-existing",
            client_type=ClientType.WORKER,
            capabilities=["browser"],
        )

        # Record original heartbeat time
        conn_before = await registry.get_connection("worker-existing")
        original_heartbeat = conn_before.last_heartbeat

        # Small delay to ensure time difference
        import asyncio

        await asyncio.sleep(0.05)

        data = {
            "client_id": "worker-existing",
            "status": "busy",
        }

        await nats_service._handle_heartbeat(data)

        # Heartbeat timestamp should have been updated
        conn_after = await registry.get_connection("worker-existing")
        assert conn_after.last_heartbeat >= original_heartbeat
        assert conn_after.status == WorkerStatus.BUSY

    @pytest.mark.asyncio
    async def test_heartbeat_auto_registers_worker_with_novnc_url(
        self, nats_service, registry
    ):
        """Heartbeat with novnc_url preserves VNC URL during auto-registration,
        so the VNC proxy can connect after orchestrator restart."""

        data = {
            "client_id": "worker-vnc",
            "client_type": "worker",
            "status": "idle",
            "novnc_url": "ws://worker-vnc:6080/websockify",
            "capabilities": ["browser", "desktop"],
        }

        await nats_service._handle_heartbeat(data)

        conn = await registry.get_connection("worker-vnc")
        assert conn is not None
        assert conn.client_type == ClientType.WORKER
        assert conn.novnc_url == "ws://worker-vnc:6080/websockify"
        assert conn.capabilities == ["browser", "desktop"]

    @pytest.mark.asyncio
    async def test_heartbeat_auto_registers_worker_without_novnc_url(
        self, nats_service, registry
    ):
        """Heartbeat without novnc_url still registers but with None VNC URL."""

        data = {
            "client_id": "worker-no-vnc",
            "client_type": "worker",
            "status": "idle",
        }

        await nats_service._handle_heartbeat(data)

        conn = await registry.get_connection("worker-no-vnc")
        assert conn is not None
        assert conn.client_type == ClientType.WORKER
        assert conn.novnc_url is None

    @pytest.mark.asyncio
    async def test_heartbeat_does_not_auto_register_without_client_type(
        self, nats_service, registry
    ):
        """Heartbeat without client_type for unknown client doesn't register it."""

        # No client registered
        conn = await registry.get_connection("unknown-client")
        assert conn is None

        data = {
            "client_id": "unknown-client",
            "status": "idle",
            # No client_type field
        }

        await nats_service._handle_heartbeat(data)

        # Should still not be registered
        conn = await registry.get_connection("unknown-client")
        assert conn is None
