from enum import Enum


class ClientType(str, Enum):
    WORKER = "worker"
    UI = "ui"
    SUPERVISOR = "supervisor"


class WorkerStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
