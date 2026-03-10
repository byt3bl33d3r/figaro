"""Memory repository for database operations."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from figaro.db.models import MemoryModel

# RRF (Reciprocal Rank Fusion) constants
RRF_K = 60  # Standard RRF constant (Cormack et al., 2009)
RRF_TOP1_BOOST = 0.05  # Extra weight for the #1 result to break ties
RRF_TOP3_BOOST = 0.02  # Extra weight for top-3 results
RRF_PRIMARY_WEIGHT = 2.0  # BM25 (primary signal) gets 2x weight in fusion


def _collection_filter(collection: str | None, params: dict[str, Any]) -> str:
    """Return a SQL AND clause for collection filtering, updating params."""
    if collection is not None:
        params["collection"] = collection
        return " AND collection = :collection"
    return ""


def _rrf_score(rank: int, weight: float = 1.0) -> float:
    """Compute RRF score with top-result boosting and list weighting."""
    score = weight / (RRF_K + rank + 1)
    if rank == 0:
        score += RRF_TOP1_BOOST
    elif rank <= 2:
        score += RRF_TOP3_BOOST
    return score


class MemoryRepository:
    """Repository for memory database operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(
        self,
        content: str,
        collection: str,
        metadata: dict[str, Any],
        embedding: list[float] | None,
    ) -> MemoryModel:
        """Save a memory, upserting by (collection, content_hash)."""
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        result = await self.session.execute(
            select(MemoryModel).where(
                MemoryModel.collection == collection,
                MemoryModel.content_hash == content_hash,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.content = content
            existing.metadata_ = metadata
            existing.embedding = embedding
            existing.updated_at = datetime.now(timezone.utc)
            await self.session.flush()
            return existing

        model = MemoryModel(
            content=content,
            content_hash=content_hash,
            collection=collection,
            metadata_=metadata,
            embedding=embedding,
        )
        self.session.add(model)
        await self.session.flush()
        return model

    async def _batch_get_memories(
        self, memory_ids: list[str]
    ) -> dict[str, MemoryModel]:
        """Load multiple MemoryModel instances in a single query."""
        if not memory_ids:
            return {}
        result = await self.session.execute(
            select(MemoryModel).where(MemoryModel.memory_id.in_(memory_ids))
        )
        return {m.memory_id: m for m in result.scalars().all()}

    async def _search_bm25_ids(
        self,
        query: str,
        collection: str | None,
        limit: int,
    ) -> list[tuple[str, float]]:
        """Return (memory_id, normalized_score) via BM25 full-text search."""
        params: dict[str, Any] = {"query": query, "limit": limit}
        col_filter = _collection_filter(collection, params)

        sql = text(
            "SELECT memory_id, paradedb.score(memory_id) AS score "
            "FROM memories "
            f"WHERE content @@@ :query{col_filter} "
            "ORDER BY score DESC "
            "LIMIT :limit"
        )

        result = await self.session.execute(sql, params)
        return [
            (row.memory_id, abs(row.score) / (1.0 + abs(row.score)))
            for row in result.fetchall()
        ]

    async def _search_vector_ids(
        self,
        embedding: list[float],
        collection: str | None,
        limit: int,
    ) -> list[tuple[str, float]]:
        """Return (memory_id, similarity) via pgvector cosine distance."""
        embedding_str = f"[{','.join(str(v) for v in embedding)}]"
        params: dict[str, Any] = {"query_embedding": embedding_str, "limit": limit}
        col_filter = _collection_filter(collection, params)

        sql = text(
            "SELECT memory_id, embedding <=> :query_embedding AS distance "
            "FROM memories "
            f"WHERE embedding IS NOT NULL{col_filter} "
            "ORDER BY distance ASC "
            "LIMIT :limit"
        )

        result = await self.session.execute(sql, params)
        return [
            (row.memory_id, 1.0 - float(row.distance))
            for row in result.fetchall()
        ]

    async def search_hybrid(
        self,
        query_text: str,
        query_embedding: list[float] | None,
        collection: str | None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search memories using hybrid BM25 + vector search with RRF fusion."""
        fetch_limit = limit * 2

        bm25_ids = await self._search_bm25_ids(query_text, collection, fetch_limit)

        vector_ids: list[tuple[str, float]] = []
        if query_embedding is not None:
            vector_ids = await self._search_vector_ids(
                query_embedding, collection, fetch_limit
            )

        # RRF score fusion
        scores: dict[str, float] = {}
        for rank, (mid, _score) in enumerate(bm25_ids):
            scores[mid] = scores.get(mid, 0.0) + _rrf_score(rank, RRF_PRIMARY_WEIGHT)
        for rank, (mid, _score) in enumerate(vector_ids):
            scores[mid] = scores.get(mid, 0.0) + _rrf_score(rank)

        sorted_ids = sorted(scores, key=lambda mid: scores[mid], reverse=True)[:limit]

        # Single batch fetch for all matched memories
        memory_map = await self._batch_get_memories(sorted_ids)

        results: list[dict[str, Any]] = []
        for mid in sorted_ids:
            memory = memory_map.get(mid)
            if not memory:
                continue
            results.append(
                {
                    "memory_id": memory.memory_id,
                    "content": memory.content,
                    "metadata": memory.metadata_,
                    "score": scores[mid],
                    "collection": memory.collection,
                    "created_at": str(memory.created_at),
                }
            )
        return results

    async def delete(self, memory_id: str) -> bool:
        """Delete a memory by ID.

        Args:
            memory_id: The memory UUID to delete

        Returns:
            True if the memory was found and deleted, False otherwise
        """
        result = await self.session.execute(
            delete(MemoryModel).where(MemoryModel.memory_id == memory_id)
        )
        return (cast(CursorResult[Any], result).rowcount or 0) > 0

    async def list_all(
        self,
        collection: str | None,
        limit: int,
    ) -> list[MemoryModel]:
        """List memories with optional collection filter.

        Args:
            collection: Optional collection filter
            limit: Maximum number of results

        Returns:
            List of MemoryModel instances ordered by updated_at DESC
        """
        query = select(MemoryModel)

        if collection is not None:
            query = query.where(MemoryModel.collection == collection)

        query = query.order_by(MemoryModel.updated_at.desc()).limit(limit)

        result = await self.session.execute(query)
        return list(result.scalars().all())
