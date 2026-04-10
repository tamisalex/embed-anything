"""
Store factory — instantiate a VectorStore from a config dict.

Usage
-----
    from embed_core.stores.factory import store_from_config

    store = store_from_config({
        "type": "pgvector",
        "dsn": "postgresql://user:pass@localhost/mydb",
        "dimension": 512,
    })
"""

from __future__ import annotations

from typing import Any

from embed_core.stores.base import VectorStore


_REGISTRY: dict[str, str] = {
    "pgvector": "embed_core.stores.pgvector.PgVectorStore",
    "pinecone": "embed_core.stores.pinecone.PineconeVectorStore",
    "opensearch": "embed_core.stores.opensearch.OpenSearchVectorStore",
}


def store_from_config(config: dict[str, Any]) -> VectorStore:
    """Instantiate a :class:`VectorStore` from a plain config dict.

    The dict must contain a ``"type"`` key whose value is one of:
    ``pgvector``, ``pinecone``, ``opensearch``.

    All remaining keys are forwarded as keyword arguments to the store
    constructor.

    Example::

        store_from_config({
            "type": "pinecone",
            "index_name": "my-index",
            "dimension": 1024,
        })
    """
    config = dict(config)
    store_type = config.pop("type")

    if store_type not in _REGISTRY:
        raise ValueError(
            f"Unknown store type: {store_type!r}. "
            f"Valid options: {sorted(_REGISTRY)}"
        )

    module_path, cls_name = _REGISTRY[store_type].rsplit(".", 1)

    import importlib

    module = importlib.import_module(module_path)
    cls = getattr(module, cls_name)
    return cls(**config)  # type: ignore[no-any-return]
