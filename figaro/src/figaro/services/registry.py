import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from figaro.models import ClientType
from figaro.models.messages import WorkerStatus

logger = logging.getLogger(__name__)


@dataclass
class Connection:
    client_id: str
    client_type: ClientType
    status: WorkerStatus = WorkerStatus.IDLE
    capabilities: list[str] = field(default_factory=list)
    novnc_url: str | None = None
    vnc_username: str | None = None
    vnc_password: str | None = None
    last_heartbeat: float = field(default_factory=time.time)
    agent_connected: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class Registry:
    def __init__(self) -> None:
        self._connections: dict[str, Connection] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        client_id: str,
        client_type: ClientType,
        capabilities: list[str] | None = None,
        novnc_url: str | None = None,
        status: WorkerStatus = WorkerStatus.IDLE,
        metadata: dict[str, Any] | None = None,
        vnc_username: str | None = None,
        vnc_password: str | None = None,
    ) -> Connection:
        async with self._lock:
            connection = Connection(
                client_id=client_id,
                client_type=client_type,
                capabilities=capabilities or [],
                novnc_url=novnc_url,
                vnc_username=vnc_username,
                vnc_password=vnc_password,
                status=status,
                last_heartbeat=time.time(),
                metadata=metadata or {},
            )
            self._connections[client_id] = connection
            logger.info(f"Registered {client_type.value} client: {client_id}")
            return connection

    async def unregister(self, client_id: str) -> None:
        async with self._lock:
            if client_id in self._connections:
                conn = self._connections.pop(client_id)
                logger.info(
                    f"Unregistered {conn.client_type.value} client: {client_id}"
                )

    async def register_desktop_only(
        self,
        client_id: str,
        novnc_url: str,
        metadata: dict[str, Any] | None = None,
        vnc_username: str | None = None,
        vnc_password: str | None = None,
    ) -> Connection:
        """Register a desktop-only worker (no agent connected).

        If the worker already exists with an agent connected, the existing
        connection is preserved to avoid overwriting a full agent registration.
        """
        async with self._lock:
            existing = self._connections.get(client_id)
            if existing is not None and existing.agent_connected:
                logger.info(
                    f"Skipping desktop-only registration for {client_id}: "
                    "agent already connected"
                )
                return existing
            connection = Connection(
                client_id=client_id,
                client_type=ClientType.WORKER,
                capabilities=[],
                novnc_url=novnc_url,
                vnc_username=vnc_username,
                vnc_password=vnc_password,
                status=WorkerStatus.IDLE,
                last_heartbeat=time.time(),
                agent_connected=False,
                metadata=metadata or {},
            )
            self._connections[client_id] = connection
            logger.info(f"Registered desktop-only worker: {client_id}")
            return connection

    async def update_desktop_only(
        self,
        client_id: str,
        new_client_id: str | None = None,
        novnc_url: str | None = None,
        metadata: dict[str, Any] | None = None,
        vnc_username: str | None = None,
        vnc_password: str | None = None,
    ) -> Connection | None:
        """Update a desktop-only worker's properties.

        If new_client_id is provided, re-keys the connection in the dict.
        Returns None if the worker is not found.
        """
        async with self._lock:
            conn = self._connections.get(client_id)
            if conn is None:
                return None
            if novnc_url is not None:
                conn.novnc_url = novnc_url
            if vnc_username is not None:
                conn.vnc_username = vnc_username
            if vnc_password is not None:
                conn.vnc_password = vnc_password
            if metadata is not None:
                conn.metadata = metadata
            if new_client_id is not None and new_client_id != client_id:
                del self._connections[client_id]
                conn.client_id = new_client_id
                self._connections[new_client_id] = conn
            logger.info(f"Updated desktop-only worker: {client_id}")
            return conn

    async def upgrade_to_agent(
        self,
        client_id: str,
        capabilities: list[str],
        novnc_url: str,
        metadata: dict[str, Any] | None = None,
    ) -> Connection | None:
        """Upgrade a desktop-only worker to a full agent worker."""
        async with self._lock:
            conn = self._connections.get(client_id)
            if conn is None:
                return None
            conn.agent_connected = True
            conn.capabilities = capabilities
            conn.novnc_url = novnc_url
            conn.last_heartbeat = time.time()
            if metadata:
                conn.metadata.update(metadata)
            logger.info(f"Upgraded worker {client_id} to agent")
            return conn

    async def downgrade_to_desktop_only(self, client_id: str) -> Connection | None:
        """Downgrade a worker to desktop-only (no agent)."""
        async with self._lock:
            conn = self._connections.get(client_id)
            if conn is None:
                return None
            conn.agent_connected = False
            conn.status = WorkerStatus.IDLE
            logger.info(f"Downgraded worker {client_id} to desktop-only")
            return conn

    async def get_connection(self, client_id: str) -> Connection | None:
        async with self._lock:
            return self._connections.get(client_id)

    async def set_worker_status(self, worker_id: str, status: WorkerStatus) -> None:
        async with self._lock:
            if worker_id in self._connections:
                self._connections[worker_id].status = status
                logger.debug(f"Worker {worker_id} status: {status.value}")

    async def update_heartbeat(
        self, client_id: str, status: WorkerStatus | None = None
    ) -> None:
        """Update the last heartbeat timestamp for a client."""
        async with self._lock:
            if client_id in self._connections:
                self._connections[client_id].last_heartbeat = time.time()
                if status is not None:
                    self._connections[client_id].status = status

    async def check_heartbeats(self, timeout: int = 90) -> list[str]:
        """Return list of client IDs that have timed out.

        Desktop-only workers (agent_connected=False) are skipped since
        they don't send heartbeats.
        """
        now = time.time()
        timed_out: list[str] = []
        async with self._lock:
            for client_id, conn in self._connections.items():
                if conn.agent_connected is False:
                    continue
                if now - conn.last_heartbeat > timeout:
                    timed_out.append(client_id)
        return timed_out

    async def get_workers(self) -> list[Connection]:
        async with self._lock:
            return [
                conn
                for conn in self._connections.values()
                if conn.client_type == ClientType.WORKER
            ]

    async def get_ui_clients(self) -> list[Connection]:
        async with self._lock:
            return [
                conn
                for conn in self._connections.values()
                if conn.client_type == ClientType.UI
            ]

    async def get_idle_worker(self) -> Connection | None:
        """Get an idle worker without claiming it."""
        async with self._lock:
            for conn in self._connections.values():
                if (
                    conn.client_type == ClientType.WORKER
                    and conn.status == WorkerStatus.IDLE
                    and conn.agent_connected
                ):
                    return conn
            return None

    async def claim_idle_worker(self) -> Connection | None:
        """Atomically find and claim an idle worker by setting status to BUSY.

        This prevents race conditions where multiple tasks could be assigned
        to the same worker. Desktop-only workers (agent_connected=False)
        are never claimed.
        """
        async with self._lock:
            for conn in self._connections.values():
                if (
                    conn.client_type == ClientType.WORKER
                    and conn.status == WorkerStatus.IDLE
                    and conn.agent_connected
                ):
                    conn.status = WorkerStatus.BUSY
                    logger.info(f"Claimed worker {conn.client_id} (now BUSY)")
                    return conn
            return None

    # Supervisor methods

    async def get_supervisors(self) -> list[Connection]:
        """Get all connected supervisors."""
        async with self._lock:
            return [
                conn
                for conn in self._connections.values()
                if conn.client_type == ClientType.SUPERVISOR
            ]

    async def get_idle_supervisor(self) -> Connection | None:
        """Get an idle supervisor without claiming it."""
        async with self._lock:
            for conn in self._connections.values():
                if (
                    conn.client_type == ClientType.SUPERVISOR
                    and conn.status == WorkerStatus.IDLE
                ):
                    return conn
            return None

    async def claim_idle_supervisor(self) -> Connection | None:
        """Atomically find and claim an idle supervisor by setting status to BUSY."""
        async with self._lock:
            for conn in self._connections.values():
                if (
                    conn.client_type == ClientType.SUPERVISOR
                    and conn.status == WorkerStatus.IDLE
                ):
                    conn.status = WorkerStatus.BUSY
                    logger.info(f"Claimed supervisor {conn.client_id} (now BUSY)")
                    return conn
            return None
