"""Tests for the HelpRequestManager service."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from figaro.services.help_request import (
    HelpRequestManager,
    HelpRequestStatus,
)


class TestHelpRequestManager:
    @pytest.fixture
    def mock_nats_service(self):
        service = MagicMock()
        service.publish_help_response = AsyncMock()

        # Mock conn with publish method
        mock_conn = MagicMock()
        mock_conn.publish = AsyncMock()
        mock_conn.is_connected = True
        service.conn = mock_conn

        return service

    @pytest.fixture
    def manager(self, mock_nats_service):
        mgr = HelpRequestManager(default_timeout=60)
        mgr.set_nats_service(mock_nats_service)
        return mgr

    @pytest.fixture
    def sample_questions(self):
        return [
            {
                "question": "Which database should I use?",
                "header": "Database",
                "options": [
                    {"label": "PostgreSQL", "description": "Relational database"},
                    {"label": "MongoDB", "description": "Document database"},
                ],
                "multiSelect": False,
            }
        ]

    @pytest.mark.asyncio
    async def test_create_request(self, manager, sample_questions):
        request = await manager.create_request(
            worker_id="worker-1",
            task_id="task-1",
            questions=sample_questions,
            timeout_seconds=120,
        )

        assert request.request_id is not None
        assert request.worker_id == "worker-1"
        assert request.task_id == "task-1"
        assert request.questions == sample_questions
        assert request.timeout_seconds == 120
        assert request.status == HelpRequestStatus.PENDING
        assert request.answers is None

    @pytest.mark.asyncio
    async def test_create_request_uses_default_timeout(self, manager, sample_questions):
        request = await manager.create_request(
            worker_id="worker-1",
            task_id="task-1",
            questions=sample_questions,
        )

        assert request.timeout_seconds == 60  # Default from manager

    @pytest.mark.asyncio
    async def test_create_request_with_provided_request_id(
        self, manager, sample_questions
    ):
        """Test that provided request_id is preserved (for worker correlation)."""
        request = await manager.create_request(
            worker_id="worker-1",
            task_id="task-1",
            questions=sample_questions,
            request_id="worker-generated-id-123",
        )

        assert request.request_id == "worker-generated-id-123"
        assert request.worker_id == "worker-1"

    @pytest.mark.asyncio
    async def test_get_request(self, manager, sample_questions):
        created = await manager.create_request(
            worker_id="worker-1",
            task_id="task-1",
            questions=sample_questions,
        )

        retrieved = await manager.get_request(created.request_id)
        assert retrieved is not None
        assert retrieved.request_id == created.request_id

    @pytest.mark.asyncio
    async def test_get_request_not_found(self, manager):
        result = await manager.get_request("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_pending_requests(self, manager, sample_questions):
        await manager.create_request(
            worker_id="worker-1",
            task_id="task-1",
            questions=sample_questions,
        )
        await manager.create_request(
            worker_id="worker-2",
            task_id="task-2",
            questions=sample_questions,
        )

        pending = await manager.get_pending_requests()
        assert len(pending) == 2

    @pytest.mark.asyncio
    async def test_get_pending_by_worker(self, manager, sample_questions):
        await manager.create_request(
            worker_id="worker-1",
            task_id="task-1",
            questions=sample_questions,
        )
        await manager.create_request(
            worker_id="worker-2",
            task_id="task-2",
            questions=sample_questions,
        )

        worker1_pending = await manager.get_pending_by_worker("worker-1")
        assert len(worker1_pending) == 1
        assert worker1_pending[0].worker_id == "worker-1"

    @pytest.mark.asyncio
    async def test_respond_success(self, manager, mock_nats_service, sample_questions):
        request = await manager.create_request(
            worker_id="worker-1",
            task_id="task-1",
            questions=sample_questions,
        )

        answers = {"Which database should I use?": "PostgreSQL"}
        result = await manager.respond(request.request_id, answers, source="telegram")

        assert result is True

        # Verify NATS publish was called for help response
        mock_nats_service.publish_help_response.assert_called_once()
        call_kwargs = mock_nats_service.publish_help_response.call_args
        assert call_kwargs[1]["request_id"] == request.request_id
        assert call_kwargs[1]["worker_id"] == "worker-1"
        assert call_kwargs[1]["answers"] == answers

        # Verify UI broadcast via NATS
        mock_nats_service.conn.publish.assert_called()

        # Verify request state updated
        updated = await manager.get_request(request.request_id)
        assert updated.status == HelpRequestStatus.RESPONDED
        assert updated.answers == answers
        assert updated.response_source == "telegram"

    @pytest.mark.asyncio
    async def test_respond_not_found(self, manager):
        result = await manager.respond("nonexistent-id", {"answer": "test"})
        assert result is False

    @pytest.mark.asyncio
    async def test_respond_already_responded(self, manager, sample_questions):
        request = await manager.create_request(
            worker_id="worker-1",
            task_id="task-1",
            questions=sample_questions,
        )

        # First response
        await manager.respond(request.request_id, {"answer": "first"})

        # Second response should fail
        result = await manager.respond(request.request_id, {"answer": "second"})
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_request(self, manager, sample_questions):
        request = await manager.create_request(
            worker_id="worker-1",
            task_id="task-1",
            questions=sample_questions,
        )

        result = await manager.cancel_request(request.request_id)
        assert result is True

        updated = await manager.get_request(request.request_id)
        assert updated.status == HelpRequestStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_request_not_found(self, manager):
        result = await manager.cancel_request("nonexistent-id")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_request_already_responded(self, manager, sample_questions):
        request = await manager.create_request(
            worker_id="worker-1",
            task_id="task-1",
            questions=sample_questions,
        )

        await manager.respond(request.request_id, {"answer": "test"})
        result = await manager.cancel_request(request.request_id)
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_requests_for_worker(self, manager, sample_questions):
        await manager.create_request(
            worker_id="worker-1",
            task_id="task-1",
            questions=sample_questions,
        )
        await manager.create_request(
            worker_id="worker-1",
            task_id="task-2",
            questions=sample_questions,
        )
        await manager.create_request(
            worker_id="worker-2",
            task_id="task-3",
            questions=sample_questions,
        )

        cancelled = await manager.cancel_requests_for_worker("worker-1")
        assert cancelled == 2

        worker1_pending = await manager.get_pending_by_worker("worker-1")
        assert len(worker1_pending) == 0

        worker2_pending = await manager.get_pending_by_worker("worker-2")
        assert len(worker2_pending) == 1

    @pytest.mark.asyncio
    async def test_set_channel_message_id(self, manager, sample_questions):
        request = await manager.create_request(
            worker_id="worker-1",
            task_id="task-1",
            questions=sample_questions,
        )

        await manager.set_channel_message_id(
            request.request_id, chat_id=123456, message_id=789
        )

        updated = await manager.get_request(request.request_id)
        assert updated.channel_chat_id == 123456
        assert updated.channel_message_id == 789

    @pytest.mark.asyncio
    async def test_get_by_channel_message_id(self, manager, sample_questions):
        request = await manager.create_request(
            worker_id="worker-1",
            task_id="task-1",
            questions=sample_questions,
        )

        await manager.set_channel_message_id(
            request.request_id, chat_id=123456, message_id=789
        )

        found = await manager.get_by_channel_message_id(chat_id=123456, message_id=789)
        assert found is not None
        assert found.request_id == request.request_id

    @pytest.mark.asyncio
    async def test_get_by_channel_message_id_not_found(self, manager):
        result = await manager.get_by_channel_message_id(chat_id=123, message_id=456)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_requests(self, manager, sample_questions):
        """Test get_all_requests returns requests of all statuses."""
        req1 = await manager.create_request(
            worker_id="worker-1",
            task_id="task-1",
            questions=sample_questions,
        )
        req2 = await manager.create_request(
            worker_id="worker-2",
            task_id="task-2",
            questions=sample_questions,
        )
        req3 = await manager.create_request(
            worker_id="worker-3",
            task_id="task-3",
            questions=sample_questions,
        )

        # Respond to one, cancel another, leave third pending
        await manager.respond(req1.request_id, {"answer": "done"}, source="ui")
        await manager.cancel_request(req2.request_id)

        all_requests = await manager.get_all_requests()
        assert len(all_requests) == 3

        statuses = {r.request_id: r.status for r in all_requests}
        assert statuses[req1.request_id] == HelpRequestStatus.RESPONDED
        assert statuses[req2.request_id] == HelpRequestStatus.CANCELLED
        assert statuses[req3.request_id] == HelpRequestStatus.PENDING

    @pytest.mark.asyncio
    async def test_get_all_requests_empty(self, manager):
        """Test get_all_requests returns empty list when no requests exist."""
        all_requests = await manager.get_all_requests()
        assert all_requests == []

    @pytest.mark.asyncio
    async def test_get_all_vs_get_pending(self, manager, sample_questions):
        """Test that get_all_requests includes resolved requests that get_pending_requests excludes."""
        req1 = await manager.create_request(
            worker_id="worker-1",
            task_id="task-1",
            questions=sample_questions,
        )
        await manager.create_request(
            worker_id="worker-2",
            task_id="task-2",
            questions=sample_questions,
        )

        await manager.respond(req1.request_id, {"answer": "done"}, source="ui")

        pending = await manager.get_pending_requests()
        all_requests = await manager.get_all_requests()

        assert len(pending) == 1
        assert len(all_requests) == 2

    @pytest.mark.asyncio
    async def test_timeout_sends_error_to_worker(
        self, manager, mock_nats_service, sample_questions
    ):
        # Create request with very short timeout
        manager._default_timeout = 0.1

        request = await manager.create_request(
            worker_id="worker-1",
            task_id="task-1",
            questions=sample_questions,
            timeout_seconds=0.1,
        )

        # Wait for timeout
        await asyncio.sleep(0.3)

        # Verify request timed out
        updated = await manager.get_request(request.request_id)
        assert updated.status == HelpRequestStatus.TIMEOUT

        # Verify publish_help_response was called with error="timeout"
        timeout_calls = [
            call
            for call in mock_nats_service.publish_help_response.call_args_list
            if call[1].get("error") == "timeout"
        ]
        assert len(timeout_calls) >= 1
