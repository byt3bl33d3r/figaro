"""Tests for the Registry service."""

import time
import pytest

from figaro.services import Registry
from figaro.models import ClientType
from figaro.models.messages import WorkerStatus


class TestRegistry:
    """Tests for Registry class."""

    @pytest.mark.asyncio
    async def test_register_worker(self, registry: Registry):
        """Test registering a worker client."""
        conn = await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            capabilities=["browser"],
            novnc_url="ws://localhost:6080/websockify",
        )

        assert conn.client_id == "worker-1"
        assert conn.client_type == ClientType.WORKER
        assert conn.status == WorkerStatus.IDLE
        assert conn.capabilities == ["browser"]
        assert conn.novnc_url == "ws://localhost:6080/websockify"

    @pytest.mark.asyncio
    async def test_register_ui_client(self, registry: Registry):
        """Test registering a UI client."""
        conn = await registry.register(
            client_id="ui-1",
            client_type=ClientType.UI,
        )

        assert conn.client_id == "ui-1"
        assert conn.client_type == ClientType.UI

    @pytest.mark.asyncio
    async def test_unregister(self, registry: Registry):
        """Test unregistering a client."""
        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
        )

        await registry.unregister("worker-1")
        conn = await registry.get_connection("worker-1")
        assert conn is None

    @pytest.mark.asyncio
    async def test_unregister_nonexistent(self, registry: Registry):
        """Test unregistering a non-existent client doesn't raise."""
        await registry.unregister("nonexistent")

    @pytest.mark.asyncio
    async def test_get_connection(self, registry: Registry):
        """Test getting a connection by ID."""
        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
        )

        conn = await registry.get_connection("worker-1")
        assert conn is not None
        assert conn.client_id == "worker-1"

    @pytest.mark.asyncio
    async def test_get_connection_nonexistent(self, registry: Registry):
        """Test getting a non-existent connection returns None."""
        conn = await registry.get_connection("nonexistent")
        assert conn is None

    @pytest.mark.asyncio
    async def test_set_worker_status(self, registry: Registry):
        """Test setting worker status."""
        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
        )

        await registry.set_worker_status("worker-1", WorkerStatus.BUSY)
        conn = await registry.get_connection("worker-1")
        assert conn is not None
        assert conn.status == WorkerStatus.BUSY

    @pytest.mark.asyncio
    async def test_get_workers(self, registry: Registry):
        """Test getting all workers."""
        await registry.register("worker-1", ClientType.WORKER)
        await registry.register("worker-2", ClientType.WORKER)
        await registry.register("ui-1", ClientType.UI)

        workers = await registry.get_workers()
        assert len(workers) == 2
        worker_ids = {w.client_id for w in workers}
        assert worker_ids == {"worker-1", "worker-2"}

    @pytest.mark.asyncio
    async def test_get_ui_clients(self, registry: Registry):
        """Test getting all UI clients."""
        await registry.register("worker-1", ClientType.WORKER)
        await registry.register("ui-1", ClientType.UI)
        await registry.register("ui-2", ClientType.UI)

        ui_clients = await registry.get_ui_clients()
        assert len(ui_clients) == 2
        ui_ids = {c.client_id for c in ui_clients}
        assert ui_ids == {"ui-1", "ui-2"}

    @pytest.mark.asyncio
    async def test_get_idle_worker(self, registry: Registry):
        """Test getting an idle worker."""
        await registry.register("worker-1", ClientType.WORKER)
        await registry.register("worker-2", ClientType.WORKER)
        await registry.set_worker_status("worker-1", WorkerStatus.BUSY)

        idle_worker = await registry.get_idle_worker()
        assert idle_worker is not None
        assert idle_worker.client_id == "worker-2"
        assert idle_worker.status == WorkerStatus.IDLE

    @pytest.mark.asyncio
    async def test_get_idle_worker_none_available(self, registry: Registry):
        """Test getting idle worker when none available."""
        await registry.register("worker-1", ClientType.WORKER)
        await registry.set_worker_status("worker-1", WorkerStatus.BUSY)

        idle_worker = await registry.get_idle_worker()
        assert idle_worker is None

    @pytest.mark.asyncio
    async def test_claim_idle_worker(self, registry: Registry):
        """Test atomically claiming an idle worker."""
        await registry.register("worker-1", ClientType.WORKER)
        await registry.register("worker-2", ClientType.WORKER)

        claimed = await registry.claim_idle_worker()
        assert claimed is not None
        assert claimed.status == WorkerStatus.BUSY

        # Verify the worker is now busy in the registry
        conn = await registry.get_connection(claimed.client_id)
        assert conn is not None
        assert conn.status == WorkerStatus.BUSY

    @pytest.mark.asyncio
    async def test_claim_idle_worker_none_available(self, registry: Registry):
        """Test claiming when no idle workers available."""
        await registry.register("worker-1", ClientType.WORKER)
        await registry.set_worker_status("worker-1", WorkerStatus.BUSY)

        claimed = await registry.claim_idle_worker()
        assert claimed is None

    @pytest.mark.asyncio
    async def test_update_heartbeat(self, registry: Registry):
        """Test updating heartbeat for a client."""
        await registry.register("worker-1", ClientType.WORKER)

        conn = await registry.get_connection("worker-1")
        original_heartbeat = conn.last_heartbeat

        # Small delay to ensure time changes
        import asyncio

        await asyncio.sleep(0.01)

        await registry.update_heartbeat("worker-1")

        conn = await registry.get_connection("worker-1")
        assert conn.last_heartbeat >= original_heartbeat

    @pytest.mark.asyncio
    async def test_update_heartbeat_with_status(self, registry: Registry):
        """Test updating heartbeat with status change."""
        await registry.register("worker-1", ClientType.WORKER)

        await registry.update_heartbeat("worker-1", status=WorkerStatus.BUSY)

        conn = await registry.get_connection("worker-1")
        assert conn.status == WorkerStatus.BUSY

    @pytest.mark.asyncio
    async def test_check_heartbeats_no_timeout(self, registry: Registry):
        """Test check_heartbeats returns empty list when all clients are fresh."""
        await registry.register("worker-1", ClientType.WORKER)
        await registry.register("worker-2", ClientType.WORKER)

        timed_out = await registry.check_heartbeats(timeout=60)
        assert timed_out == []

    @pytest.mark.asyncio
    async def test_check_heartbeats_with_timeout(self, registry: Registry):
        """Test check_heartbeats returns timed-out clients."""
        await registry.register("worker-1", ClientType.WORKER)

        # Manually set a very old heartbeat
        conn = await registry.get_connection("worker-1")
        conn.last_heartbeat = time.time() - 120  # 2 minutes ago

        timed_out = await registry.check_heartbeats(timeout=60)
        assert "worker-1" in timed_out

    @pytest.mark.asyncio
    async def test_register_with_status(self, registry: Registry):
        """Test registering a client with a specific status."""
        conn = await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            status=WorkerStatus.BUSY,
        )

        assert conn.status == WorkerStatus.BUSY

    @pytest.mark.asyncio
    async def test_get_supervisors(self, registry: Registry):
        """Test getting all supervisors."""
        await registry.register("supervisor-1", ClientType.SUPERVISOR)
        await registry.register("worker-1", ClientType.WORKER)

        supervisors = await registry.get_supervisors()
        assert len(supervisors) == 1
        assert supervisors[0].client_id == "supervisor-1"

    @pytest.mark.asyncio
    async def test_claim_idle_supervisor(self, registry: Registry):
        """Test claiming an idle supervisor."""
        await registry.register("supervisor-1", ClientType.SUPERVISOR)

        claimed = await registry.claim_idle_supervisor()
        assert claimed is not None
        assert claimed.client_id == "supervisor-1"
        assert claimed.status == WorkerStatus.BUSY

    @pytest.mark.asyncio
    async def test_register_desktop_only(self, registry: Registry):
        """Test registering a desktop-only worker."""
        conn = await registry.register_desktop_only(
            "desktop-1",
            "ws://host:6080/websockify",
            {"os": "macos"},
        )

        assert conn.client_id == "desktop-1"
        assert conn.agent_connected is False
        assert conn.status == WorkerStatus.IDLE
        assert conn.metadata == {"os": "macos"}
        assert conn.capabilities == []

        # Verify it's retrievable from the registry
        stored = await registry.get_connection("desktop-1")
        assert stored is not None
        assert stored.agent_connected is False

    @pytest.mark.asyncio
    async def test_claim_idle_worker_skips_desktop_only(self, registry: Registry):
        """Test that claim_idle_worker skips desktop-only workers."""
        await registry.register_desktop_only(
            "desktop-1",
            "ws://host:6080/websockify",
        )

        claimed = await registry.claim_idle_worker()
        assert claimed is None

    @pytest.mark.asyncio
    async def test_get_idle_worker_skips_desktop_only(self, registry: Registry):
        """Test that get_idle_worker skips desktop-only workers."""
        await registry.register_desktop_only(
            "desktop-1",
            "ws://host:6080/websockify",
        )

        idle = await registry.get_idle_worker()
        assert idle is None

    @pytest.mark.asyncio
    async def test_check_heartbeats_skips_desktop_only(self, registry: Registry):
        """Test that check_heartbeats skips desktop-only workers."""
        await registry.register_desktop_only(
            "desktop-1",
            "ws://host:6080/websockify",
        )

        # Set a very old heartbeat
        conn = await registry.get_connection("desktop-1")
        conn.last_heartbeat = time.time() - 300  # 5 minutes ago

        timed_out = await registry.check_heartbeats(timeout=60)
        assert "desktop-1" not in timed_out

        # Verify the worker is still in the registry
        stored = await registry.get_connection("desktop-1")
        assert stored is not None

    @pytest.mark.asyncio
    async def test_upgrade_to_agent(self, registry: Registry):
        """Test upgrading a desktop-only worker to a full agent."""
        await registry.register_desktop_only(
            "desktop-1",
            "ws://host:6080/websockify",
            {"os": "macos"},
        )

        before = await registry.get_connection("desktop-1")
        old_heartbeat = before.last_heartbeat

        import asyncio

        await asyncio.sleep(0.01)

        upgraded = await registry.upgrade_to_agent(
            "desktop-1",
            ["browser"],
            "ws://host:6080/websockify",
            {"hostname": "my-mac"},
        )

        assert upgraded is not None
        assert upgraded.agent_connected is True
        assert upgraded.capabilities == ["browser"]
        # Metadata should be merged (both os and hostname present)
        assert upgraded.metadata["os"] == "macos"
        assert upgraded.metadata["hostname"] == "my-mac"
        # Heartbeat should be reset (newer)
        assert upgraded.last_heartbeat >= old_heartbeat

    @pytest.mark.asyncio
    async def test_downgrade_to_desktop_only(self, registry: Registry):
        """Test downgrading a full agent worker to desktop-only."""
        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            capabilities=["browser"],
            novnc_url="ws://localhost:6080/websockify",
            metadata={"hostname": "my-mac"},
        )
        await registry.set_worker_status("worker-1", WorkerStatus.BUSY)

        downgraded = await registry.downgrade_to_desktop_only("worker-1")

        assert downgraded is not None
        assert downgraded.agent_connected is False
        assert downgraded.status == WorkerStatus.IDLE
        # Existing metadata should be preserved
        assert downgraded.metadata == {"hostname": "my-mac"}

    @pytest.mark.asyncio
    async def test_register_desktop_only_no_overwrite(self, registry: Registry):
        """Test that register_desktop_only does not overwrite an existing agent."""
        await registry.register(
            client_id="worker-1",
            client_type=ClientType.WORKER,
            capabilities=["browser"],
            novnc_url="ws://localhost:6080/websockify",
        )

        # Attempt to register the same ID as desktop-only
        conn = await registry.register_desktop_only(
            "worker-1",
            "ws://other:6080/websockify",
        )

        # The existing agent connection should be preserved
        assert conn.agent_connected is True
        assert conn.capabilities == ["browser"]

        stored = await registry.get_connection("worker-1")
        assert stored is not None
        assert stored.agent_connected is True

    @pytest.mark.asyncio
    async def test_update_desktop_only_basic(self, registry: Registry):
        """Test basic update of a desktop-only worker."""
        await registry.register_desktop_only(
            "desktop-1",
            "ws://host:6080/websockify",
            {"os": "linux"},
        )

        updated = await registry.update_desktop_only(
            "desktop-1",
            novnc_url="ws://newhost:6080/websockify",
            metadata={"os": "macos"},
        )

        assert updated is not None
        assert updated.novnc_url == "ws://newhost:6080/websockify"
        assert updated.metadata == {"os": "macos"}

    @pytest.mark.asyncio
    async def test_update_desktop_only_rename(self, registry: Registry):
        """Test renaming a desktop-only worker re-keys in registry."""
        await registry.register_desktop_only(
            "desktop-1",
            "ws://host:6080/websockify",
            {"os": "linux"},
        )

        updated = await registry.update_desktop_only(
            "desktop-1",
            new_client_id="desktop-renamed",
        )

        assert updated is not None
        assert updated.client_id == "desktop-renamed"

        # Old key should be gone
        old = await registry.get_connection("desktop-1")
        assert old is None

        # New key should exist
        new = await registry.get_connection("desktop-renamed")
        assert new is not None
        assert new.client_id == "desktop-renamed"

    @pytest.mark.asyncio
    async def test_update_desktop_only_not_found(self, registry: Registry):
        """Test update returns None for non-existent worker."""
        result = await registry.update_desktop_only(
            "nonexistent",
            novnc_url="ws://host:6080/websockify",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_update_desktop_only_partial(self, registry: Registry):
        """Test partial update only changes specified fields."""
        await registry.register_desktop_only(
            "desktop-1",
            "ws://host:6080/websockify",
            {"os": "linux"},
        )

        updated = await registry.update_desktop_only(
            "desktop-1",
            novnc_url="ws://newhost:6080/websockify",
        )

        assert updated is not None
        assert updated.novnc_url == "ws://newhost:6080/websockify"
        # Metadata should be unchanged since we didn't pass it
        assert updated.metadata == {"os": "linux"}
