"""Tests for the notify_on_complete gateway notification feature."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from figaro.models.scheduled_task import ScheduledTask
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
    settings.self_healing_enabled = False
    settings.self_healing_max_retries = 0
    return settings


@pytest.fixture
def nats_service(
    registry, task_manager, mock_scheduler, mock_help_request_manager, mock_settings
):
    from figaro.services.nats_service import NatsService

    service = NatsService(
        registry=registry,
        task_manager=task_manager,
        scheduler=mock_scheduler,
        help_request_manager=mock_help_request_manager,
        settings=mock_settings,
        session_factory=MagicMock(),
    )

    mock_conn = MagicMock()
    mock_conn.publish = AsyncMock()
    mock_conn.is_connected = True
    service._conn = mock_conn

    return service


def _make_task_model(
    *,
    source="scheduler",
    scheduled_task_id="sched-1",
    prompt="Run daily report",
):
    model = MagicMock()
    model.source = source
    model.scheduled_task_id = scheduled_task_id
    model.prompt = prompt
    return model


def _make_scheduled_task(
    schedule_id="sched-1",
    name="Daily Report",
    notify_on_complete=True,
):
    return ScheduledTask(
        schedule_id=schedule_id,
        name=name,
        prompt="Run daily report",
        start_url="https://example.com",
        interval_seconds=86400,
        enabled=True,
        notify_on_complete=notify_on_complete,
    )


def _prepare_db_mocks(nats_service, mock_task_model):
    mock_repo = MagicMock()
    mock_repo.get = AsyncMock(return_value=mock_task_model)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    nats_service._session_factory = MagicMock(return_value=mock_session)
    return mock_repo


class TestMaybeNotifyGateway:
    """Tests for NatsService._maybe_notify_gateway."""

    @pytest.mark.asyncio
    async def test_sends_completion_notification(
        self, nats_service, mock_scheduler
    ):
        """When a scheduler task completes and notify_on_complete is True,
        a message is published to each registered gateway channel."""
        task_model = _make_task_model()
        mock_repo = _prepare_db_mocks(nats_service, task_model)

        mock_scheduler.get_scheduled_task.return_value = _make_scheduled_task(
            notify_on_complete=True,
        )

        nats_service._gateway_channels = {"telegram"}
        nats_service.publish_gateway_send = AsyncMock()

        with patch(
            "figaro.services.nats_service.TaskRepository", return_value=mock_repo
        ):
            await nats_service._maybe_notify_gateway(
                "task-1", result={"result": "Report generated successfully"}
            )

        nats_service.publish_gateway_send.assert_called_once_with(
            "telegram",
            {"chat_id": "", "text": "Scheduled task *Daily Report* completed:\nReport generated successfully"},
        )

    @pytest.mark.asyncio
    async def test_sends_error_notification(
        self, nats_service, mock_scheduler
    ):
        """When a scheduler task fails and notify_on_complete is True,
        a failure message is published to the gateway."""
        task_model = _make_task_model()
        mock_repo = _prepare_db_mocks(nats_service, task_model)

        mock_scheduler.get_scheduled_task.return_value = _make_scheduled_task(
            notify_on_complete=True,
        )

        nats_service._gateway_channels = {"telegram"}
        nats_service.publish_gateway_send = AsyncMock()

        with patch(
            "figaro.services.nats_service.TaskRepository", return_value=mock_repo
        ):
            await nats_service._maybe_notify_gateway(
                "task-1", error="Element not found"
            )

        nats_service.publish_gateway_send.assert_called_once_with(
            "telegram",
            {"chat_id": "", "text": "Scheduled task *Daily Report* failed:\nElement not found"},
        )

    @pytest.mark.asyncio
    async def test_skips_when_notify_on_complete_false(
        self, nats_service, mock_scheduler
    ):
        """No notification sent when notify_on_complete is False."""
        task_model = _make_task_model()
        mock_repo = _prepare_db_mocks(nats_service, task_model)

        mock_scheduler.get_scheduled_task.return_value = _make_scheduled_task(
            notify_on_complete=False,
        )

        nats_service._gateway_channels = {"telegram"}
        nats_service.publish_gateway_send = AsyncMock()

        with patch(
            "figaro.services.nats_service.TaskRepository", return_value=mock_repo
        ):
            await nats_service._maybe_notify_gateway(
                "task-1", result="done"
            )

        nats_service.publish_gateway_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_non_scheduler_tasks(
        self, nats_service, mock_scheduler
    ):
        """No notification sent for tasks not originating from the scheduler."""
        task_model = _make_task_model(source="api", scheduled_task_id=None)
        mock_repo = _prepare_db_mocks(nats_service, task_model)

        nats_service._gateway_channels = {"telegram"}
        nats_service.publish_gateway_send = AsyncMock()

        with patch(
            "figaro.services.nats_service.TaskRepository", return_value=mock_repo
        ):
            await nats_service._maybe_notify_gateway(
                "task-1", result="done"
            )

        mock_scheduler.get_scheduled_task.assert_not_called()
        nats_service.publish_gateway_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_gateway_channels(
        self, nats_service, mock_scheduler
    ):
        """No notification sent when no gateway channels are registered."""
        task_model = _make_task_model()
        mock_repo = _prepare_db_mocks(nats_service, task_model)

        mock_scheduler.get_scheduled_task.return_value = _make_scheduled_task(
            notify_on_complete=True,
        )

        nats_service._gateway_channels = set()
        nats_service.publish_gateway_send = AsyncMock()

        with patch(
            "figaro.services.nats_service.TaskRepository", return_value=mock_repo
        ):
            await nats_service._maybe_notify_gateway(
                "task-1", result="done"
            )

        nats_service.publish_gateway_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_notifies_multiple_channels(
        self, nats_service, mock_scheduler
    ):
        """Notification is sent to all registered gateway channels."""
        task_model = _make_task_model()
        mock_repo = _prepare_db_mocks(nats_service, task_model)

        mock_scheduler.get_scheduled_task.return_value = _make_scheduled_task(
            notify_on_complete=True,
        )

        nats_service._gateway_channels = {"telegram", "whatsapp"}
        nats_service.publish_gateway_send = AsyncMock()

        with patch(
            "figaro.services.nats_service.TaskRepository", return_value=mock_repo
        ):
            await nats_service._maybe_notify_gateway(
                "task-1", result="done"
            )

        assert nats_service.publish_gateway_send.call_count == 2
        called_channels = {
            call.args[0] for call in nats_service.publish_gateway_send.call_args_list
        }
        assert called_channels == {"telegram", "whatsapp"}


class TestGatewayChannelRegister:
    """Tests for NatsService._handle_gateway_channel_register."""

    @pytest.mark.asyncio
    async def test_registers_channel(self, nats_service):
        """Gateway channel registration adds channel to the set."""
        await nats_service._handle_gateway_channel_register(
            {"channel": "telegram", "status": "online"}
        )

        assert "telegram" in nats_service._gateway_channels

    @pytest.mark.asyncio
    async def test_registers_multiple_channels(self, nats_service):
        """Multiple channels can be registered."""
        await nats_service._handle_gateway_channel_register(
            {"channel": "telegram", "status": "online"}
        )
        await nats_service._handle_gateway_channel_register(
            {"channel": "whatsapp", "status": "online"}
        )

        assert nats_service._gateway_channels == {"telegram", "whatsapp"}

    @pytest.mark.asyncio
    async def test_ignores_empty_channel(self, nats_service):
        """Empty channel name is ignored."""
        await nats_service._handle_gateway_channel_register(
            {"channel": "", "status": "online"}
        )

        assert len(nats_service._gateway_channels) == 0
