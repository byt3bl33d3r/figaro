"""Tests for the self-healing feature in NatsService."""

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
    settings.self_healing_enabled = True
    settings.self_healing_max_retries = 2
    return settings


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
    mock_conn.request = AsyncMock(return_value={"status": "ok"})
    mock_conn.js_publish = AsyncMock()
    mock_conn.is_connected = True
    service._conn = mock_conn

    return service


def _make_scheduled_task(
    schedule_id="sched-1",
    self_healing=True,
    self_learning=False,
    self_learning_max_runs=None,
    self_learning_run_count=0,
):
    """Helper to create a ScheduledTask with defaults."""
    return ScheduledTask(
        schedule_id=schedule_id,
        name="Daily Report",
        prompt="Generate the daily report",
        start_url="https://example.com",
        interval_seconds=86400,
        enabled=True,
        self_healing=self_healing,
        self_learning=self_learning,
        self_learning_max_runs=self_learning_max_runs,
        self_learning_run_count=self_learning_run_count,
    )


def _make_failed_task_model(
    *,
    source="api",
    scheduled_task_id=None,
    options=None,
    source_metadata=None,
    result=None,
    prompt="Do something",
):
    """Helper to create a mock TaskModel for a failed task."""
    mock_task_model = MagicMock()
    mock_task_model.source = source
    mock_task_model.scheduled_task_id = scheduled_task_id
    mock_task_model.options = options or {}
    mock_task_model.source_metadata = source_metadata or {}
    mock_task_model.result = result or {"error": "Element not found"}
    mock_task_model.prompt = prompt
    return mock_task_model


class TestMaybeHealFailedTask:
    """Tests for NatsService._maybe_heal_failed_task."""

    @pytest.mark.asyncio
    async def test_healing_creates_healer_task(
        self, nats_service, task_manager, registry, mock_settings
    ):
        """When a task fails with healing enabled and a supervisor is available,
        a healer task is created with source='healer' and assigned to the supervisor."""

        # 1. Create and fail the original task
        original_task = await task_manager.create_task(
            prompt="Do something on the website",
            source="api",
            options={"self_healing": True},
        )
        await task_manager.append_message(
            original_task.task_id,
            {"type": "assistant", "content": "Trying to click button"},
        )
        await task_manager.fail_task(original_task.task_id, "Element not found")

        # 2. Mock the DB layer
        mock_task_model = _make_failed_task_model(
            source="api",
            options={"self_healing": True},
            prompt="Do something on the website",
        )
        mock_repo = _prepare_db_mocks(nats_service, mock_task_model)

        # 3. Register an idle supervisor
        await registry.register(
            client_id="supervisor-1",
            client_type=ClientType.SUPERVISOR,
            status=WorkerStatus.IDLE,
        )

        # 4. Spy on publish_supervisor_task
        nats_service.publish_supervisor_task = AsyncMock()

        # 5. Run the method under test
        with patch(
            "figaro.services.nats_service.TaskRepository", return_value=mock_repo
        ):
            await nats_service._maybe_heal_failed_task(original_task.task_id)

        # 6. Verify a healer task was created
        all_tasks = await task_manager.get_all_tasks()
        healer_tasks = [t for t in all_tasks if t.source == "healer"]
        assert len(healer_tasks) == 1

        healer_task = healer_tasks[0]
        assert healer_task.source == "healer"
        assert healer_task.status == TaskStatus.ASSIGNED

        # 7. Verify the supervisor was assigned
        nats_service.publish_supervisor_task.assert_called_once_with(
            "supervisor-1", healer_task
        )

    @pytest.mark.asyncio
    async def test_healing_skipped_when_disabled(
        self, nats_service, task_manager, mock_settings
    ):
        """When self_healing is disabled (via task options), no healer task is created."""

        # 1. Create and fail the original task
        original_task = await task_manager.create_task(
            prompt="Do something",
            source="api",
            options={"self_healing": False},
        )
        await task_manager.fail_task(original_task.task_id, "Some error")

        # 2. Mock the DB layer with healing disabled in options
        mock_task_model = _make_failed_task_model(
            source="api",
            options={"self_healing": False},
        )
        mock_repo = _prepare_db_mocks(nats_service, mock_task_model)

        # 3. Also disable system-wide setting to ensure no fallback
        mock_settings.self_healing_enabled = False

        # 4. Run
        with patch(
            "figaro.services.nats_service.TaskRepository", return_value=mock_repo
        ):
            await nats_service._maybe_heal_failed_task(original_task.task_id)

        # 5. Verify no healer task was created
        all_tasks = await task_manager.get_all_tasks()
        healer_tasks = [t for t in all_tasks if t.source == "healer"]
        assert len(healer_tasks) == 0

    @pytest.mark.asyncio
    async def test_healing_skipped_for_healer_source(
        self, nats_service, task_manager
    ):
        """Tasks with source='healer' are never themselves healed (loop prevention)."""

        # 1. Create a healer task that itself failed
        healer_task = await task_manager.create_task(
            prompt="Heal the failed task",
            source="healer",
            source_metadata={"original_task_id": "orig-1", "retry_number": 1},
        )
        await task_manager.fail_task(healer_task.task_id, "Healing also failed")

        # 2. Mock the DB layer
        mock_task_model = _make_failed_task_model(source="healer")
        mock_repo = _prepare_db_mocks(nats_service, mock_task_model)

        # 3. Run
        with patch(
            "figaro.services.nats_service.TaskRepository", return_value=mock_repo
        ):
            await nats_service._maybe_heal_failed_task(healer_task.task_id)

        # 4. Verify no new healer task was created
        all_tasks = await task_manager.get_all_tasks()
        healer_tasks = [t for t in all_tasks if t.source == "healer"]
        # Only the original healer task, no new one
        assert len(healer_tasks) == 1
        assert healer_tasks[0].task_id == healer_task.task_id

    @pytest.mark.asyncio
    async def test_healing_skipped_for_optimizer_source(
        self, nats_service, task_manager
    ):
        """Tasks with source='optimizer' are never healed."""

        # 1. Create an optimizer task that failed
        optimizer_task = await task_manager.create_task(
            prompt="Optimize the scheduled task",
            source="optimizer",
        )
        await task_manager.fail_task(optimizer_task.task_id, "Optimization error")

        # 2. Mock the DB layer
        mock_task_model = _make_failed_task_model(source="optimizer")
        mock_repo = _prepare_db_mocks(nats_service, mock_task_model)

        # 3. Run
        with patch(
            "figaro.services.nats_service.TaskRepository", return_value=mock_repo
        ):
            await nats_service._maybe_heal_failed_task(optimizer_task.task_id)

        # 4. Verify no healer task was created
        all_tasks = await task_manager.get_all_tasks()
        healer_tasks = [t for t in all_tasks if t.source == "healer"]
        assert len(healer_tasks) == 0

    @pytest.mark.asyncio
    async def test_healing_skipped_at_retry_limit(
        self, nats_service, task_manager, mock_settings
    ):
        """When retry_number >= max_retries, no more healing is attempted."""

        # 1. Create a task that has already been retried max times
        original_task = await task_manager.create_task(
            prompt="Do something",
            source="api",
            options={"self_healing": True},
            source_metadata={"retry_number": 2, "original_task_id": "orig-1"},
        )
        await task_manager.fail_task(original_task.task_id, "Failed again")

        # 2. Mock the DB layer — retry_number equals max_retries (2)
        mock_task_model = _make_failed_task_model(
            source="api",
            options={"self_healing": True},
            source_metadata={"retry_number": 2, "original_task_id": "orig-1"},
        )
        mock_repo = _prepare_db_mocks(nats_service, mock_task_model)

        # 3. Ensure max_retries is 2 (default in mock_settings)
        assert mock_settings.self_healing_max_retries == 2

        # 4. Run
        with patch(
            "figaro.services.nats_service.TaskRepository", return_value=mock_repo
        ):
            await nats_service._maybe_heal_failed_task(original_task.task_id)

        # 5. Verify no healer task was created
        all_tasks = await task_manager.get_all_tasks()
        healer_tasks = [t for t in all_tasks if t.source == "healer"]
        assert len(healer_tasks) == 0

    @pytest.mark.asyncio
    async def test_healer_task_queued_when_no_supervisor(
        self, nats_service, task_manager, registry, mock_settings
    ):
        """When no supervisor is available, the healer task is queued (pending)."""

        # 1. Create and fail a task
        original_task = await task_manager.create_task(
            prompt="Do something",
            source="api",
            options={"self_healing": True},
        )
        await task_manager.append_message(
            original_task.task_id,
            {"type": "assistant", "content": "Working on it"},
        )
        await task_manager.fail_task(original_task.task_id, "Timeout error")

        # 2. Mock the DB layer
        mock_task_model = _make_failed_task_model(
            source="api",
            options={"self_healing": True},
            prompt="Do something",
        )
        mock_repo = _prepare_db_mocks(nats_service, mock_task_model)

        # 3. No supervisors registered (registry is empty)

        # 4. Run -- should not raise
        with patch(
            "figaro.services.nats_service.TaskRepository", return_value=mock_repo
        ):
            await nats_service._maybe_heal_failed_task(original_task.task_id)

        # 5. Verify a healer task was still created
        all_tasks = await task_manager.get_all_tasks()
        healer_tasks = [t for t in all_tasks if t.source == "healer"]
        assert len(healer_tasks) == 1

        # 6. But it was NOT assigned (no supervisor), so status stays PENDING
        healer_task = healer_tasks[0]
        assert healer_task.status == TaskStatus.PENDING

    @pytest.mark.asyncio
    async def test_healing_resolves_config_from_scheduled_task(
        self, nats_service, task_manager, registry, mock_scheduler, mock_settings
    ):
        """When the task has a scheduled_task_id, healing config comes from
        the scheduled task's self_healing setting."""

        # 1. Create a task with scheduled_task_id but no self_healing in options
        original_task = await task_manager.create_task(
            prompt="Generate report",
            source="scheduler",
            scheduled_task_id="sched-1",
        )
        await task_manager.append_message(
            original_task.task_id,
            {"type": "assistant", "content": "Generating report"},
        )
        await task_manager.fail_task(original_task.task_id, "Navigation error")

        # 2. Mock the DB layer — no self_healing in options
        mock_task_model = _make_failed_task_model(
            source="scheduler",
            scheduled_task_id="sched-1",
            options={},  # no self_healing key
            prompt="Generate report",
        )
        mock_repo = _prepare_db_mocks(nats_service, mock_task_model)

        # 3. Scheduled task with self_healing=True
        scheduled_task = _make_scheduled_task(schedule_id="sched-1", self_healing=True)
        mock_scheduler.get_scheduled_task = AsyncMock(return_value=scheduled_task)

        # 4. System-wide default is False (to confirm scheduled task takes precedence)
        mock_settings.self_healing_enabled = False

        # 5. Register an idle supervisor
        await registry.register(
            client_id="supervisor-1",
            client_type=ClientType.SUPERVISOR,
            status=WorkerStatus.IDLE,
        )

        # 6. Spy on publish_supervisor_task
        nats_service.publish_supervisor_task = AsyncMock()

        # 7. Run
        with patch(
            "figaro.services.nats_service.TaskRepository", return_value=mock_repo
        ):
            await nats_service._maybe_heal_failed_task(original_task.task_id)

        # 8. Verify scheduler was consulted
        mock_scheduler.get_scheduled_task.assert_called_once_with("sched-1")

        # 9. Verify a healer task was created (scheduled task's self_healing=True)
        all_tasks = await task_manager.get_all_tasks()
        healer_tasks = [t for t in all_tasks if t.source == "healer"]
        assert len(healer_tasks) == 1

        # 10. Verify it was assigned to supervisor
        nats_service.publish_supervisor_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_healing_resolves_config_from_system_default(
        self, nats_service, task_manager, registry, mock_scheduler, mock_settings
    ):
        """When no task-level or scheduled-task-level config, falls back to
        system settings.self_healing_enabled."""

        # 1. Create a task without self_healing in options and no scheduled_task_id
        original_task = await task_manager.create_task(
            prompt="Do something",
            source="api",
        )
        await task_manager.append_message(
            original_task.task_id,
            {"type": "assistant", "content": "Working"},
        )
        await task_manager.fail_task(original_task.task_id, "Error occurred")

        # 2. Mock DB — no self_healing in options, no scheduled_task_id
        mock_task_model = _make_failed_task_model(
            source="api",
            options={},  # no self_healing key
            scheduled_task_id=None,
            prompt="Do something",
        )
        mock_repo = _prepare_db_mocks(nats_service, mock_task_model)

        # 3. System-wide default is True
        mock_settings.self_healing_enabled = True

        # 4. Register an idle supervisor
        await registry.register(
            client_id="supervisor-1",
            client_type=ClientType.SUPERVISOR,
            status=WorkerStatus.IDLE,
        )

        # 5. Spy on publish_supervisor_task
        nats_service.publish_supervisor_task = AsyncMock()

        # 6. Run
        with patch(
            "figaro.services.nats_service.TaskRepository", return_value=mock_repo
        ):
            await nats_service._maybe_heal_failed_task(original_task.task_id)

        # 7. Verify scheduler was NOT consulted (no scheduled_task_id)
        mock_scheduler.get_scheduled_task.assert_not_called()

        # 8. Verify a healer task was created (system default self_healing_enabled=True)
        all_tasks = await task_manager.get_all_tasks()
        healer_tasks = [t for t in all_tasks if t.source == "healer"]
        assert len(healer_tasks) == 1

        # 9. Verify it was assigned
        nats_service.publish_supervisor_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_healer_prompt_contains_error_and_history(
        self, nats_service, task_manager, registry, mock_settings
    ):
        """The healer task prompt includes the original prompt, error message,
        and conversation history."""

        # 1. Create a task with some conversation history
        original_task = await task_manager.create_task(
            prompt="Navigate to dashboard and export CSV",
            source="api",
            options={"self_healing": True, "start_url": "https://app.example.com"},
        )
        await task_manager.append_message(
            original_task.task_id,
            {"type": "assistant", "content": "Navigating to dashboard"},
        )
        await task_manager.append_message(
            original_task.task_id,
            {"type": "tool_result", "content": "Page loaded successfully"},
        )
        await task_manager.append_message(
            original_task.task_id,
            {"type": "assistant", "content": "Clicking export button"},
        )
        await task_manager.fail_task(
            original_task.task_id, "Element #export-btn not found"
        )

        # 2. Mock the DB layer
        mock_task_model = _make_failed_task_model(
            source="api",
            options={"self_healing": True, "start_url": "https://app.example.com"},
            result={"error": "Element #export-btn not found"},
            prompt="Navigate to dashboard and export CSV",
        )
        mock_repo = _prepare_db_mocks(nats_service, mock_task_model)

        # 3. Register an idle supervisor
        await registry.register(
            client_id="supervisor-1",
            client_type=ClientType.SUPERVISOR,
            status=WorkerStatus.IDLE,
        )

        # 4. Spy on publish_supervisor_task
        nats_service.publish_supervisor_task = AsyncMock()

        # 5. Run
        with patch(
            "figaro.services.nats_service.TaskRepository", return_value=mock_repo
        ):
            await nats_service._maybe_heal_failed_task(original_task.task_id)

        # 6. Verify the healer task prompt content
        all_tasks = await task_manager.get_all_tasks()
        healer_tasks = [t for t in all_tasks if t.source == "healer"]
        assert len(healer_tasks) == 1

        healer_prompt = healer_tasks[0].prompt

        # Should contain original prompt
        assert "Navigate to dashboard and export CSV" in healer_prompt

        # Should contain error message
        assert "Element #export-btn not found" in healer_prompt

        # Should contain conversation history
        assert "Navigating to dashboard" in healer_prompt
        assert "Page loaded successfully" in healer_prompt
        assert "Clicking export button" in healer_prompt

        # Should contain start_url
        assert "https://app.example.com" in healer_prompt

        # Should contain retry info
        assert "1 of 2" in healer_prompt

        # 7. Verify source_metadata on the healer task
        healer_task = healer_tasks[0]
        assert healer_task.source_metadata["failed_task_id"] == original_task.task_id
        assert healer_task.source_metadata["original_task_id"] == original_task.task_id
        assert healer_task.source_metadata["retry_number"] == 1
        assert healer_task.source_metadata["max_retries"] == 2
        assert healer_task.source_metadata["error"] == "Element #export-btn not found"


class TestMaybeOptimizeScheduledTask:
    """Tests for NatsService._maybe_optimize_scheduled_task."""

    @pytest.mark.asyncio
    async def test_optimization_skipped_when_at_max_learning_runs(
        self, nats_service, task_manager, mock_scheduler
    ):
        """When self_learning_run_count >= self_learning_max_runs, optimization is skipped."""

        # 1. Create a completed scheduler task
        original_task = await task_manager.create_task(
            prompt="Do something",
            source="scheduler",
            scheduled_task_id="sched-1",
        )
        await task_manager.append_message(
            original_task.task_id,
            {"type": "assistant", "content": "Done"},
        )

        # 2. Mock the DB layer for task lookup
        mock_task_model = MagicMock()
        mock_task_model.scheduled_task_id = "sched-1"
        mock_task_model.source = "scheduler"

        mock_repo = MagicMock()
        mock_repo.get = AsyncMock(return_value=mock_task_model)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        nats_service._session_factory = MagicMock(return_value=mock_session)

        # 3. Scheduled task with self_learning=True but at max runs
        scheduled_task = _make_scheduled_task(
            schedule_id="sched-1",
            self_learning=True,
            self_learning_max_runs=5,
            self_learning_run_count=5,  # at the limit
        )
        mock_scheduler.get_scheduled_task = AsyncMock(return_value=scheduled_task)

        # 4. Run
        with patch(
            "figaro.services.nats_service.TaskRepository", return_value=mock_repo
        ):
            await nats_service._maybe_optimize_scheduled_task(original_task.task_id)

        # 5. Verify no optimization task was created
        all_tasks = await task_manager.get_all_tasks()
        optimizer_tasks = [t for t in all_tasks if t.source == "optimizer"]
        assert len(optimizer_tasks) == 0

    @pytest.mark.asyncio
    async def test_optimization_proceeds_when_under_max_learning_runs(
        self, nats_service, task_manager, registry, mock_scheduler
    ):
        """When self_learning_run_count < self_learning_max_runs, optimization proceeds."""

        # 1. Create a completed scheduler task
        original_task = await task_manager.create_task(
            prompt="Do something",
            source="scheduler",
            scheduled_task_id="sched-1",
        )
        await task_manager.append_message(
            original_task.task_id,
            {"type": "assistant", "content": "Done"},
        )

        # 2. Mock the DB layer for task lookup
        mock_task_model = MagicMock()
        mock_task_model.scheduled_task_id = "sched-1"
        mock_task_model.source = "scheduler"

        mock_repo = MagicMock()
        mock_repo.get = AsyncMock(return_value=mock_task_model)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        nats_service._session_factory = MagicMock(return_value=mock_session)

        # 3. Scheduled task with self_learning=True and below max runs
        scheduled_task = _make_scheduled_task(
            schedule_id="sched-1",
            self_learning=True,
            self_learning_max_runs=5,
            self_learning_run_count=3,  # under the limit
        )
        mock_scheduler.get_scheduled_task = AsyncMock(return_value=scheduled_task)

        # 4. Mock ScheduledTaskRepository for increment
        mock_sched_repo = MagicMock()
        mock_sched_repo.increment_learning_count = AsyncMock()

        # 5. Register an idle supervisor
        await registry.register(
            client_id="supervisor-1",
            client_type=ClientType.SUPERVISOR,
            status=WorkerStatus.IDLE,
        )
        nats_service.publish_supervisor_task = AsyncMock()

        # 6. Run
        with patch(
            "figaro.services.nats_service.TaskRepository", return_value=mock_repo
        ), patch(
            "figaro.services.nats_service.ScheduledTaskRepository", return_value=mock_sched_repo
        ):
            await nats_service._maybe_optimize_scheduled_task(original_task.task_id)

        # 7. Verify an optimization task was created
        all_tasks = await task_manager.get_all_tasks()
        optimizer_tasks = [t for t in all_tasks if t.source == "optimizer"]
        assert len(optimizer_tasks) == 1

    @pytest.mark.asyncio
    async def test_optimization_proceeds_when_max_runs_is_none(
        self, nats_service, task_manager, registry, mock_scheduler
    ):
        """When self_learning_max_runs is None (unlimited), optimization always proceeds."""

        # 1. Create a completed scheduler task
        original_task = await task_manager.create_task(
            prompt="Do something",
            source="scheduler",
            scheduled_task_id="sched-1",
        )
        await task_manager.append_message(
            original_task.task_id,
            {"type": "assistant", "content": "Done"},
        )

        # 2. Mock the DB layer for task lookup
        mock_task_model = MagicMock()
        mock_task_model.scheduled_task_id = "sched-1"
        mock_task_model.source = "scheduler"

        mock_repo = MagicMock()
        mock_repo.get = AsyncMock(return_value=mock_task_model)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        nats_service._session_factory = MagicMock(return_value=mock_session)

        # 3. Scheduled task with self_learning=True and no max runs
        scheduled_task = _make_scheduled_task(
            schedule_id="sched-1",
            self_learning=True,
            self_learning_max_runs=None,  # unlimited
            self_learning_run_count=100,  # many runs
        )
        mock_scheduler.get_scheduled_task = AsyncMock(return_value=scheduled_task)

        # 4. Mock ScheduledTaskRepository for increment
        mock_sched_repo = MagicMock()
        mock_sched_repo.increment_learning_count = AsyncMock()

        # 5. Register an idle supervisor
        await registry.register(
            client_id="supervisor-1",
            client_type=ClientType.SUPERVISOR,
            status=WorkerStatus.IDLE,
        )
        nats_service.publish_supervisor_task = AsyncMock()

        # 6. Run
        with patch(
            "figaro.services.nats_service.TaskRepository", return_value=mock_repo
        ), patch(
            "figaro.services.nats_service.ScheduledTaskRepository", return_value=mock_sched_repo
        ):
            await nats_service._maybe_optimize_scheduled_task(original_task.task_id)

        # 7. Verify an optimization task was created
        all_tasks = await task_manager.get_all_tasks()
        optimizer_tasks = [t for t in all_tasks if t.source == "optimizer"]
        assert len(optimizer_tasks) == 1
