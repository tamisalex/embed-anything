"""
FastAPI dependency injection — provider and store singletons.

The provider and store are initialised once at startup and shared across
all requests via ``app.state``.  The ``Annotated`` helpers below let
route handlers declare them as typed dependencies cleanly.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from embed_core.providers.base import EmbeddingProvider
from embed_core.stores.base import VectorStore


def get_provider(request: Request) -> EmbeddingProvider:
    return request.app.state.provider  # type: ignore[no-any-return]


def get_store(request: Request) -> VectorStore:
    return request.app.state.store  # type: ignore[no-any-return]


ProviderDep = Annotated[EmbeddingProvider, Depends(get_provider)]
StoreDep = Annotated[VectorStore, Depends(get_store)]
