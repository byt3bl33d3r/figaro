from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING

from figaro_nats import Subjects

from figaro.services.nats.event_handlers import (
    handle_deregister,
    handle_gateway_channel_register,
    handle_gateway_task,
    handle_heartbeat,
    handle_help_request,
    handle_supervisor_register,
    handle_task_complete,
    handle_task_error,
    handle_task_message,
    handle_worker_register,
)
from figaro.services.nats.api_tasks import (
    api_create_task,
    api_delegate,
    api_get_task,
    api_list_tasks,
    api_list_workers,
    api_search_tasks,
    api_stop_task,
    api_supervisor_status,
)
from figaro.services.nats.api_scheduled import (
    api_create_scheduled_task,
    api_delete_scheduled_task,
    api_get_scheduled_task,
    api_list_scheduled_tasks,
    api_toggle_scheduled_task,
    api_trigger_scheduled_task,
    api_update_scheduled_task,
)
from figaro.services.nats.api_remote import (
    api_ssh,
    api_telnet,
    api_vnc,
)
from figaro.services.nats.api_help import (
    api_help_request_dismiss,
    api_help_request_respond,
    api_list_help_requests,
)
from figaro.services.nats.api_desktop_workers import (
    api_register_desktop_worker,
    api_remove_desktop_worker,
    api_update_desktop_worker,
)
from figaro.services.nats.api_memories import (
    api_delete_memory,
    api_list_memories,
    api_save_memory,
    api_search_memories,
)

if TYPE_CHECKING:
    from figaro.services.nats.service import NatsService

logger = logging.getLogger(__name__)


async def setup_subscriptions(svc: NatsService) -> None:
    """Set up all NATS subscriptions."""
    conn = svc.conn

    # Registration (Core NATS request/reply so clients get ack)
    await conn.subscribe_request(
        Subjects.REGISTER_WORKER,
        functools.partial(handle_worker_register, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.REGISTER_SUPERVISOR,
        functools.partial(handle_supervisor_register, svc),
        queue="orchestrator",
    )
    await conn.subscribe(
        Subjects.HEARTBEAT_ALL,
        functools.partial(handle_heartbeat, svc),
    )
    await conn.subscribe(
        "figaro.deregister.>",
        functools.partial(handle_deregister, svc),
    )

    # Task events (JetStream)
    await conn.js_subscribe(
        "figaro.task.*.message",
        functools.partial(handle_task_message, svc),
        durable="orchestrator-task-message",
        deliver_policy="new",
    )
    await conn.js_subscribe(
        "figaro.task.*.complete",
        functools.partial(handle_task_complete, svc),
        durable="orchestrator-task-complete",
        deliver_policy="new",
    )
    await conn.js_subscribe(
        "figaro.task.*.error",
        functools.partial(handle_task_error, svc),
        durable="orchestrator-task-error",
        deliver_policy="new",
    )

    # Help requests (Core NATS)
    await conn.subscribe(
        Subjects.HELP_REQUEST,
        functools.partial(handle_help_request, svc),
        queue="orchestrator",
    )

    # Gateway (Core NATS)
    await conn.subscribe(
        Subjects.gateway_task("telegram"),
        functools.partial(handle_gateway_task, svc),
        queue="orchestrator",
    )
    await conn.subscribe(
        "figaro.gateway.*.register",
        functools.partial(handle_gateway_channel_register, svc),
    )

    # API request/reply handlers (for supervisor NATS-based tool calls)
    await conn.subscribe_request(
        Subjects.API_DELEGATE,
        functools.partial(api_delegate, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_WORKERS,
        functools.partial(api_list_workers, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_TASKS,
        functools.partial(api_list_tasks, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_TASK_GET,
        functools.partial(api_get_task, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_TASK_SEARCH,
        functools.partial(api_search_tasks, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_SUPERVISOR_STATUS,
        functools.partial(api_supervisor_status, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_SCHEDULED_TASKS,
        functools.partial(api_list_scheduled_tasks, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_SCHEDULED_TASK_GET,
        functools.partial(api_get_scheduled_task, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_SCHEDULED_TASK_CREATE,
        functools.partial(api_create_scheduled_task, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_SCHEDULED_TASK_UPDATE,
        functools.partial(api_update_scheduled_task, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_SCHEDULED_TASK_DELETE,
        functools.partial(api_delete_scheduled_task, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_SCHEDULED_TASK_TOGGLE,
        functools.partial(api_toggle_scheduled_task, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_SCHEDULED_TASK_TRIGGER,
        functools.partial(api_trigger_scheduled_task, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_TASK_CREATE,
        functools.partial(api_create_task, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_HELP_REQUEST_RESPOND,
        functools.partial(api_help_request_respond, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_HELP_REQUEST_DISMISS,
        functools.partial(api_help_request_dismiss, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_HELP_REQUESTS_LIST,
        functools.partial(api_list_help_requests, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_VNC,
        functools.partial(api_vnc, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_SSH,
        functools.partial(api_ssh, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_TELNET,
        functools.partial(api_telnet, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_DESKTOP_WORKERS_REGISTER,
        functools.partial(api_register_desktop_worker, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_DESKTOP_WORKERS_REMOVE,
        functools.partial(api_remove_desktop_worker, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_DESKTOP_WORKERS_UPDATE,
        functools.partial(api_update_desktop_worker, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_TASK_STOP,
        functools.partial(api_stop_task, svc),
        queue="orchestrator",
    )

    # Memories API
    await conn.subscribe_request(
        Subjects.API_MEMORY_SAVE,
        functools.partial(api_save_memory, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_MEMORY_SEARCH,
        functools.partial(api_search_memories, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_MEMORY_DELETE,
        functools.partial(api_delete_memory, svc),
        queue="orchestrator",
    )
    await conn.subscribe_request(
        Subjects.API_MEMORY_LIST,
        functools.partial(api_list_memories, svc),
        queue="orchestrator",
    )

    logger.info("All NATS subscriptions established")
