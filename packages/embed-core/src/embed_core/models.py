"""
Shared data models used across providers, stores, and services.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Modality(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    MULTIMODAL = "multimodal"


class Vector(BaseModel):
    """A single embedding record ready for upsert."""

    id: str
    values: list[float]
    metadata: dict[str, Any] = Field(default_factory=dict)
    # original modality that produced this vector
    modality: Modality = Modality.TEXT


class SearchResult(BaseModel):
    """A single result returned from a vector similarity search."""

    id: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpsertResult(BaseModel):
    upserted_count: int
    failed_ids: list[str] = Field(default_factory=list)


class TextEmbedRequest(BaseModel):
    texts: list[str]
    metadata: list[dict[str, Any]] | None = None
    ids: list[str] | None = None
    index: str = "default"


class ImageEmbedRequest(BaseModel):
    """Images encoded as base-64 strings."""

    images_b64: list[str]
    metadata: list[dict[str, Any]] | None = None
    ids: list[str] | None = None
    index: str = "default"


class SearchRequest(BaseModel):
    index: str = "default"
    top_k: int = Field(default=10, ge=1, le=1000)
    filters: dict[str, Any] = Field(default_factory=dict)
    # Exactly one of query_text or query_image_b64 must be set
    query_text: str | None = None
    query_image_b64: str | None = None

    def model_post_init(self, __context: Any) -> None:
        if self.query_text is None and self.query_image_b64 is None:
            raise ValueError("One of query_text or query_image_b64 is required")
        if self.query_text is not None and self.query_image_b64 is not None:
            raise ValueError("Only one of query_text or query_image_b64 may be set")
