"""
Abstract base class for all vector store backends.

Stores are responsible for persisting vectors and serving approximate-
nearest-neighbour (ANN) queries.  Concrete implementations may wrap
pgvector, Pinecone, or OpenSearch — consumers must not depend on any of
them directly.
"""

from __future__ import annotations

import abc
from typing import Any

from embed_core.models import SearchResult, UpsertResult, Vector


class VectorStore(abc.ABC):
    """Async vector persistence and retrieval backend."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create schema / index if it does not already exist.

        Called once at startup.  Implementations should be idempotent.
        """

    async def close(self) -> None:
        """Release connections / clients."""

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def upsert(self, vectors: list[Vector], index: str = "default") -> UpsertResult:
        """Insert or update vectors in *index*.

        Args:
            vectors: Batch of :class:`Vector` records.
            index: Logical index / namespace name.

        Returns:
            :class:`UpsertResult` with counts and any failed IDs.
        """

    @abc.abstractmethod
    async def search(
        self,
        query_vector: list[float],
        index: str = "default",
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Return the *top_k* most similar vectors.

        Args:
            query_vector: Dense float vector to search against.
            index: Logical index / namespace name.
            top_k: Maximum number of results to return.
            filters: Optional metadata equality filters (backend-specific
                     semantics, best-effort).

        Returns:
            List of :class:`SearchResult`, ordered by descending similarity.
        """

    @abc.abstractmethod
    async def delete(self, ids: list[str], index: str = "default") -> None:
        """Delete vectors by ID from *index*."""

    # ------------------------------------------------------------------
    # Optional helpers
    # ------------------------------------------------------------------

    async def list_indices(self) -> list[str]:
        """Return names of all indices managed by this store."""
        raise NotImplementedError(f"{type(self).__name__} does not implement list_indices()")

    async def count(self, index: str = "default") -> int:
        """Return the number of vectors in *index*."""
        raise NotImplementedError(f"{type(self).__name__} does not implement count()")

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"
