"""Tests for the self-learning optimization feature in NatsService."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from figaro.models import ClientType
from figaro.models.messages import WorkerStatus
from figaro.models.scheduled_task import ScheduledTask
from figaro.services import Registry, TaskManager
from figaro.services.task_manager import TaskStatus


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
    return settings


def _mock_session_factory(mock_repo):
    """Create a mock session factory wired to a given repository mock.

    The factory returns an async context manager (the session) and, inside that
    session, the TaskRepository constructor is patched to return *mock_repo*.
    """
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock(return_value=mock_session)
    return factory


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

    # Mock the NATS connection so publish_supervisor_task works
    mock_conn = MagicMock()
    mock_conn.publish = AsyncMock()
    mock_conn.is_connected = True
    service._conn = mock_conn

    return service


def _make_scheduled_task(schedule_id="sched-1", self_learning=True):
    """Helper to create a ScheduledTask with defaults."""
    return ScheduledTask(
        schedule_id=schedule_id,
        name="Daily Report",
        prompt="Generate the daily report",
        start_url="https://example.com",
        interval_seconds=86400,
        enabled=True,
        self_learning=self_learning,
    )


def _prepare_db_mocks(nats_service, mock_task_model):
    """Wire a mock session factory + TaskRepository into the service.

    Returns the mock_repo so callers can add further assertions.
    """
    mock_repo = MagicMock()
    mock_repo.get = AsyncMock(return_value=mock_task_model)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    nats_service._session_factory = MagicMock(return_value=mock_session)
    return mock_repo


class TestMaybeOptimizeScheduledTask:
    """Tests for NatsService._maybe_optimize_scheduled_task."""

    @pytest.mark.asyncio
    async def test_optimize_scheduled_task_creates_optimization_task(
        self, nats_service, task_manager, registry, mock_scheduler
    ):
        """When a completed task has scheduled_task_id, source='scheduler', and
        the scheduled task has self_learning=True with an idle supervisor available,
        an optimization task should be created and assigned to the supervisor."""

        # 1. Create and complete the original task in-memory
        original_task = await task_manager.create_task(
            prompt="Generate the daily report",
            source="scheduler",
            scheduled_task_id="sched-1",
        )
        await task_manager.append_message(
            original_task.task_id, {"type": "assistant", "content": "Report generated"}
        )
        await task_manager.complete_task(original_task.task_id, result="Done")

        # 2. Mock the DB layer
        mock_task_model = MagicMock()
        mock_task_model.scheduled_task_id = "sched-1"
        mock_task_model.source = "scheduler"
        mock_repo = _prepare_db_mocks(nats_service, mock_task_model)

        # 3. Set up scheduled task with self_learning=True
        scheduled_task = _make_scheduled_task(schedule_id="sched-1", self_learning=True)
        mock_scheduler.get_scheduled_task = AsyncMock(return_value=scheduled_task)

        # 4. Register an idle supervisor
        await registry.register(
            client_id="supervisor-1",
            client_type=ClientType.SUPERVISOR,
            status=WorkerStatus.IDLE,
        )

        # 5. Spy on publish_supervisor_task
        nats_service.publish_supervisor_task = AsyncMock()

        # 6. Run the method under test
        with patch(
            "figaro.db.repositories.tasks.TaskRepository", return_value=mock_repo
        ):
            await nats_service._maybe_optimize_scheduled_task(original_task.task_id)

        # 7. Verify an optimization task was created
        all_tasks = await task_manager.get_all_tasks()
        optimization_tasks = [t for t in all_tasks if t.source == "optimizer"]
        assert len(optimization_tasks) == 1

        opt_task = optimization_tasks[0]
        assert "optimiz" in opt_task.prompt.lower()
        assert scheduled_task.schedule_id in opt_task.prompt
        assert opt_task.status == TaskStatus.ASSIGNED

        # 8. Verify the supervisor was assigned
        nats_service.publish_supervisor_task.assert_called_once_with(
            "supervisor-1", opt_task
        )

    @pytest.mark.asyncio
    async def test_optimize_skipped_when_self_learning_disabled(
        self, nats_service, task_manager, mock_scheduler
    ):
        """When the scheduled task has self_learning=False, no optimization
        task should be created."""

        # 1. Create the original task
        original_task = await task_manager.create_task(
            prompt="Generate the daily report",
            source="scheduler",
            scheduled_task_id="sched-1",
        )
        await task_manager.append_message(
            original_task.task_id, {"type": "assistant", "content": "Report generated"}
        )

        # 2. Mock DB layer
        mock_task_model = MagicMock()
        mock_task_model.scheduled_task_id = "sched-1"
        mock_task_model.source = "scheduler"
        mock_repo = _prepare_db_mocks(nats_service, mock_task_model)

        # 3. Scheduled task with self_learning=False
        scheduled_task = _make_scheduled_task(schedule_id="sched-1", self_learning=False)
        mock_scheduler.get_scheduled_task = AsyncMock(return_value=scheduled_task)

        # 4. Run
        with patch(
            "figaro.db.repositories.tasks.TaskRepository", return_value=mock_repo
        ):
            await nats_service._maybe_optimize_scheduled_task(original_task.task_id)

        # 5. Verify no optimization task was created
        all_tasks = await task_manager.get_all_tasks()
        optimization_tasks = [t for t in all_tasks if t.source == "optimizer"]
        assert len(optimization_tasks) == 0

    @pytest.mark.asyncio
    async def test_optimize_skipped_when_no_scheduled_task_id(
        self, nats_service, task_manager, mock_scheduler
    ):
        """When the task has no scheduled_task_id, the method should return
        early without doing anything."""

        # 1. Create a task without a scheduled_task_id
        original_task = await task_manager.create_task(
            prompt="One-off task",
            source="api",
        )

        # 2. Mock DB repo to return model without scheduled_task_id
        mock_task_model = MagicMock()
        mock_task_model.scheduled_task_id = None
        mock_task_model.source = "api"
        mock_repo = _prepare_db_mocks(nats_service, mock_task_model)

        # 3. Run
        with patch(
            "figaro.db.repositories.tasks.TaskRepository", return_value=mock_repo
        ):
            await nats_service._maybe_optimize_scheduled_task(original_task.task_id)

        # 4. Verify scheduler was never consulted
        mock_scheduler.get_scheduled_task.assert_not_called()

        # 5. Verify no optimization task was created
        all_tasks = await task_manager.get_all_tasks()
        optimization_tasks = [t for t in all_tasks if t.source == "optimizer"]
        assert len(optimization_tasks) == 0

    @pytest.mark.asyncio
    async def test_optimize_skipped_when_no_supervisor(
        self, nats_service, task_manager, registry, mock_scheduler
    ):
        """When self_learning is enabled but no idle supervisor is available,
        the method should log a warning and not crash."""

        # 1. Create and complete the original task
        original_task = await task_manager.create_task(
            prompt="Generate the daily report",
            source="scheduler",
            scheduled_task_id="sched-1",
        )
        await task_manager.append_message(
            original_task.task_id, {"type": "assistant", "content": "Report generated"}
        )
        await task_manager.complete_task(original_task.task_id, result="Done")

        # 2. Mock DB layer
        mock_task_model = MagicMock()
        mock_task_model.scheduled_task_id = "sched-1"
        mock_task_model.source = "scheduler"
        mock_repo = _prepare_db_mocks(nats_service, mock_task_model)

        # 3. Scheduled task with self_learning=True
        scheduled_task = _make_scheduled_task(schedule_id="sched-1", self_learning=True)
        mock_scheduler.get_scheduled_task = AsyncMock(return_value=scheduled_task)

        # 4. No supervisors registered (registry is empty)

        # 5. Run -- should not raise
        with patch(
            "figaro.db.repositories.tasks.TaskRepository", return_value=mock_repo
        ):
            await nats_service._maybe_optimize_scheduled_task(original_task.task_id)

        # 6. Verify an optimization task was still created (it gets created before assignment)
        all_tasks = await task_manager.get_all_tasks()
        optimization_tasks = [t for t in all_tasks if t.source == "optimizer"]
        assert len(optimization_tasks) == 1

        # 7. But it was NOT assigned (no supervisor), so status stays PENDING
        opt_task = optimization_tasks[0]
        assert opt_task.status == TaskStatus.PENDING
