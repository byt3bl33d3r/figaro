"""JetStream stream configuration for Figaro."""

from __future__ import annotations

import asyncio
import logging

from nats.js import JetStreamContext
from nats.js.api import StreamConfig, RetentionPolicy

logger = logging.getLogger(__name__)

TASKS_STREAM = "TASKS"
TASKS_SUBJECTS = ["figaro.task.>"]
TASKS_MAX_AGE = 7 * 24 * 60 * 60  # 7 days in seconds

HELP_STREAM = "HELP"
HELP_SUBJECTS = ["figaro.help.*.response"]
HELP_MAX_AGE = 24 * 60 * 60  # 1 day in seconds


async def _ensure_stream(
    js: JetStreamContext,
    name: str,
    subjects: list[str],
    max_age: int,
) -> None:
    """Create or update a single JetStream stream."""
    config = StreamConfig(
        name=name,
        subjects=subjects,
        retention=RetentionPolicy.LIMITS,
        max_age=max_age,
    )
    try:
        await js.find_stream_name_by_subject(subjects[0])
        await js.update_stream(config)
        logger.info("Updated JetStream stream: %s", name)
    except Exception:
        await js.add_stream(config)
        logger.info("Created JetStream stream: %s", name)


async def ensure_streams(js: JetStreamContext) -> None:
    """Create or update JetStream streams required by Figaro."""
    await asyncio.gather(
        _ensure_stream(js, TASKS_STREAM, TASKS_SUBJECTS, TASKS_MAX_AGE),
        _ensure_stream(js, HELP_STREAM, HELP_SUBJECTS, HELP_MAX_AGE),
    )
