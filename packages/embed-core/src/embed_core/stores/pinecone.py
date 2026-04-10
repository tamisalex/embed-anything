"""
Pinecone vector store backend.

Each logical ``index`` maps to a Pinecone index.  The *namespace* feature
is used within a single Pinecone index to cheaply implement multiple
logical namespaces when you want to share an index across indices.

Install extras:
    pip install "embed-core[pinecone]"
"""

from __future__ import annotations

import logging
from typing import Any

from embed_core.models import SearchResult, UpsertResult, Vector
from embed_core.stores.base import VectorStore

logger = logging.getLogger(__name__)

_UPSERT_BATCH = 100  # Pinecone recommends ≤ 100 vectors per upsert call


class PineconeVectorStore(VectorStore):
    """Pinecone serverless vector store.

    Args:
        api_key: Pinecone API key.  Defaults to ``PINECONE_API_KEY`` env var.
        index_name: Name of the Pinecone index to use.
        dimension: Vector dimension — must match the provider and the index.
        metric: Distance metric (``"cosine"``, ``"euclidean"``, ``"dotproduct"``).
        cloud: Cloud provider for serverless (``"aws"``, ``"gcp"``, ``"azure"``).
        region: Cloud region for serverless, e.g. ``"us-east-1"``.
    """

    def __init__(
        self,
        api_key: str | None = None,
        index_name: str = "embed-anything",
        dimension: int = 512,
        metric: str = "cosine",
        cloud: str = "aws",
        region: str = "us-east-1",
    ) -> None:
        self._api_key = api_key
        self._index_name = index_name
        self._dimension = dimension
        self._metric = metric
        self._cloud = cloud
        self._region = region
        self._index: Any = None

    async def initialize(self) -> None:
        try:
            from pinecone import Pinecone, ServerlessSpec
        except ImportError as exc:
            raise ImportError(
                "Install the 'pinecone' extras: pip install 'embed-core[pinecone]'"
            ) from exc

        kwargs: dict[str, Any] = {}
        if self._api_key:
            kwargs["api_key"] = self._api_key

        pc = Pinecone(**kwargs)

        existing = {idx.name for idx in pc.list_indexes()}
        if self._index_name not in existing:
            logger.info("Creating Pinecone index '%s'", self._index_name)
            pc.create_index(
                name=self._index_name,
                dimension=self._dimension,
                metric=self._metric,
                spec=ServerlessSpec(cloud=self._cloud, region=self._region),
            )
        self._index = pc.Index(self._index_name)
        logger.info("Pinecone index '%s' ready", self._index_name)

    async def upsert(self, vectors: list[Vector], index: str = "default") -> UpsertResult:
        if self._index is None:
            raise RuntimeError("Call initialize() before upsert()")

        records = [
            {"id": v.id, "values": v.values, "metadata": v.metadata} for v in vectors
        ]
        failed: list[str] = []
        for i in range(0, len(records), _UPSERT_BATCH):
            batch = records[i : i + _UPSERT_BATCH]
            try:
                self._index.upsert(vectors=batch, namespace=index)
            except Exception:
                logger.exception("Pinecone upsert failed for batch starting at %d", i)
                failed.extend(r["id"] for r in batch)

        return UpsertResult(upserted_count=len(vectors) - len(failed), failed_ids=failed)

    async def search(
        self,
        query_vector: list[float],
        index: str = "default",
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        if self._index is None:
            raise RuntimeError("Call initialize() before search()")

        kwargs: dict[str, Any] = {
            "vector": query_vector,
            "top_k": top_k,
            "namespace": index,
            "include_metadata": True,
        }
        if filters:
            kwargs["filter"] = filters

        response = self._index.query(**kwargs)
        return [
            SearchResult(
                id=match["id"],
                score=float(match["score"]),
                metadata=match.get("metadata") or {},
            )
            for match in response["matches"]
        ]

    async def delete(self, ids: list[str], index: str = "default") -> None:
        if self._index is None:
            raise RuntimeError("Call initialize() before delete()")
        self._index.delete(ids=ids, namespace=index)

    async def list_indices(self) -> list[str]:
        if self._index is None:
            raise RuntimeError("Call initialize() before list_indices()")
        stats = self._index.describe_index_stats()
        return list(stats.get("namespaces", {}).keys())

    async def count(self, index: str = "default") -> int:
        if self._index is None:
            raise RuntimeError("Call initialize() before count()")
        stats = self._index.describe_index_stats()
        ns = stats.get("namespaces", {}).get(index, {})
        return int(ns.get("vector_count", 0))
