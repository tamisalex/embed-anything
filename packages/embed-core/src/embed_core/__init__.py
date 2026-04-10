"""
embed-core — abstract embedding providers and vector store interfaces.
"""

from embed_core.models import (
    ImageEmbedRequest,
    Modality,
    SearchRequest,
    SearchResult,
    TextEmbedRequest,
    UpsertResult,
    Vector,
)
from embed_core.providers import EmbeddingProvider, provider_from_config
from embed_core.stores import VectorStore, store_from_config

__all__ = [
    # Models
    "Modality",
    "Vector",
    "SearchResult",
    "UpsertResult",
    "TextEmbedRequest",
    "ImageEmbedRequest",
    "SearchRequest",
    # Providers
    "EmbeddingProvider",
    "provider_from_config",
    # Stores
    "VectorStore",
    "store_from_config",
]
