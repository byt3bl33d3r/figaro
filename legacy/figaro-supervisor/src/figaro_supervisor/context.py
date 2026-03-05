"""Context management for figaro-supervisor using contextvars.

This module provides async-safe context for hooks, replacing
module-level global variables with contextvars for proper isolation
and thread/coroutine safety.
"""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from figaro_supervisor.supervisor.client import SupervisorNatsClient


@dataclass
class SupervisorContext:
    """Holds all shared context for supervisor hooks.

    This replaces the various module-level globals with a single
    immutable context object that can be safely passed around.
    """

    client: "SupervisorNatsClient | None" = None
    task_id: str | None = None


# Context variable for the current supervisor context
# This is async-safe and properly isolated between coroutines
_supervisor_context: ContextVar[SupervisorContext | None] = ContextVar(
    "supervisor_context", default=None
)


def set_context(ctx: SupervisorContext | None) -> None:
    """Set the current supervisor context.

    Args:
        ctx: SupervisorContext to set as current, or None to clear
    """
    _supervisor_context.set(ctx)


def get_context() -> SupervisorContext | None:
    """Get the current supervisor context.

    Returns:
        Current SupervisorContext or None if not set
    """
    return _supervisor_context.get()


def get_client() -> "SupervisorNatsClient | None":
    """Get the SupervisorNatsClient from current context.

    Returns:
        SupervisorNatsClient instance or None if context not set
    """
    ctx = _supervisor_context.get()
    return ctx.client if ctx else None


def get_task_id() -> str | None:
    """Get the current task ID from context.

    Returns:
        Current task ID or None if not set
    """
    ctx = _supervisor_context.get()
    return ctx.task_id if ctx else None


def update_task_context(client: "SupervisorNatsClient", task_id: str) -> None:
    """Update the context with task-specific information.

    This creates a new context with updated client and task_id.

    Args:
        client: SupervisorNatsClient for NATS communication
        task_id: Current task ID
    """
    ctx = _supervisor_context.get()
    if ctx:
        new_ctx = SupervisorContext(
            client=client,
            task_id=task_id,
        )
        _supervisor_context.set(new_ctx)
