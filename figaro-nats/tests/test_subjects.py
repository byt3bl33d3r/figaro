"""Tests for NATS subject constants and builder functions."""

from figaro_nats.subjects import Subjects


class TestStaticSubjects:
    """Test all static subject constants."""

    def test_register_worker(self) -> None:
        assert Subjects.REGISTER_WORKER == "figaro.register.worker"

    def test_register_supervisor(self) -> None:
        assert Subjects.REGISTER_SUPERVISOR == "figaro.register.supervisor"

    def test_register_gateway(self) -> None:
        assert Subjects.REGISTER_GATEWAY == "figaro.register.gateway"

    def test_heartbeat_all(self) -> None:
        assert Subjects.HEARTBEAT_ALL == "figaro.heartbeat.>"

    def test_task_events_all(self) -> None:
        assert Subjects.TASK_EVENTS_ALL == "figaro.task.>"

    def test_help_request(self) -> None:
        assert Subjects.HELP_REQUEST == "figaro.help.request"

    def test_broadcast_workers(self) -> None:
        assert Subjects.BROADCAST_WORKERS == "figaro.broadcast.workers"

    def test_broadcast_supervisors(self) -> None:
        assert Subjects.BROADCAST_SUPERVISORS == "figaro.broadcast.supervisors"

    def test_broadcast_all(self) -> None:
        assert Subjects.BROADCAST_ALL == "figaro.broadcast.>"


class TestDynamicSubjects:
    """Test all dynamic subject builder functions with sample IDs."""

    def test_deregister(self) -> None:
        assert Subjects.deregister("worker", "w1") == "figaro.deregister.worker.w1"
        assert Subjects.deregister("supervisor", "s1") == "figaro.deregister.supervisor.s1"

    def test_heartbeat(self) -> None:
        assert Subjects.heartbeat("worker", "w1") == "figaro.heartbeat.worker.w1"
        assert Subjects.heartbeat("supervisor", "s1") == "figaro.heartbeat.supervisor.s1"

    def test_worker_task(self) -> None:
        assert Subjects.worker_task("worker-001") == "figaro.worker.worker-001.task"

    def test_supervisor_task(self) -> None:
        assert Subjects.supervisor_task("sup-001") == "figaro.supervisor.sup-001.task"

    def test_task_assigned(self) -> None:
        assert Subjects.task_assigned("task-abc") == "figaro.task.task-abc.assigned"

    def test_task_message(self) -> None:
        assert Subjects.task_message("task-abc") == "figaro.task.task-abc.message"

    def test_task_complete(self) -> None:
        assert Subjects.task_complete("task-abc") == "figaro.task.task-abc.complete"

    def test_task_error(self) -> None:
        assert Subjects.task_error("task-abc") == "figaro.task.task-abc.error"

    def test_task_all(self) -> None:
        assert Subjects.task_all("task-abc") == "figaro.task.task-abc.>"

    def test_help_response(self) -> None:
        assert Subjects.help_response("req-123") == "figaro.help.req-123.response"

    def test_gateway_send(self) -> None:
        assert Subjects.gateway_send("telegram") == "figaro.gateway.telegram.send"

    def test_gateway_task(self) -> None:
        assert Subjects.gateway_task("slack") == "figaro.gateway.slack.task"

    def test_gateway_question(self) -> None:
        assert Subjects.gateway_question("discord") == "figaro.gateway.discord.question"

    def test_gateway_register(self) -> None:
        assert Subjects.gateway_register("telegram") == "figaro.gateway.telegram.register"


class TestApiSubjects:
    """Test all API subject constants."""

    def test_api_delegate(self) -> None:
        assert Subjects.API_DELEGATE == "figaro.api.delegate"

    def test_api_workers(self) -> None:
        assert Subjects.API_WORKERS == "figaro.api.workers"

    def test_api_tasks(self) -> None:
        assert Subjects.API_TASKS == "figaro.api.tasks"

    def test_api_task_get(self) -> None:
        assert Subjects.API_TASK_GET == "figaro.api.tasks.get"

    def test_api_task_search(self) -> None:
        assert Subjects.API_TASK_SEARCH == "figaro.api.tasks.search"

    def test_api_task_create(self) -> None:
        assert Subjects.API_TASK_CREATE == "figaro.api.tasks.create"

    def test_api_supervisor_status(self) -> None:
        assert Subjects.API_SUPERVISOR_STATUS == "figaro.api.supervisor.status"

    def test_api_scheduled_tasks(self) -> None:
        assert Subjects.API_SCHEDULED_TASKS == "figaro.api.scheduled-tasks"

    def test_api_scheduled_task_get(self) -> None:
        assert Subjects.API_SCHEDULED_TASK_GET == "figaro.api.scheduled-tasks.get"

    def test_api_scheduled_task_create(self) -> None:
        assert Subjects.API_SCHEDULED_TASK_CREATE == "figaro.api.scheduled-tasks.create"

    def test_api_scheduled_task_update(self) -> None:
        assert Subjects.API_SCHEDULED_TASK_UPDATE == "figaro.api.scheduled-tasks.update"

    def test_api_scheduled_task_delete(self) -> None:
        assert Subjects.API_SCHEDULED_TASK_DELETE == "figaro.api.scheduled-tasks.delete"

    def test_api_scheduled_task_toggle(self) -> None:
        assert Subjects.API_SCHEDULED_TASK_TOGGLE == "figaro.api.scheduled-tasks.toggle"

    def test_api_help_request_respond(self) -> None:
        assert Subjects.API_HELP_REQUEST_RESPOND == "figaro.api.help-requests.respond"

    def test_api_help_request_dismiss(self) -> None:
        assert Subjects.API_HELP_REQUEST_DISMISS == "figaro.api.help-requests.dismiss"


class TestWildcardPatterns:
    """Test that wildcard patterns follow NATS conventions."""

    def test_heartbeat_wildcard_uses_gt(self) -> None:
        """The > wildcard matches one or more tokens."""
        assert Subjects.HEARTBEAT_ALL.endswith(">")

    def test_task_events_wildcard_uses_gt(self) -> None:
        assert Subjects.TASK_EVENTS_ALL.endswith(">")

    def test_broadcast_all_wildcard_uses_gt(self) -> None:
        assert Subjects.BROADCAST_ALL.endswith(">")

    def test_task_all_wildcard_uses_gt(self) -> None:
        result = Subjects.task_all("any-id")
        assert result.endswith(">")

    def test_wildcard_subjects_have_correct_prefix(self) -> None:
        assert Subjects.HEARTBEAT_ALL.startswith("figaro.heartbeat.")
        assert Subjects.TASK_EVENTS_ALL.startswith("figaro.task.")
        assert Subjects.BROADCAST_ALL.startswith("figaro.broadcast.")
