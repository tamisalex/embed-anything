"""
Admin router — index management and stats.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from embed_api.dependencies import StoreDep

router = APIRouter(prefix="/admin", tags=["admin"])


class IndexInfo(BaseModel):
    name: str
    count: int | None = None


class IndexListResponse(BaseModel):
    indices: list[IndexInfo]


@router.get(
    "/indices",
    response_model=IndexListResponse,
    summary="List available indices",
)
async def list_indices(store: StoreDep) -> IndexListResponse:
    try:
        names = await store.list_indices()
    except NotImplementedError:
        names = []

    indices: list[IndexInfo] = []
    for name in names:
        try:
            count: int | None = await store.count(name)
        except NotImplementedError:
            count = None
        indices.append(IndexInfo(name=name, count=count))

    return IndexListResponse(indices=indices)


@router.delete(
    "/indices/{index}/vectors",
    summary="Delete vectors by ID",
    status_code=204,
)
async def delete_vectors(
    index: str,
    ids: list[str],
    store: StoreDep,
) -> None:
    await store.delete(ids=ids, index=index)
