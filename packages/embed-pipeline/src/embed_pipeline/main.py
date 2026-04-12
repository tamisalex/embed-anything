"""
Pipeline entry point.

Invoked as:
    python -m embed_pipeline.main

All configuration is sourced from environment variables (see config.py).
"""

from __future__ import annotations

import logging
import sys

import structlog

from embed_pipeline.config import (
    AthenaConfig,
    PipelineConfig,
    ProviderConfig,
    RayConfig,
    StoreConfig,
    TrackingConfig,
)
from embed_pipeline.processor import run_pipeline


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


def main() -> None:
    pipeline_cfg = PipelineConfig()
    _configure_logging(pipeline_cfg.log_level)

    log = structlog.get_logger(__name__).bind(run_id=pipeline_cfg.run_id)
    log.info("Starting embed-pipeline")

    provider_cfg = ProviderConfig()
    store_cfg = StoreConfig()
    athena_cfg = AthenaConfig()
    ray_cfg = RayConfig()
    tracking_cfg = TrackingConfig()

    try:
        totals = run_pipeline(
            pipeline_cfg=pipeline_cfg,
            provider_cfg=provider_cfg,
            store_cfg=store_cfg,
            athena_cfg=athena_cfg,
            ray_cfg=ray_cfg,
            tracking_cfg=tracking_cfg,
        )
        log.info("Finished", **totals)
    except Exception:
        log.exception("Pipeline failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
