"""Tests for HelpRequestRepository database operations."""

import pytest
from uuid import uuid4

from figaro.db.models import HelpRequestStatus
from figaro.db.repositories.tasks import TaskRepository
from figaro.db.repositories.help_requests import HelpRequestRepository


class TestHelpRequestRepository:
    """Tests for HelpRequestRepository."""

    @pytest.fixture
    async def task_repo(self, db_session):
        """Create a TaskRepository instance."""
        return TaskRepository(db_session)

    @pytest.fixture
    async def repo(self, db_session):
        """Create a HelpRequestRepository instance."""
        return HelpRequestRepository(db_session)

    @pytest.fixture
    async def task(self, task_repo, db_session):
        """Create a task for help requests to reference."""
        task = await task_repo.create(prompt="Test task")
        await db_session.commit()
        return task

    async def test_create_help_request(self, repo, task, db_session):
        """Test creating a new help request."""
        request = await repo.create(
            task_id=task.task_id,
            worker_id="worker-1",
            questions=[
                {"question": "What should I do?", "header": "Action"},
            ],
        )
        await db_session.commit()

        assert request.request_id is not None
        assert request.task_id == task.task_id
        assert request.worker_id == "worker-1"
        assert len(request.questions) == 1
        assert request.status == HelpRequestStatus.PENDING
        assert request.answers is None

    async def test_create_with_all_options(self, repo, task, db_session):
        """Test creating a help request with all options."""
        request = await repo.create(
            task_id=task.task_id,
            worker_id="worker-1",
            questions=[{"question": "Help?"}],
            context={"current_page": "https://example.com"},
            timeout_seconds=600,
            telegram_chat_id=12345,
            telegram_message_id=67890,
        )
        await db_session.commit()

        assert request.context == {"current_page": "https://example.com"}
        assert request.timeout_seconds == 600
        assert request.telegram_chat_id == 12345
        assert request.telegram_message_id == 67890

    async def test_create_with_specific_id(self, repo, task, db_session):
        """Test creating a help request with a specific ID."""
        request_id = str(uuid4())
        request = await repo.create(
            task_id=task.task_id,
            worker_id="worker-1",
            questions=[{"question": "Help?"}],
            request_id=request_id,
        )
        await db_session.commit()

        assert request.request_id == request_id

    async def test_get_help_request(self, repo, task, db_session):
        """Test getting a help request by ID."""
        created = await repo.create(
            task_id=task.task_id,
            worker_id="worker-1",
            questions=[{"question": "Help?"}],
        )
        await db_session.commit()

        fetched = await repo.get(created.request_id)
        assert fetched is not None
        assert fetched.request_id == created.request_id

    async def test_get_not_found(self, repo):
        """Test getting a non-existent help request."""
        fetched = await repo.get(str(uuid4()))
        assert fetched is None

    async def test_get_by_task(self, repo, task, db_session):
        """Test getting all help requests for a task."""
        await repo.create(
            task_id=task.task_id,
            worker_id="worker-1",
            questions=[{"question": "First question"}],
        )
        await repo.create(
            task_id=task.task_id,
            worker_id="worker-1",
            questions=[{"question": "Second question"}],
        )
        await db_session.commit()

        requests = await repo.get_by_task(task.task_id)
        assert len(requests) == 2

    async def test_list_pending(self, repo, task, db_session):
        """Test listing pending help requests."""
        request1 = await repo.create(
            task_id=task.task_id,
            worker_id="worker-1",
            questions=[{"question": "Help 1?"}],
        )
        await repo.create(
            task_id=task.task_id,
            worker_id="worker-1",
            questions=[{"question": "Help 2?"}],
        )
        await db_session.commit()

        # Respond to one
        await repo.respond(request1.request_id, {"0": "Answer 1"})
        await db_session.commit()

        pending = await repo.list_pending()
        assert len(pending) == 1

    async def test_respond(self, repo, task, db_session):
        """Test responding to a help request."""
        request = await repo.create(
            task_id=task.task_id,
            worker_id="worker-1",
            questions=[{"question": "Help?"}],
        )
        await db_session.commit()

        responded = await repo.respond(
            request.request_id,
            answers={"0": "Do this!"},
            response_source="telegram",
        )
        await db_session.commit()

        assert responded is not None
        assert responded.status == HelpRequestStatus.RESPONDED
        assert responded.answers == {"0": "Do this!"}
        assert responded.response_source == "telegram"
        assert responded.responded_at is not None

    async def test_respond_already_responded_returns_none(self, repo, task, db_session):
        """Test that responding to an already responded request returns None."""
        request = await repo.create(
            task_id=task.task_id,
            worker_id="worker-1",
            questions=[{"question": "Help?"}],
        )
        await db_session.commit()

        await repo.respond(request.request_id, {"0": "First answer"})
        await db_session.commit()

        result = await repo.respond(request.request_id, {"0": "Second answer"})
        assert result is None

    async def test_timeout(self, repo, task, db_session):
        """Test timing out a help request."""
        request = await repo.create(
            task_id=task.task_id,
            worker_id="worker-1",
            questions=[{"question": "Help?"}],
        )
        await db_session.commit()

        timed_out = await repo.timeout(request.request_id)
        await db_session.commit()

        assert timed_out is not None
        assert timed_out.status == HelpRequestStatus.TIMEOUT

    async def test_timeout_already_responded_returns_none(self, repo, task, db_session):
        """Test that timing out a responded request returns None."""
        request = await repo.create(
            task_id=task.task_id,
            worker_id="worker-1",
            questions=[{"question": "Help?"}],
        )
        await db_session.commit()

        await repo.respond(request.request_id, {"0": "Answer"})
        await db_session.commit()

        result = await repo.timeout(request.request_id)
        assert result is None

    async def test_cancel(self, repo, task, db_session):
        """Test cancelling a help request."""
        request = await repo.create(
            task_id=task.task_id,
            worker_id="worker-1",
            questions=[{"question": "Help?"}],
        )
        await db_session.commit()

        cancelled = await repo.cancel(request.request_id)
        await db_session.commit()

        assert cancelled is not None
        assert cancelled.status == HelpRequestStatus.CANCELLED

    async def test_cancel_already_responded_returns_none(self, repo, task, db_session):
        """Test that cancelling a responded request returns None."""
        request = await repo.create(
            task_id=task.task_id,
            worker_id="worker-1",
            questions=[{"question": "Help?"}],
        )
        await db_session.commit()

        await repo.respond(request.request_id, {"0": "Answer"})
        await db_session.commit()

        result = await repo.cancel(request.request_id)
        assert result is None

    async def test_update_telegram_info(self, repo, task, db_session):
        """Test updating Telegram info for a help request."""
        request = await repo.create(
            task_id=task.task_id,
            worker_id="worker-1",
            questions=[{"question": "Help?"}],
        )
        await db_session.commit()

        updated = await repo.update_telegram_info(
            request.request_id,
            chat_id=12345,
            message_id=67890,
        )
        await db_session.commit()

        assert updated is not None
        assert updated.telegram_chat_id == 12345
        assert updated.telegram_message_id == 67890

    async def test_help_request_lifecycle(self, repo, task, db_session):
        """Test complete help request lifecycle."""
        # Create
        request = await repo.create(
            task_id=task.task_id,
            worker_id="worker-1",
            questions=[
                {"question": "Should I click the button?", "header": "Action"},
                {"question": "What credentials to use?", "header": "Auth"},
            ],
            context={"screenshot": "base64..."},
            timeout_seconds=300,
        )
        await db_session.commit()

        assert request.status == HelpRequestStatus.PENDING

        # Update Telegram info after sending
        await repo.update_telegram_info(request.request_id, 12345, 67890)
        await db_session.commit()

        # Verify pending
        pending = await repo.list_pending()
        assert len(pending) == 1

        # Respond
        responded = await repo.respond(
            request.request_id,
            answers={"0": "Yes, click it", "1": "Use test credentials"},
            response_source="telegram",
        )
        await db_session.commit()

        assert responded.status == HelpRequestStatus.RESPONDED
        assert responded.response_source == "telegram"

        # Verify no longer pending
        pending = await repo.list_pending()
        assert len(pending) == 0

    async def test_list_recent_returns_all_statuses(self, repo, task, db_session):
        """Test list_recent returns requests regardless of status."""
        req1 = await repo.create(
            task_id=task.task_id,
            worker_id="worker-1",
            questions=[{"question": "Q1"}],
        )
        req2 = await repo.create(
            task_id=task.task_id,
            worker_id="worker-1",
            questions=[{"question": "Q2"}],
        )
        req3 = await repo.create(
            task_id=task.task_id,
            worker_id="worker-1",
            questions=[{"question": "Q3"}],
        )
        await db_session.commit()

        # Set different statuses
        await repo.respond(req1.request_id, {"0": "A1"})
        await repo.timeout(req2.request_id)
        await db_session.commit()

        recent = await repo.list_recent()
        assert len(recent) == 3

        statuses = {r.request_id: r.status for r in recent}
        assert statuses[req1.request_id] == HelpRequestStatus.RESPONDED
        assert statuses[req2.request_id] == HelpRequestStatus.TIMEOUT
        assert statuses[req3.request_id] == HelpRequestStatus.PENDING

    async def test_list_recent_respects_limit(self, repo, task, db_session):
        """Test list_recent respects the limit parameter."""
        for i in range(5):
            await repo.create(
                task_id=task.task_id,
                worker_id="worker-1",
                questions=[{"question": f"Q{i}"}],
            )
        await db_session.commit()

        recent = await repo.list_recent(limit=3)
        assert len(recent) == 3

    async def test_list_recent_returns_all_created(self, repo, task, db_session):
        """Test list_recent returns all created requests."""
        req1 = await repo.create(
            task_id=task.task_id,
            worker_id="worker-1",
            questions=[{"question": "First"}],
        )
        req2 = await repo.create(
            task_id=task.task_id,
            worker_id="worker-1",
            questions=[{"question": "Second"}],
        )
        await db_session.commit()

        recent = await repo.list_recent()
        ids = {r.request_id for r in recent}
        assert req1.request_id in ids
        assert req2.request_id in ids

    async def test_list_recent_empty(self, repo):
        """Test list_recent returns empty list when no requests exist."""
        recent = await repo.list_recent()
        assert recent == []

    async def test_multiple_requests_different_statuses(self, repo, task, db_session):
        """Test multiple help requests with different statuses."""
        req1 = await repo.create(
            task_id=task.task_id,
            worker_id="worker-1",
            questions=[{"question": "Q1"}],
        )
        req2 = await repo.create(
            task_id=task.task_id,
            worker_id="worker-1",
            questions=[{"question": "Q2"}],
        )
        req3 = await repo.create(
            task_id=task.task_id,
            worker_id="worker-1",
            questions=[{"question": "Q3"}],
        )
        await db_session.commit()

        # Different outcomes
        await repo.respond(req1.request_id, {"0": "A1"})
        await repo.timeout(req2.request_id)
        await db_session.commit()

        # Check states
        fetched1 = await repo.get(req1.request_id)
        fetched2 = await repo.get(req2.request_id)
        fetched3 = await repo.get(req3.request_id)

        assert fetched1.status == HelpRequestStatus.RESPONDED
        assert fetched2.status == HelpRequestStatus.TIMEOUT
        assert fetched3.status == HelpRequestStatus.PENDING
