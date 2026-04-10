"""
Search router — text and image similarity search endpoints.
"""

from __future__ import annotations

import base64
import io
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from embed_api.dependencies import ProviderDep, StoreDep
from embed_core.models import SearchResult

router = APIRouter(prefix="/search", tags=["search"])


class TextSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Natural language search query")
    index: str = Field(default="default", description="Index / namespace to search")
    top_k: int = Field(default=10, ge=1, le=1000)
    filters: dict[str, Any] = Field(default_factory=dict, description="Metadata equality filters")


class ImageSearchRequest(BaseModel):
    image_b64: str = Field(..., description="Base-64 encoded JPEG or PNG image")
    index: str = Field(default="default")
    top_k: int = Field(default=10, ge=1, le=1000)
    filters: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    results: list[SearchResult]
    index: str
    query_modality: str


@router.post(
    "/text",
    response_model=SearchResponse,
    summary="Search by text query",
    description=(
        "Embed the query string using the configured provider and return the "
        "most similar vectors from the index."
    ),
)
async def search_by_text(
    body: TextSearchRequest,
    provider: ProviderDep,
    store: StoreDep,
) -> SearchResponse:
    query_vector = await provider.embed_single_text(body.query)
    results = await store.search(
        query_vector=query_vector,
        index=body.index,
        top_k=body.top_k,
        filters=body.filters or None,
    )
    return SearchResponse(results=results, index=body.index, query_modality="text")


@router.post(
    "/image",
    response_model=SearchResponse,
    summary="Search by image",
    description=(
        "Embed the query image and return the most visually similar vectors. "
        "Requires a provider that supports image embeddings (e.g. CLIP or Bedrock Titan)."
    ),
)
async def search_by_image(
    body: ImageSearchRequest,
    provider: ProviderDep,
    store: StoreDep,
) -> SearchResponse:
    if not provider.supports_images:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Provider {type(provider).__name__} does not support image embeddings.",
        )

    try:
        from PIL import Image

        img_bytes = base64.b64decode(body.image_b64)
        image = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not decode image: {exc}",
        ) from exc

    query_vector = await provider.embed_single_image(image)
    results = await store.search(
        query_vector=query_vector,
        index=body.index,
        top_k=body.top_k,
        filters=body.filters or None,
    )
    return SearchResponse(results=results, index=body.index, query_modality="image")
