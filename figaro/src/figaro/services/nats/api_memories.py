from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from figaro.db.models import MemoryModel
from figaro.db.repositories.memories import MemoryRepository

if TYPE_CHECKING:
    from figaro.services.nats.service import NatsService

logger = logging.getLogger(__name__)


def format_memory(m: MemoryModel) -> dict[str, Any]:
    """Serialize a MemoryModel to a JSON-safe dict."""
    return {
        "memory_id": str(m.memory_id),
        "content": m.content,
        "collection": m.collection,
        "metadata": m.metadata_,
        "created_at": str(m.created_at),
        "updated_at": str(m.updated_at),
    }


async def api_save_memory(
    svc: NatsService, data: dict[str, Any]
) -> dict[str, Any]:
    """Save a memory via NATS API."""
    content = data.get("content", "")
    metadata = data.get("metadata", {})
    collection = data.get("collection", "default")

    if not content:
        return {"error": "content is required"}

    if not svc._session_factory:
        return {"error": "database not available"}

    embedding = await svc._embedding_service.embed_one(content)

    async with svc._session_factory() as session:
        repo = MemoryRepository(session)
        memory = await repo.save(content, collection, metadata, embedding)
        await session.commit()
        return format_memory(memory)


async def api_search_memories(
    svc: NatsService, data: dict[str, Any]
) -> dict[str, Any]:
    """Search memories via NATS API."""
    query = data.get("query", "")
    collection = data.get("collection")
    limit = min(data.get("limit", 10), 200)

    if not query:
        return {"error": "query is required"}

    if not svc._session_factory:
        return {"error": "database not available"}

    query_embedding = await svc._embedding_service.embed_one(query)

    async with svc._session_factory() as session:
        repo = MemoryRepository(session)
        results = await repo.search_hybrid(query, query_embedding, collection, limit)
        return {"results": results}


async def api_delete_memory(
    svc: NatsService, data: dict[str, Any]
) -> dict[str, Any]:
    """Delete a memory via NATS API."""
    memory_id = data.get("memory_id", "")

    if not memory_id:
        return {"error": "memory_id is required"}

    if not svc._session_factory:
        return {"error": "database not available"}

    async with svc._session_factory() as session:
        repo = MemoryRepository(session)
        deleted = await repo.delete(memory_id)
        await session.commit()
        return {"status": "ok", "deleted": deleted}


async def api_list_memories(
    svc: NatsService, data: dict[str, Any]
) -> dict[str, Any]:
    """List memories via NATS API."""
    collection = data.get("collection")
    limit = min(data.get("limit", 50), 200)

    if not svc._session_factory:
        return {"error": "database not available"}

    async with svc._session_factory() as session:
        repo = MemoryRepository(session)
        memories = await repo.list_all(collection, limit)
        return {"memories": [format_memory(m) for m in memories]}
