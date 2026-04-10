"""
OpenSearch k-NN vector store backend.

Uses the OpenSearch k-NN plugin (``knn_vector`` field type) with HNSW
approximate nearest-neighbour search.  Compatible with:
  - Amazon OpenSearch Service (t3.small.search is free-tier eligible)
  - Self-hosted OpenSearch 2.x

Install extras:
    pip install "embed-core[opensearch]"
"""

from __future__ import annotations

import json
import logging
from typing import Any

from embed_core.models import SearchResult, UpsertResult, Vector
from embed_core.stores.base import VectorStore

logger = logging.getLogger(__name__)

_INDEX_BODY_TEMPLATE = {
    "settings": {
        "index": {
            "knn": True,
            "knn.algo_param.ef_search": 100,
        }
    },
    "mappings": {
        "properties": {
            "embedding": {
                "type": "knn_vector",
                # "dimension" injected at runtime
                "method": {
                    "name": "hnsw",
                    "space_type": "cosinesimil",
                    "engine": "nmslib",
                    "parameters": {"ef_construction": 128, "m": 16},
                },
            },
            "metadata": {"type": "object", "dynamic": True},
            "modality": {"type": "keyword"},
        }
    },
}

_BULK_CHUNK = 200  # documents per _bulk request


class OpenSearchVectorStore(VectorStore):
    """OpenSearch k-NN vector store.

    Args:
        host: OpenSearch host URL, e.g. ``"https://my-domain.us-east-1.es.amazonaws.com"``.
        dimension: Vector dimension — must match the provider.
        index_prefix: Prefix prepended to every logical index name (prevents
            collisions with other OpenSearch indices).
        http_auth: ``(username, password)`` tuple or ``None`` for IAM.
        use_ssl: Whether to use TLS.  Defaults to ``True``.
        verify_certs: Whether to verify TLS certificates.
    """

    def __init__(
        self,
        host: str = "https://localhost:9200",
        dimension: int = 512,
        index_prefix: str = "ea_",
        http_auth: tuple[str, str] | None = None,
        use_ssl: bool = True,
        verify_certs: bool = True,
    ) -> None:
        self._host = host
        self._dimension = dimension
        self._prefix = index_prefix
        self._http_auth = http_auth
        self._use_ssl = use_ssl
        self._verify_certs = verify_certs
        self._client: Any = None
        self._created_indices: set[str] = set()

    def _full_index(self, index: str) -> str:
        return f"{self._prefix}{index}"

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from opensearchpy import OpenSearch
            except ImportError as exc:
                raise ImportError(
                    "Install the 'opensearch' extras: pip install 'embed-core[opensearch]'"
                ) from exc
            kwargs: dict[str, Any] = {
                "hosts": [self._host],
                "use_ssl": self._use_ssl,
                "verify_certs": self._verify_certs,
            }
            if self._http_auth:
                kwargs["http_auth"] = self._http_auth
            self._client = OpenSearch(**kwargs)
        return self._client

    async def _ensure_index(self, index: str) -> None:
        if index in self._created_indices:
            return
        client = self._get_client()
        full = self._full_index(index)
        if not client.indices.exists(full):
            body = json.loads(json.dumps(_INDEX_BODY_TEMPLATE))  # deep copy
            body["mappings"]["properties"]["embedding"]["dimension"] = self._dimension
            client.indices.create(index=full, body=body)
            logger.info("Created OpenSearch index '%s'", full)
        self._created_indices.add(index)

    async def close(self) -> None:
        if self._client:
            self._client.close()

    async def upsert(self, vectors: list[Vector], index: str = "default") -> UpsertResult:
        await self._ensure_index(index)
        client = self._get_client()
        full = self._full_index(index)
        failed: list[str] = []

        for i in range(0, len(vectors), _BULK_CHUNK):
            batch = vectors[i : i + _BULK_CHUNK]
            actions: list[dict[str, Any]] = []
            for v in batch:
                actions.append({"index": {"_index": full, "_id": v.id}})
                actions.append(
                    {
                        "embedding": v.values,
                        "metadata": v.metadata,
                        "modality": v.modality.value,
                    }
                )
            try:
                resp = client.bulk(body=actions)
                if resp.get("errors"):
                    for item in resp["items"]:
                        op = item.get("index", {})
                        if op.get("error"):
                            failed.append(op["_id"])
                            logger.error("OpenSearch bulk error for id=%s: %s", op["_id"], op["error"])
            except Exception:
                logger.exception("OpenSearch bulk upsert failed for batch starting at %d", i)
                failed.extend(v.id for v in batch)

        return UpsertResult(upserted_count=len(vectors) - len(failed), failed_ids=failed)

    async def search(
        self,
        query_vector: list[float],
        index: str = "default",
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        await self._ensure_index(index)
        client = self._get_client()
        full = self._full_index(index)

        knn_query: dict[str, Any] = {
            "knn": {"embedding": {"vector": query_vector, "k": top_k}}
        }
        if filters:
            filter_clauses = [{"term": {f"metadata.{k}": v}} for k, v in filters.items()]
            query: dict[str, Any] = {
                "bool": {"must": [knn_query], "filter": filter_clauses}
            }
        else:
            query = knn_query

        resp = client.search(index=full, body={"size": top_k, "query": query})
        return [
            SearchResult(
                id=hit["_id"],
                score=float(hit["_score"]),
                metadata=hit["_source"].get("metadata", {}),
            )
            for hit in resp["hits"]["hits"]
        ]

    async def delete(self, ids: list[str], index: str = "default") -> None:
        await self._ensure_index(index)
        client = self._get_client()
        full = self._full_index(index)
        actions = [{"delete": {"_index": full, "_id": id_}} for id_ in ids]
        client.bulk(body=actions)

    async def list_indices(self) -> list[str]:
        client = self._get_client()
        resp = client.cat.indices(index=f"{self._prefix}*", h="index", format="json")
        return [r["index"].removeprefix(self._prefix) for r in resp]

    async def count(self, index: str = "default") -> int:
        await self._ensure_index(index)
        client = self._get_client()
        resp = client.count(index=self._full_index(index))
        return int(resp["count"])
