"""Shared NATS messaging library for Figaro."""

from figaro_nats.client import NatsConnection
from figaro_nats.streams import ensure_streams
from figaro_nats.subjects import Subjects

__all__ = ["NatsConnection", "Subjects", "ensure_streams"]
