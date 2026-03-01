"""Tests for figaro_supervisor main module (heartbeat, handlers)."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from figaro_supervisor import run_heartbeat
from figaro_supervisor.supervisor.client import SupervisorNatsClient


class TestRunHeartbeat:
    """Tests for run_heartbeat function."""

    @pytest.mark.asyncio
    async def test_heartbeat_sends_liveness_ping(self):
        """Test heartbeat sends liveness ping."""
        client = MagicMock(spec=SupervisorNatsClient)
        client.send_heartbeat = AsyncMock()

        heartbeat_task = asyncio.create_task(
            run_heartbeat(client, interval=0.01)
        )
        await asyncio.sleep(0.02)
        heartbeat_task.cancel()

        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

        client.send_heartbeat.assert_called()

    @pytest.mark.asyncio
    async def test_heartbeat_continues_after_failure(self):
        """Test heartbeat doesn't crash when send_heartbeat fails."""
        client = MagicMock(spec=SupervisorNatsClient)
        call_count = 0

        async def failing_send_heartbeat():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("NATS disconnected")

        client.send_heartbeat = failing_send_heartbeat

        heartbeat_task = asyncio.create_task(
            run_heartbeat(client, interval=0.01)
        )
        await asyncio.sleep(0.03)
        heartbeat_task.cancel()

        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_heartbeat_does_not_propagate_exception(self):
        """Test that exceptions in heartbeat don't propagate up."""
        client = MagicMock(spec=SupervisorNatsClient)
        client.send_heartbeat = AsyncMock(side_effect=Exception("Network error"))

        heartbeat_task = asyncio.create_task(
            run_heartbeat(client, interval=0.01)
        )

        await asyncio.sleep(0.03)
        assert not heartbeat_task.done()

        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
