"""
pgvector store backend.

Stores vectors in PostgreSQL using the pgvector extension.  Each logical
``index`` maps to a separate table named ``vectors_{index}``.

Install extras:
    pip install "embed-core[pgvector]"

Prerequisites:
    CREATE EXTENSION IF NOT EXISTS vector;
"""

from __future__ import annotations

import json
import logging
from typing import Any

from embed_core.models import SearchResult, UpsertResult, Vector
from embed_core.stores.base import VectorStore

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS vectors_{index} (
    id          TEXT PRIMARY KEY,
    embedding   vector({dim}),
    metadata    JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    modality    TEXT NOT NULL DEFAULT 'text',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS vectors_{index}_embedding_idx
    ON vectors_{index}
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
"""


class PgVectorStore(VectorStore):
    """PostgreSQL + pgvector vector store.

    Args:
        dsn: asyncpg-compatible DSN, e.g.
            ``"postgresql://user:pass@host:5432/dbname"``.
        dimension: Vector dimension — must match the provider's dimension.
        pool_min_size: Minimum connection pool size.
        pool_max_size: Maximum connection pool size.
    """

    def __init__(
        self,
        dsn: str,
        dimension: int,
        pool_min_size: int = 2,
        pool_max_size: int = 10,
    ) -> None:
        self._dsn = dsn
        self._dimension = dimension
        self._pool_min = pool_min_size
        self._pool_max = pool_max_size
        self._pool: Any = None
        self._indices: set[str] = set()

    async def initialize(self) -> None:
        try:
            import asyncpg
        except ImportError as exc:
            raise ImportError(
                "Install the 'pgvector' extras: pip install 'embed-core[pgvector]'"
            ) from exc

        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=self._pool_min,
            max_size=self._pool_max,
            init=self._init_connection,
        )
        logger.info("pgvector pool created (min=%d max=%d)", self._pool_min, self._pool_max)

    @staticmethod
    async def _init_connection(conn: Any) -> None:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        # Register the pgvector codec so asyncpg can serialise vector[] <-> list[float]
        await conn.execute("SELECT NULL::vector")

    async def _ensure_index(self, conn: Any, index: str) -> None:
        if index not in self._indices:
            ddl = _DDL.format(index=index, dim=self._dimension)
            await conn.execute(ddl)
            self._indices.add(index)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()

    async def upsert(self, vectors: list[Vector], index: str = "default") -> UpsertResult:
        async with self._pool.acquire() as conn:
            await self._ensure_index(conn, index)
            failed: list[str] = []
            async with conn.transaction():
                for v in vectors:
                    try:
                        await conn.execute(
                            f"""
                            INSERT INTO vectors_{index} (id, embedding, metadata, modality)
                            VALUES ($1, $2::vector, $3::jsonb, $4)
                            ON CONFLICT (id) DO UPDATE
                                SET embedding  = EXCLUDED.embedding,
                                    metadata   = EXCLUDED.metadata,
                                    modality   = EXCLUDED.modality,
                                    updated_at = NOW()
                            """,
                            v.id,
                            str(v.values),  # asyncpg accepts '[x,y,...]' string for vector
                            json.dumps(v.metadata),
                            v.modality.value,
                        )
                    except Exception:
                        logger.exception("Failed to upsert vector id=%s", v.id)
                        failed.append(v.id)
        return UpsertResult(upserted_count=len(vectors) - len(failed), failed_ids=failed)

    async def search(
        self,
        query_vector: list[float],
        index: str = "default",
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        async with self._pool.acquire() as conn:
            await self._ensure_index(conn, index)
            # Build optional metadata filter clause
            where = ""
            params: list[Any] = [str(query_vector), top_k]
            if filters:
                conditions = []
                for key, val in filters.items():
                    params.append(json.dumps({key: val}))
                    conditions.append(f"metadata @> ${len(params)}::jsonb")
                where = "WHERE " + " AND ".join(conditions)

            rows = await conn.fetch(
                f"""
                SELECT id,
                       1 - (embedding <=> $1::vector) AS score,
                       metadata
                FROM   vectors_{index}
                {where}
                ORDER  BY embedding <=> $1::vector
                LIMIT  $2
                """,
                *params,
            )
        return [
            SearchResult(id=r["id"], score=float(r["score"]), metadata=json.loads(r["metadata"]))
            for r in rows
        ]

    async def delete(self, ids: list[str], index: str = "default") -> None:
        async with self._pool.acquire() as conn:
            await self._ensure_index(conn, index)
            await conn.execute(
                f"DELETE FROM vectors_{index} WHERE id = ANY($1::text[])", ids
            )

    async def list_indices(self) -> list[str]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT table_name
                FROM   information_schema.tables
                WHERE  table_schema = 'public'
                  AND  table_name   LIKE 'vectors_%'
                """
            )
        return [r["table_name"].removeprefix("vectors_") for r in rows]

    async def count(self, index: str = "default") -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT COUNT(*) AS n FROM vectors_{index}")
            return int(row["n"])
