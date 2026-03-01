"""API request/response schemas for FastAPI endpoints."""

from typing import Any

from pydantic import BaseModel


# Task schemas
class TaskCreate(BaseModel):
    prompt: str
    options: dict[str, Any] = {}


class TaskResponse(BaseModel):
    task_id: str
    prompt: str
    options: dict[str, Any]
    status: str
    result: Any | None = None
    worker_id: str | None = None
    session_id: str | None = None
    messages: list[dict[str, Any]] = []


# Worker schemas
class WorkerResponse(BaseModel):
    id: str
    status: str
    capabilities: list[str]
    novnc_url: str | None = None


# Scheduled task schemas
class ScheduledTaskCreate(BaseModel):
    name: str
    prompt: str
    start_url: str
    interval_seconds: int
    options: dict[str, Any] = {}
    parallel_workers: int = 1
    max_runs: int | None = None
    notify_on_complete: bool = False


class ScheduledTaskUpdate(BaseModel):
    name: str | None = None
    prompt: str | None = None
    start_url: str | None = None
    interval_seconds: int | None = None
    enabled: bool | None = None
    options: dict[str, Any] | None = None
    parallel_workers: int | None = None
    max_runs: int | None = None
    notify_on_complete: bool | None = None


class ScheduledTaskResponse(BaseModel):
    schedule_id: str
    name: str
    prompt: str
    start_url: str
    interval_seconds: int
    enabled: bool
    created_at: str
    last_run_at: str | None
    next_run_at: str | None
    run_count: int
    options: dict[str, Any]
    parallel_workers: int
    max_runs: int | None
    notify_on_complete: bool


# Help request schemas
class HelpRequestResponse(BaseModel):
    request_id: str
    worker_id: str
    task_id: str
    questions: list[dict[str, Any]]
    created_at: str
    timeout_seconds: int
    status: str
    answers: dict[str, str] | None = None
    responded_at: str | None = None
    response_source: str | None = None


class HelpResponseSubmit(BaseModel):
    answers: dict[str, str]
