"""
Health and readiness endpoints — used by ECS / ALB target group checks.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(tags=["observability"])


class HealthResponse(BaseModel):
    status: str
    provider: str
    store: str


@router.get("/healthz", response_model=HealthResponse, include_in_schema=False)
async def healthz() -> HealthResponse:
    """Liveness probe — always returns 200 if the process is alive."""
    return HealthResponse(status="ok", provider="unknown", store="unknown")


@router.get(
    "/readyz",
    response_model=HealthResponse,
    summary="Readiness probe",
    description="Returns 200 once the provider model and store connection are ready.",
)
async def readyz(
    request: Request,
) -> HealthResponse:
    provider = getattr(request.app.state, "provider", None)
    store = getattr(request.app.state, "store", None)
    return HealthResponse(
        status="ready" if (provider and store) else "initialising",
        provider=type(provider).__name__ if provider else "none",
        store=type(store).__name__ if store else "none",
    )
