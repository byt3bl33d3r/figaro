"""Tests for the memories NATS API handlers."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


from figaro.db.models import MemoryModel
from figaro.services.nats.api_memories import (
    api_delete_memory,
    api_list_memories,
    api_save_memory,
    api_search_memories,
)


def _make_memory(
    memory_id: str = "mem-1",
    content: str = "test memory",
    collection: str = "default",
    metadata: dict | None = None,
) -> MemoryModel:
    m = MemoryModel()
    m.memory_id = memory_id
    m.content = content
    m.collection = collection
    m.metadata_ = metadata or {}
    m.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    m.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return m


def _make_svc(
    embed_return: list[float] | None = None,
) -> MagicMock:
    svc = MagicMock()
    svc._embedding_service = MagicMock()
    svc._embedding_service.embed_one = AsyncMock(return_value=embed_return)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()
    svc._session_factory = MagicMock(return_value=mock_session)
    svc._mock_session = mock_session
    return svc


class TestApiSaveMemory:
    async def test_save_memory_success(self):
        svc = _make_svc(embed_return=[0.1, 0.2])
        memory = _make_memory()

        with patch(
            "figaro.services.nats.api_memories.MemoryRepository"
        ) as MockRepo:
            MockRepo.return_value.save = AsyncMock(return_value=memory)
            result = await api_save_memory(svc, {"content": "test memory"})

        assert result["memory_id"] == "mem-1"
        assert result["content"] == "test memory"
        assert result["collection"] == "default"

    async def test_save_memory_empty_content(self):
        svc = _make_svc()
        result = await api_save_memory(svc, {"content": ""})
        assert result == {"error": "content is required"}

    async def test_save_memory_no_db(self):
        svc = _make_svc()
        svc._session_factory = None
        result = await api_save_memory(svc, {"content": "test"})
        assert result == {"error": "database not available"}


class TestApiSearchMemories:
    async def test_search_memories_success(self):
        svc = _make_svc(embed_return=[0.1, 0.2])

        with patch(
            "figaro.services.nats.api_memories.MemoryRepository"
        ) as MockRepo:
            MockRepo.return_value.search_hybrid = AsyncMock(
                return_value=[
                    {
                        "memory_id": "mem-1",
                        "content": "test",
                        "metadata": {},
                        "score": 0.95,
                        "collection": "default",
                        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                    }
                ]
            )
            result = await api_search_memories(
                svc, {"query": "test", "limit": 5}
            )

        assert len(result["results"]) == 1
        assert result["results"][0]["memory_id"] == "mem-1"

    async def test_search_memories_empty_query(self):
        svc = _make_svc()
        result = await api_search_memories(svc, {"query": ""})
        assert result == {"error": "query is required"}

    async def test_search_memories_no_db(self):
        svc = _make_svc()
        svc._session_factory = None
        result = await api_search_memories(svc, {"query": "test"})
        assert result == {"error": "database not available"}


class TestApiDeleteMemory:
    async def test_delete_memory_success(self):
        svc = _make_svc()

        with patch(
            "figaro.services.nats.api_memories.MemoryRepository"
        ) as MockRepo:
            MockRepo.return_value.delete = AsyncMock(return_value=True)
            result = await api_delete_memory(svc, {"memory_id": "mem-1"})

        assert result == {"status": "ok", "deleted": True}

    async def test_delete_memory_empty_id(self):
        svc = _make_svc()
        result = await api_delete_memory(svc, {"memory_id": ""})
        assert result == {"error": "memory_id is required"}

    async def test_delete_memory_no_db(self):
        svc = _make_svc()
        svc._session_factory = None
        result = await api_delete_memory(svc, {"memory_id": "mem-1"})
        assert result == {"error": "database not available"}


class TestApiListMemories:
    async def test_list_memories_success(self):
        svc = _make_svc()
        memories = [_make_memory("mem-1"), _make_memory("mem-2", content="second")]

        with patch(
            "figaro.services.nats.api_memories.MemoryRepository"
        ) as MockRepo:
            MockRepo.return_value.list_all = AsyncMock(return_value=memories)
            result = await api_list_memories(svc, {"limit": 50})

        assert len(result["memories"]) == 2
        assert result["memories"][0]["memory_id"] == "mem-1"
        assert result["memories"][1]["content"] == "second"

    async def test_list_memories_with_collection(self):
        svc = _make_svc()

        with patch(
            "figaro.services.nats.api_memories.MemoryRepository"
        ) as MockRepo:
            MockRepo.return_value.list_all = AsyncMock(return_value=[])
            result = await api_list_memories(
                svc, {"collection": "project-x", "limit": 10}
            )

        assert result == {"memories": []}
        MockRepo.return_value.list_all.assert_awaited_once_with("project-x", 10)

    async def test_list_memories_no_db(self):
        svc = _make_svc()
        svc._session_factory = None
        result = await api_list_memories(svc, {})
        assert result == {"error": "database not available"}
