"""Tests for the _api_vnc handler in NatsService."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager

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
    settings.vnc_port = 5901
    settings.vnc_username = None
    settings.vnc_password = "vscode"
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

    # Mock the NATS connection
    mock_conn = MagicMock()
    mock_conn.publish = AsyncMock()
    mock_conn.is_connected = True
    service._conn = mock_conn

    return service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_pool_connection(mock_client, captured=None):
    """Create a mock pool.connection() context manager that yields mock_client.

    If *captured* is a dict, the host/port/username/password arguments are
    stored in it so tests can inspect what the handler passed.
    """
    @asynccontextmanager
    async def _connection(host, port, username=None, password=None):
        if captured is not None:
            captured["host"] = host
            captured["port"] = port
            captured["username"] = username
            captured["password"] = password
        yield mock_client
    return _connection


def _mock_pool_ws_connection(mock_client, captured=None):
    """Create a mock pool.ws_connection() context manager that yields mock_client.

    If *captured* is a dict, the url/username/password arguments are stored in
    it so tests can inspect what the handler passed.
    """
    @asynccontextmanager
    async def _ws_connection(url, username=None, password=None):
        if captured is not None:
            captured["url"] = url
            captured["username"] = username
            captured["password"] = password
        yield mock_client
    return _ws_connection


async def _register_worker(registry: Registry, worker_id: str = "worker-1") -> None:
    """Register a mock worker with a noVNC URL in the registry."""
    await registry.register(
        client_id=worker_id,
        client_type=ClientType.WORKER,
        novnc_url="ws://worker-1-host:6080/websockify",
        status=WorkerStatus.IDLE,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestApiVncWorkerNotFound:
    """Test _api_vnc returns error when worker is not registered."""

    async def test_api_vnc_worker_not_found(self, nats_service):
        result = await nats_service._api_vnc(
            {"worker_id": "nonexistent", "action": "screenshot"}
        )
        assert result == {"error": "Worker not found"}


class TestApiVncScreenshot:
    """Test _api_vnc screenshot action."""

    async def test_api_vnc_screenshot(self, nats_service, registry):
        await _register_worker(registry)
        mock_client = MagicMock()
        nats_service._vnc_pool.connection = _mock_pool_connection(mock_client)

        with patch(
            "figaro.services.nats_service.screenshot_with_client",
            new_callable=AsyncMock,
            return_value=("base64data", "image/jpeg", 1920, 1080, 1280, 720),
        ) as mock_screenshot:
            result = await nats_service._api_vnc(
                {"worker_id": "worker-1", "action": "screenshot"}
            )

        assert result == {
            "image": "base64data",
            "mime_type": "image/jpeg",
            "original_width": 1920,
            "original_height": 1080,
            "width": 1280,
            "height": 720,
        }
        mock_screenshot.assert_awaited_once_with(
            mock_client, 70, None, None,
        )


class TestApiVncType:
    """Test _api_vnc type action."""

    async def test_api_vnc_type(self, nats_service, registry):
        await _register_worker(registry)
        mock_client = MagicMock()
        nats_service._vnc_pool.connection = _mock_pool_connection(mock_client)

        with patch(
            "figaro.services.nats_service.type_with_client",
            new_callable=AsyncMock,
        ) as mock_type:
            result = await nats_service._api_vnc(
                {"worker_id": "worker-1", "action": "type", "text": "hello"}
            )

        assert result == {"ok": True}
        mock_type.assert_awaited_once_with(mock_client, "hello")


class TestApiVncKey:
    """Test _api_vnc key action."""

    async def test_api_vnc_key(self, nats_service, registry):
        await _register_worker(registry)
        mock_client = MagicMock()
        nats_service._vnc_pool.connection = _mock_pool_connection(mock_client)

        with patch(
            "figaro.services.nats_service.key_with_client",
            new_callable=AsyncMock,
        ) as mock_key:
            result = await nats_service._api_vnc(
                {"worker_id": "worker-1", "action": "key", "key": "Return"}
            )

        assert result == {"ok": True}
        mock_key.assert_awaited_once_with(mock_client, "Return", None, hold_seconds=None)


class TestApiVncClick:
    """Test _api_vnc click action."""

    async def test_api_vnc_click(self, nats_service, registry):
        await _register_worker(registry)
        mock_client = MagicMock()
        nats_service._vnc_pool.connection = _mock_pool_connection(mock_client)

        with patch(
            "figaro.services.nats_service.click_with_client",
            new_callable=AsyncMock,
        ) as mock_click:
            result = await nats_service._api_vnc(
                {
                    "worker_id": "worker-1",
                    "action": "click",
                    "x": 100,
                    "y": 200,
                    "button": "left",
                }
            )

        assert result == {"ok": True}
        mock_click.assert_awaited_once_with(mock_client, 100, 200, "left")


class TestApiVncUnknownAction:
    """Test _api_vnc returns error for unknown actions."""

    async def test_api_vnc_unknown_action(self, nats_service, registry):
        await _register_worker(registry)
        mock_client = MagicMock()
        nats_service._vnc_pool.connection = _mock_pool_connection(mock_client)

        result = await nats_service._api_vnc(
            {"worker_id": "worker-1", "action": "scroll"}
        )

        assert result == {"error": "Unknown action: scroll"}


class TestApiVncConnectionError:
    """Test _api_vnc returns error when a VNC function raises an exception."""

    async def test_api_vnc_connection_error(self, nats_service, registry):
        await _register_worker(registry)

        @asynccontextmanager
        async def _broken_connection(host, port, username=None, password=None):
            raise ConnectionRefusedError("Connection refused")
            yield  # noqa: F841 — required for asynccontextmanager

        nats_service._vnc_pool.connection = _broken_connection

        result = await nats_service._api_vnc(
            {"worker_id": "worker-1", "action": "screenshot"}
        )

        assert "error" in result
        assert "Connection refused" in result["error"]


class TestApiVncCredentialFallback:
    """Test _api_vnc credential and port resolution from URLs."""

    async def test_port_from_url(self, nats_service, registry):
        """Port should be extracted from the novnc_url, not the global setting."""
        await registry.register(
            client_id="mac-1",
            client_type=ClientType.WORKER,
            novnc_url="vnc://mac-host:5900",
            status=WorkerStatus.IDLE,
        )

        mock_client = MagicMock()
        captured = {}

        @asynccontextmanager
        async def _capture_connection(host, port, username=None, password=None):
            captured["host"] = host
            captured["port"] = port
            captured["username"] = username
            captured["password"] = password
            yield mock_client

        nats_service._vnc_pool.connection = _capture_connection

        with patch(
            "figaro.services.nats_service.screenshot_with_client",
            new_callable=AsyncMock,
            return_value=("img", "image/jpeg", 1920, 1080, 1920, 1080),
        ):
            await nats_service._api_vnc(
                {"worker_id": "mac-1", "action": "screenshot"}
            )

        # Port 5900 from the URL, not 5901 from settings
        assert captured["host"] == "mac-host"
        assert captured["port"] == 5900

    async def test_credentials_from_url(self, nats_service, registry, mock_settings):
        """Credentials embedded in the URL are used as fallback."""
        mock_settings.vnc_password = None
        mock_settings.vnc_username = None
        await registry.register(
            client_id="mac-2",
            client_type=ClientType.WORKER,
            novnc_url="vnc://admin:secret@mac-host:5900",
            status=WorkerStatus.IDLE,
        )

        mock_client = MagicMock()
        captured = {}

        @asynccontextmanager
        async def _capture_connection(host, port, username=None, password=None):
            captured["host"] = host
            captured["port"] = port
            captured["username"] = username
            captured["password"] = password
            yield mock_client

        nats_service._vnc_pool.connection = _capture_connection

        with patch(
            "figaro.services.nats_service.screenshot_with_client",
            new_callable=AsyncMock,
            return_value=("img", "image/jpeg", 1920, 1080, 1920, 1080),
        ):
            await nats_service._api_vnc(
                {"worker_id": "mac-2", "action": "screenshot"}
            )

        assert captured["username"] == "admin"
        assert captured["password"] == "secret"

    async def test_per_worker_credentials_override_url(self, nats_service, registry, mock_settings):
        """Per-worker vnc_username/vnc_password fields take priority over URL creds."""
        mock_settings.vnc_password = None
        mock_settings.vnc_username = None
        await registry.register(
            client_id="mac-3",
            client_type=ClientType.WORKER,
            novnc_url="vnc://url-user:url-pass@mac-host:5900",
            vnc_username="override-user",
            vnc_password="override-pass",
            status=WorkerStatus.IDLE,
        )

        mock_client = MagicMock()
        captured = {}

        @asynccontextmanager
        async def _capture_connection(host, port, username=None, password=None):
            captured["username"] = username
            captured["password"] = password
            yield mock_client

        nats_service._vnc_pool.connection = _capture_connection

        with patch(
            "figaro.services.nats_service.screenshot_with_client",
            new_callable=AsyncMock,
            return_value=("img", "image/jpeg", 1920, 1080, 1920, 1080),
        ):
            await nats_service._api_vnc(
                {"worker_id": "mac-3", "action": "screenshot"}
            )

        assert captured["username"] == "override-user"
        assert captured["password"] == "override-pass"


class TestApiVncWsSchemeRouting:
    """Test that ws:// URLs use pool.connection() with settings.vnc_port."""

    async def test_ws_uses_settings_vnc_port(self, nats_service, registry, mock_settings):
        """ws:// URL should route through pool.connection() using settings.vnc_port."""
        await _register_worker(registry)

        mock_client = MagicMock()
        captured = {}
        nats_service._vnc_pool.connection = _mock_pool_connection(mock_client, captured)

        with patch(
            "figaro.services.nats_service.screenshot_with_client",
            new_callable=AsyncMock,
            return_value=("img", "image/jpeg", 1920, 1080, 1920, 1080),
        ):
            result = await nats_service._api_vnc(
                {"worker_id": "worker-1", "action": "screenshot"}
            )

        assert result["image"] == "img"
        # Host extracted from ws:// URL
        assert captured["host"] == "worker-1-host"
        # Port comes from settings.vnc_port (5901), NOT the websockify port (6080)
        assert captured["port"] == mock_settings.vnc_port
        assert captured["port"] == 5901


class TestApiVncWssSchemeRouting:
    """Test that wss:// URLs use pool.ws_connection() with the full URL."""

    async def test_wss_uses_ws_connection(self, nats_service, registry):
        """wss:// URL should route through pool.ws_connection() with full URL."""
        wss_url = "wss://worker-host:443/websockify"
        await registry.register(
            client_id="wss-worker",
            client_type=ClientType.WORKER,
            novnc_url=wss_url,
            status=WorkerStatus.IDLE,
        )

        mock_client = MagicMock()
        captured = {}
        nats_service._vnc_pool.ws_connection = _mock_pool_ws_connection(
            mock_client, captured,
        )

        with patch(
            "figaro.services.nats_service.screenshot_with_client",
            new_callable=AsyncMock,
            return_value=("img", "image/jpeg", 1920, 1080, 1920, 1080),
        ):
            result = await nats_service._api_vnc(
                {"worker_id": "wss-worker", "action": "screenshot"}
            )

        assert result["image"] == "img"
        # Full URL passed to ws_connection
        assert captured["url"] == wss_url

    async def test_wss_does_not_call_tcp_connection(self, nats_service, registry):
        """wss:// URL should NOT call pool.connection() (TCP)."""
        wss_url = "wss://worker-host:443/websockify"
        await registry.register(
            client_id="wss-worker-2",
            client_type=ClientType.WORKER,
            novnc_url=wss_url,
            status=WorkerStatus.IDLE,
        )

        mock_client = MagicMock()
        nats_service._vnc_pool.ws_connection = _mock_pool_ws_connection(mock_client)

        tcp_called = False
        original_connection = nats_service._vnc_pool.connection

        @asynccontextmanager
        async def _spy_connection(host, port, username=None, password=None):
            nonlocal tcp_called
            tcp_called = True
            async with original_connection(host, port, username=username, password=password) as c:
                yield c

        nats_service._vnc_pool.connection = _spy_connection

        with patch(
            "figaro.services.nats_service.screenshot_with_client",
            new_callable=AsyncMock,
            return_value=("img", "image/jpeg", 1920, 1080, 1920, 1080),
        ):
            await nats_service._api_vnc(
                {"worker_id": "wss-worker-2", "action": "screenshot"}
            )

        assert not tcp_called, "pool.connection() should not be called for wss:// URLs"

    async def test_wss_passes_credentials(self, nats_service, registry, mock_settings):
        """wss:// should forward resolved credentials to ws_connection()."""
        mock_settings.vnc_password = "global-pass"
        mock_settings.vnc_username = None
        wss_url = "wss://worker-host:443/websockify"
        await registry.register(
            client_id="wss-worker-3",
            client_type=ClientType.WORKER,
            novnc_url=wss_url,
            status=WorkerStatus.IDLE,
        )

        mock_client = MagicMock()
        captured = {}
        nats_service._vnc_pool.ws_connection = _mock_pool_ws_connection(
            mock_client, captured,
        )

        with patch(
            "figaro.services.nats_service.screenshot_with_client",
            new_callable=AsyncMock,
            return_value=("img", "image/jpeg", 1920, 1080, 1920, 1080),
        ):
            await nats_service._api_vnc(
                {"worker_id": "wss-worker-3", "action": "screenshot"}
            )

        assert captured["password"] == "global-pass"
        assert captured["username"] is None


class TestApiVncVncSchemeRouting:
    """Test that vnc:// URLs use pool.connection() with port from URL."""

    async def test_vnc_uses_port_from_url(self, nats_service, registry, mock_settings):
        """vnc:// URL should route through pool.connection() with port from URL."""
        await registry.register(
            client_id="vnc-worker",
            client_type=ClientType.WORKER,
            novnc_url="vnc://worker-host:5900",
            status=WorkerStatus.IDLE,
        )

        mock_client = MagicMock()
        captured = {}
        nats_service._vnc_pool.connection = _mock_pool_connection(mock_client, captured)

        with patch(
            "figaro.services.nats_service.screenshot_with_client",
            new_callable=AsyncMock,
            return_value=("img", "image/jpeg", 1920, 1080, 1920, 1080),
        ):
            result = await nats_service._api_vnc(
                {"worker_id": "vnc-worker", "action": "screenshot"}
            )

        assert result["image"] == "img"
        assert captured["host"] == "worker-host"
        # Port 5900 from the URL, NOT 5901 from settings.vnc_port
        assert captured["port"] == 5900
        assert captured["port"] != mock_settings.vnc_port

    async def test_vnc_does_not_call_ws_connection(self, nats_service, registry):
        """vnc:// URL should NOT call pool.ws_connection()."""
        await registry.register(
            client_id="vnc-worker-2",
            client_type=ClientType.WORKER,
            novnc_url="vnc://worker-host:5900",
            status=WorkerStatus.IDLE,
        )

        mock_client = MagicMock()
        nats_service._vnc_pool.connection = _mock_pool_connection(mock_client)

        ws_called = False

        @asynccontextmanager
        async def _spy_ws_connection(url, username=None, password=None):
            nonlocal ws_called
            ws_called = True
            yield mock_client

        nats_service._vnc_pool.ws_connection = _spy_ws_connection

        with patch(
            "figaro.services.nats_service.screenshot_with_client",
            new_callable=AsyncMock,
            return_value=("img", "image/jpeg", 1920, 1080, 1920, 1080),
        ):
            await nats_service._api_vnc(
                {"worker_id": "vnc-worker-2", "action": "screenshot"}
            )

        assert not ws_called, "pool.ws_connection() should not be called for vnc:// URLs"

    async def test_vnc_default_port_when_not_specified(self, nats_service, registry):
        """vnc:// URL without explicit port should default to 5900."""
        await registry.register(
            client_id="vnc-worker-3",
            client_type=ClientType.WORKER,
            novnc_url="vnc://worker-host",
            status=WorkerStatus.IDLE,
        )

        mock_client = MagicMock()
        captured = {}
        nats_service._vnc_pool.connection = _mock_pool_connection(mock_client, captured)

        with patch(
            "figaro.services.nats_service.screenshot_with_client",
            new_callable=AsyncMock,
            return_value=("img", "image/jpeg", 1920, 1080, 1920, 1080),
        ):
            await nats_service._api_vnc(
                {"worker_id": "vnc-worker-3", "action": "screenshot"}
            )

        # parse_vnc_url defaults to 5900 for vnc:// when no port given
        assert captured["host"] == "worker-host"
        assert captured["port"] == 5900
