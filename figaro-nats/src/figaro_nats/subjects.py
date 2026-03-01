"""NATS subject constants and builder functions for Figaro."""


class Subjects:
    """NATS subject definitions for the Figaro messaging system."""

    # Registration & Presence (Core NATS)
    REGISTER_WORKER = "figaro.register.worker"
    REGISTER_SUPERVISOR = "figaro.register.supervisor"
    REGISTER_GATEWAY = "figaro.register.gateway"

    @staticmethod
    def deregister(client_type: str, client_id: str) -> str:
        return f"figaro.deregister.{client_type}.{client_id}"

    @staticmethod
    def heartbeat(client_type: str, client_id: str) -> str:
        return f"figaro.heartbeat.{client_type}.{client_id}"

    # Wildcard for subscribing to all heartbeats
    HEARTBEAT_ALL = "figaro.heartbeat.>"

    # Task Assignment (Core NATS - point-to-point)
    @staticmethod
    def worker_task(worker_id: str) -> str:
        return f"figaro.worker.{worker_id}.task"

    @staticmethod
    def supervisor_task(supervisor_id: str) -> str:
        return f"figaro.supervisor.{supervisor_id}.task"

    # Task Events (JetStream TASKS stream - figaro.task.>)
    @staticmethod
    def task_assigned(task_id: str) -> str:
        return f"figaro.task.{task_id}.assigned"

    @staticmethod
    def task_message(task_id: str) -> str:
        return f"figaro.task.{task_id}.message"

    @staticmethod
    def task_complete(task_id: str) -> str:
        return f"figaro.task.{task_id}.complete"

    @staticmethod
    def task_error(task_id: str) -> str:
        return f"figaro.task.{task_id}.error"

    # Subscribe to all events for a specific task
    @staticmethod
    def task_all(task_id: str) -> str:
        return f"figaro.task.{task_id}.>"

    # Subscribe to all task events (for JetStream stream)
    TASK_EVENTS_ALL = "figaro.task.>"

    # Help Requests (Core NATS)
    HELP_REQUEST = "figaro.help.request"

    @staticmethod
    def help_response(request_id: str) -> str:
        return f"figaro.help.{request_id}.response"

    # Broadcasts (Core NATS)
    BROADCAST_WORKERS = "figaro.broadcast.workers"
    BROADCAST_SUPERVISORS = "figaro.broadcast.supervisors"
    BROADCAST_ALL = "figaro.broadcast.>"

    # API (NATS request/reply for service-to-service calls)
    API_DELEGATE = "figaro.api.delegate"
    API_WORKERS = "figaro.api.workers"
    API_TASKS = "figaro.api.tasks"
    API_TASK_GET = "figaro.api.tasks.get"
    API_TASK_SEARCH = "figaro.api.tasks.search"
    API_SUPERVISOR_STATUS = "figaro.api.supervisor.status"
    API_SCHEDULED_TASKS = "figaro.api.scheduled-tasks"
    API_SCHEDULED_TASK_GET = "figaro.api.scheduled-tasks.get"
    API_SCHEDULED_TASK_CREATE = "figaro.api.scheduled-tasks.create"
    API_SCHEDULED_TASK_UPDATE = "figaro.api.scheduled-tasks.update"
    API_SCHEDULED_TASK_DELETE = "figaro.api.scheduled-tasks.delete"
    API_SCHEDULED_TASK_TOGGLE = "figaro.api.scheduled-tasks.toggle"
    API_SCHEDULED_TASK_TRIGGER = "figaro.api.scheduled-tasks.trigger"
    API_TASK_CREATE = "figaro.api.tasks.create"
    API_HELP_REQUESTS_LIST = "figaro.api.help-requests.list"
    API_HELP_REQUEST_RESPOND = "figaro.api.help-requests.respond"
    API_HELP_REQUEST_DISMISS = "figaro.api.help-requests.dismiss"
    API_VNC = "figaro.api.vnc"
    API_DESKTOP_WORKERS_REGISTER = "figaro.api.desktop-workers.register"
    API_DESKTOP_WORKERS_REMOVE = "figaro.api.desktop-workers.remove"
    API_DESKTOP_WORKERS_UPDATE = "figaro.api.desktop-workers.update"

    # Gateway — channel-agnostic (Core NATS)
    @staticmethod
    def gateway_send(channel: str) -> str:
        return f"figaro.gateway.{channel}.send"

    @staticmethod
    def gateway_task(channel: str) -> str:
        return f"figaro.gateway.{channel}.task"

    @staticmethod
    def gateway_question(channel: str) -> str:
        return f"figaro.gateway.{channel}.question"

    @staticmethod
    def gateway_register(channel: str) -> str:
        return f"figaro.gateway.{channel}.register"
