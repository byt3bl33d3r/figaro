"""Pytest configuration and fixtures for figaro-worker tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_nats_client():
    """Create a mock NatsClient."""
    client = MagicMock()
    client.worker_id = "test-worker"
    client.is_connected = True
    client.on = MagicMock()
    client.connect = AsyncMock(return_value=True)
    client.run = AsyncMock()
    client.stop = MagicMock()
    client.close = AsyncMock()
    client.send_status = AsyncMock()
    client.send_heartbeat = AsyncMock()
    client.publish_task_message = AsyncMock()
    client.publish_task_complete = AsyncMock()
    client.publish_task_error = AsyncMock()
    client.publish_help_request = AsyncMock()
    return client
