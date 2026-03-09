from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from figaro.services.nats.service import NatsService

logger = logging.getLogger(__name__)


async def api_list_help_requests(
    svc: NatsService, data: dict[str, Any]
) -> dict[str, Any]:
    """List all help requests (pending + recent resolved)."""
    requests = await svc._help_request_manager.get_all_requests()
    return {
        "requests": [
            {
                "request_id": r.request_id,
                "worker_id": r.worker_id,
                "task_id": r.task_id,
                "questions": r.questions,
                "context": None,
                "created_at": r.created_at.isoformat(),
                "timeout_seconds": r.timeout_seconds,
                "status": r.status.value,
            }
            for r in requests
        ]
    }


async def api_help_request_respond(
    svc: NatsService, data: dict[str, Any]
) -> dict[str, Any]:
    """Handle help request response via NATS."""
    request_id = data.get("request_id", "")
    answers = data.get("answers", {})
    source = data.get("source", "nats")

    success = await svc._help_request_manager.respond(
        request_id=request_id,
        answers=answers,
        source=source,
    )

    if not success:
        return {
            "success": False,
            "error": "Failed to submit response. Request may not exist or already responded.",
            "request_id": request_id,
        }

    return {"success": True, "request_id": request_id}


async def api_help_request_dismiss(
    svc: NatsService, data: dict[str, Any]
) -> dict[str, Any]:
    """Handle help request dismissal via NATS."""
    request_id = data.get("request_id", "")
    source = data.get("source", "nats")

    success = await svc._help_request_manager.dismiss_request(
        request_id=request_id,
        source=source,
    )

    if not success:
        return {
            "success": False,
            "error": "Failed to dismiss request. Request may not exist or already handled.",
            "request_id": request_id,
        }

    return {"success": True, "request_id": request_id}
