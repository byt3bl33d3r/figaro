from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from figaro.db.repositories.scheduled import ScheduledTaskRepository
from figaro.db.repositories.tasks import TaskRepository
from figaro.db.repositories.workers import WorkerSessionRepository
from figaro.services.nats.publishing import try_assign_to_supervisor
from figaro.services.task_manager import TaskStatus

if TYPE_CHECKING:
    from figaro.services.nats.service import NatsService

logger = logging.getLogger(__name__)


async def maybe_notify_gateway(
    svc: NatsService,
    task_id: str,
    result: Any = None,
    error: str | None = None,
) -> None:
    """Send a gateway notification if the task's scheduled task has notify_on_complete."""
    try:
        if not svc._session_factory:
            return

        async with svc._session_factory() as session:
            repo = TaskRepository(session)
            task_model = await repo.get(task_id)
            if (
                not task_model
                or not task_model.scheduled_task_id
                or task_model.source != "scheduler"
            ):
                return

            scheduled_task_id = task_model.scheduled_task_id

        scheduled_task = await svc._scheduler.get_scheduled_task(scheduled_task_id)
        if not scheduled_task or not scheduled_task.notify_on_complete:
            return

        task_name = scheduled_task.name or scheduled_task_id
        if error:
            text = f"Scheduled task *{task_name}* failed:\n{error}"
        else:
            if isinstance(result, dict):
                result_text = result.get("result") or result.get("text", "")
            else:
                result_text = result
            if not result_text:
                result_text = "No result text."
            if not isinstance(result_text, str):
                result_text = str(result_text)
            text = f"Scheduled task *{task_name}* completed:\n{result_text}"

        if not svc._gateway_channels:
            logger.warning(
                f"No gateway channels registered, cannot notify for scheduled task {scheduled_task_id}"
            )
            return

        for channel in svc._gateway_channels:
            await svc.publish_gateway_send(
                channel,
                {"chat_id": "", "text": text},
            )
        logger.info(
            f"Sent gateway notification for scheduled task {scheduled_task_id}"
        )
    except Exception:
        logger.exception(f"Failed to send gateway notification for task {task_id}")


async def maybe_optimize_scheduled_task(svc: NatsService, task_id: str) -> None:
    """If the completed task came from a self-learning scheduled task, create an optimization task for the supervisor."""
    try:
        # 1. Get the task from DB to access scheduled_task_id and source
        if not svc._session_factory:
            return

        async with svc._session_factory() as session:
            repo = TaskRepository(session)
            task_model = await repo.get(task_id)
            if (
                not task_model
                or not task_model.scheduled_task_id
                or task_model.source != "scheduler"
            ):
                return

            scheduled_task_id = task_model.scheduled_task_id

        # 2. Get the scheduled task, check self_learning
        scheduled_task = await svc._scheduler.get_scheduled_task(scheduled_task_id)
        if not scheduled_task or not scheduled_task.self_learning:
            return

        # Check if self-learning run count has reached the limit
        if (
            scheduled_task.self_learning_max_runs is not None
            and scheduled_task.self_learning_run_count
            >= scheduled_task.self_learning_max_runs
        ):
            logger.info(
                f"Skipping optimization for scheduled task {scheduled_task_id}: "
                f"learning run count {scheduled_task.self_learning_run_count} >= max {scheduled_task.self_learning_max_runs}"
            )
            return

        # 3. Get conversation history
        messages = await svc._task_manager.get_history(task_id)
        if not messages:
            return

        # 4. Filter to key message types and format
        key_types = {"assistant", "tool_result", "result"}
        filtered = [m for m in messages if m.get("type") in key_types]
        if not filtered:
            filtered = messages  # fallback to all messages

        formatted_history = "\n\n".join(
            f"[{m.get('type', 'unknown')}]: {m.get('content', '')[:2000]}"
            for m in filtered[-50:]  # last 50 messages max
        )

        # 5. Build optimization prompt
        prompt = f"""You are optimizing a recurring scheduled task based on a worker's execution history.

## Scheduled Task
- ID: {scheduled_task.schedule_id}
- Name: {scheduled_task.name}
- Current Prompt: {scheduled_task.prompt}

## Worker Conversation History (Task {task_id})
{formatted_history}

## Instructions
Analyze the worker's conversation history above. Based on what happened:
1. Identify what worked well and what was inefficient
2. Note any errors, retries, or wasted steps
3. Look for any human-in-the-loop interactions (AskUserQuestion / help requests). If the worker asked a human for clarification and received answers, incorporate those answers directly into the improved prompt so the worker won't need to ask again next time
4. Improve the task prompt to be more specific and efficient
5. If the task involves website navigation and search, ensure the prompt instructs the worker to use `patchright-cli` for browser automation if available, and to refresh or redo searches to provide fresh results rather than relying on stale page state

Use the `update_scheduled_task` tool to save your improved prompt.
ONLY update the prompt field - do NOT change the schedule, enabled state, start_url, or any other settings.
Keep the core intent of the original prompt intact while making it more actionable and specific."""

        # 6. Create optimization task
        opt_task = await svc._task_manager.create_task(
            prompt=prompt,
            source="optimizer",
            options={"source": "optimizer"},
            scheduled_task_id=scheduled_task.schedule_id,
        )

        # 7. Assign to an idle supervisor, or queue for later
        if not await try_assign_to_supervisor(svc, opt_task):
            await svc._task_manager.queue_task(opt_task.task_id)
            logger.info(
                f"Queued optimization task {opt_task.task_id} (no idle supervisor)"
            )
            return

        logger.info(
            f"Created optimization task {opt_task.task_id} for scheduled task {scheduled_task.schedule_id}"
        )

        # 8. Increment learning run count
        async with svc._session_factory() as session:
            repo = ScheduledTaskRepository(session)
            await repo.increment_learning_count(scheduled_task.schedule_id)
            await session.commit()

    except Exception as e:
        logger.warning(f"Failed to create optimization task for {task_id}: {e}")


async def maybe_heal_failed_task(svc: NatsService, task_id: str) -> None:
    """If a failed task has self-healing enabled, create a healer task for the supervisor to retry with an improved approach."""
    try:
        if not svc._session_factory:
            return

        async with svc._session_factory() as session:
            repo = TaskRepository(session)
            task_model = await repo.get(task_id)
            if not task_model:
                return

            # Guard: skip healer and optimizer tasks to prevent loops
            if task_model.source in ("healer", "optimizer"):
                return

            # Guard: skip cancelled tasks
            task = await svc._task_manager.get_task(task_id)
            if task and task.status == TaskStatus.CANCELLED:
                logger.debug(f"Skipping healing for cancelled task {task_id}")
                return

            # Resolve healing config
            # 1. Check task options
            options = task_model.options or {}
            source_metadata = task_model.source_metadata or {}
            healing_enabled = options.get("self_healing")

            # 2. If not set in options, check scheduled task
            if healing_enabled is None and task_model.scheduled_task_id:
                scheduled_task = await svc._scheduler.get_scheduled_task(
                    task_model.scheduled_task_id
                )
                if scheduled_task:
                    healing_enabled = scheduled_task.self_healing

            # 3. Fall back to system-wide setting
            if healing_enabled is None:
                healing_enabled = svc._settings.self_healing_enabled

            if not healing_enabled:
                return

            # Check retry limit
            retry_number = source_metadata.get("retry_number", 0)
            max_retries = svc._settings.self_healing_max_retries
            if retry_number >= max_retries:
                logger.info(
                    f"Task {task_id} has reached max healing retries ({retry_number}/{max_retries}), skipping"
                )
                return

            # Get conversation history
            messages = await svc._task_manager.get_history(task_id)

            # Filter to key message types and format
            formatted_history = ""
            if messages:
                key_types = {"assistant", "tool_result", "result"}
                filtered = [m for m in messages if m.get("type") in key_types]
                if not filtered:
                    filtered = messages  # fallback to all messages

                formatted_history = "\n\n".join(
                    f"[{m.get('type', 'unknown')}]: {m.get('content', '')[:2000]}"
                    for m in filtered[-50:]  # last 50 messages max
                )

            # Get the error from the failed task result
            error_msg = ""
            if task_model.result:
                error_msg = task_model.result.get("error", "")
            if not error_msg:
                error_msg = "Unknown error"

            # Build healer prompt
            prompt = f"""You are a self-healing agent analyzing a failed task and retrying it with an improved approach.

## Failed Task
- Task ID: {task_id}
- Original Prompt: {task_model.prompt}
- Error: {error_msg}
- Retry Attempt: {retry_number + 1} of {max_retries}

## Conversation History (Task {task_id})
{formatted_history if formatted_history else "[No conversation history available]"}

## Instructions
Analyze the error and conversation history above. Based on what went wrong:
1. Identify the root cause of the failure
2. Determine if this is a recoverable error (e.g., timing issue, element not found, navigation error) or an unrecoverable one (e.g., invalid credentials, service down, fundamental approach problem)
3. If recoverable: use `delegate_to_worker` with an improved prompt that addresses the failure. Modify the approach to avoid the same error.
4. If unrecoverable: do NOT retry. Simply explain why the task cannot be completed.

When delegating, include the original task's start_url if available: {options.get("start_url", "not specified")}

IMPORTANT: Do not simply retry with the exact same prompt. Analyze the failure and adapt the approach."""

            # Determine original_task_id for tracking retry chains
            original_task_id = source_metadata.get("original_task_id", task_id)

            # Create healer task
            healer_task = await svc._task_manager.create_task(
                prompt=prompt,
                source="healer",
                options={"source": "healer"},
                source_metadata={
                    "original_task_id": original_task_id,
                    "failed_task_id": task_id,
                    "retry_number": retry_number + 1,
                    "max_retries": max_retries,
                    "error": str(error_msg),
                },
            )

            # Broadcast healing event
            await svc.conn.publish(
                "figaro.broadcast.task_healing",
                {
                    "healer_task_id": healer_task.task_id,
                    "failed_task_id": task_id,
                    "original_task_id": original_task_id,
                    "retry_number": retry_number + 1,
                    "max_retries": max_retries,
                    "error": str(error_msg),
                },
            )

            # Assign to an idle supervisor, or queue for later
            if not await try_assign_to_supervisor(svc, healer_task):
                await svc._task_manager.queue_task(healer_task.task_id)
                logger.info(
                    f"Queued healer task {healer_task.task_id} (no idle supervisor)"
                )
                return

            logger.info(
                f"Created healer task {healer_task.task_id} for failed task {task_id} "
                f"(retry {retry_number + 1}/{max_retries})"
            )

    except Exception as e:
        logger.warning(f"Failed to create healer task for {task_id}: {e}")


async def increment_worker_completed_count(
    svc: NatsService, worker_id: str
) -> None:
    """Background task to increment worker completed count in DB."""
    if not svc._session_factory:
        return
    try:
        async with svc._session_factory() as session:
            repo = WorkerSessionRepository(session)
            await repo.increment_completed(worker_id)
            await session.commit()
    except Exception as e:
        logger.warning(f"Failed to increment completed count for {worker_id}: {e}")


async def increment_worker_failed_count(svc: NatsService, worker_id: str) -> None:
    """Background task to increment worker failed count in DB."""
    if not svc._session_factory:
        return
    try:
        async with svc._session_factory() as session:
            repo = WorkerSessionRepository(session)
            await repo.increment_failed(worker_id)
            await session.commit()
    except Exception as e:
        logger.warning(f"Failed to increment failed count for {worker_id}: {e}")
