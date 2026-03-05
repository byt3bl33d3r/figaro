"""Supervisor module for NATS client and task processing."""

from figaro_supervisor.supervisor.client import SupervisorNatsClient
from figaro_supervisor.supervisor.processor import TaskProcessor

__all__ = ["SupervisorNatsClient", "TaskProcessor"]
