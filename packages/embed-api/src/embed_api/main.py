"""
embed-api — FastAPI application entry point.

Provider and store are loaded once at startup via lifespan context manager
and attached to ``app.state``.  Route handlers access them through typed
dependency injection (see ``dependencies.py``).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from embed_api.config import ApiSettings, ProviderConfig, StoreConfig
from embed_api.routers import admin, health, search
from embed_core.providers.factory import provider_from_config
from embed_core.stores.factory import store_from_config


def _configure_logging(level: str) -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialise provider + store on startup; clean up on shutdown."""
    log = structlog.get_logger(__name__)

    provider_cfg = ProviderConfig()
    store_cfg = StoreConfig()

    log.info("Loading embedding provider", type=provider_cfg.type)
    provider = provider_from_config(provider_cfg.to_provider_config_dict())
    # Warm up: triggers lazy model load so first request isn't slow
    await provider.embed_single_text("warmup")
    app.state.provider = provider
    log.info("Provider ready", provider=repr(provider))

    log.info("Connecting to vector store", type=store_cfg.type)
    store = store_from_config(store_cfg.to_store_config_dict())
    await store.initialize()
    app.state.store = store
    log.info("Store ready", store=repr(store))

    yield

    log.info("Shutting down")
    await store.close()


def create_app() -> FastAPI:
    settings = ApiSettings()
    _configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.title,
        version=settings.version,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(search.router)
    app.include_router(admin.router)

    return app


app = create_app()
