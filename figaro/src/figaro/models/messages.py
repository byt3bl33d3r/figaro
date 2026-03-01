from enum import Enum
from typing import Any
from pydantic import BaseModel


class ClientType(str, Enum):
    WORKER = "worker"
    UI = "ui"
    SUPERVISOR = "supervisor"


class WorkerStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"


class RegisterPayload(BaseModel):
    client_type: ClientType
    worker_id: str | None = None
    capabilities: list[str] | None = None
    novnc_url: str | None = None


class TaskPayload(BaseModel):
    task_id: str | None = None
    prompt: str
    options: dict[str, Any] = {}


class ErrorPayload(BaseModel):
    task_id: str
    error: str


class StatusPayload(BaseModel):
    worker_id: str
    status: WorkerStatus


class WorkerInfo(BaseModel):
    id: str
    status: WorkerStatus
    capabilities: list[str]
    novnc_url: str | None = None


class WorkersPayload(BaseModel):
    workers: list[WorkerInfo]


class SupervisorInfo(BaseModel):
    id: str
    status: WorkerStatus
    capabilities: list[str]


class SupervisorsPayload(BaseModel):
    supervisors: list[SupervisorInfo]


class Message(BaseModel):
    type: str
    payload: dict[str, Any] = {}
