"""
Ray-based parallel embedding processor.

Architecture
------------
::

    Athena/Parquet → Ray Dataset
        → filter(modality != skip)
        → map_batches(EmbedBatch, actor_pool)   ← model stays warm per actor
        → iter_batches → upsert to VectorStore

Each ``EmbedBatch`` actor loads the model once and processes many batches,
keeping expensive model initialisation off the critical path.

Multimodal rows (image_b64 + text both present) are handled by embedding
the image — the provider determines which modality to use.  For text-only
providers the image rows are skipped with a warning.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import structlog

from embed_core.models import Modality, Vector
from embed_pipeline.config import AthenaConfig, PipelineConfig, ProviderConfig, RayConfig, StoreConfig
from embed_pipeline.s3_reader import build_dataset

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Stateful embedding actor
# ---------------------------------------------------------------------------


def _make_embed_batch_cls(provider_config: dict[str, Any]) -> type:
    """Return a stateful Ray actor class configured with *provider_config*."""
    try:
        import ray
    except ImportError as exc:
        raise ImportError("pip install 'ray[data,default]'") from exc

    @ray.remote
    class EmbedBatch:
        """Holds an EmbeddingProvider loaded in memory across many batches."""

        def __init__(self) -> None:
            from embed_core.providers.factory import provider_from_config

            self._provider = provider_from_config(provider_config)
            self._loop = asyncio.new_event_loop()

        def __call__(self, batch: dict[str, Any]) -> dict[str, Any]:
            """Embed one batch.  Called by ``ray.data.map_batches``.

            Input columns: id, modality, image_b64, text, metadata
            Output adds:   embedding (list[float] or [] on failure)
            """
            import base64
            import io

            ids: list[str] = batch["id"]
            modalities: list[str] = batch["modality"]
            images_b64: list[str] = batch["image_b64"]
            texts: list[str] = batch["text"]

            embeddings: list[list[float]] = [[]] * len(ids)

            # Separate rows by how we'll embed them
            image_indices = [
                i for i, m in enumerate(modalities)
                if m in ("image", "multimodal") and images_b64[i]
            ]
            text_only_indices = [
                i for i, m in enumerate(modalities)
                if m == "text" or (m == "multimodal" and not images_b64[i])
            ]

            # Image embeddings
            if image_indices:
                if self._provider.supports_images:
                    from PIL import Image

                    images = [
                        Image.open(io.BytesIO(base64.b64decode(images_b64[i])))
                        for i in image_indices
                    ]
                    vecs = self._loop.run_until_complete(self._provider.embed_images(images))
                    for idx, vec in zip(image_indices, vecs):
                        embeddings[idx] = vec
                else:
                    # Fall back to embedding the text caption if available
                    fallback_indices = [i for i in image_indices if texts[i]]
                    fallback_texts = [texts[i] for i in fallback_indices]
                    if fallback_texts:
                        vecs = self._loop.run_until_complete(
                            self._provider.embed_texts(fallback_texts)
                        )
                        for idx, vec in zip(fallback_indices, vecs):
                            embeddings[idx] = vec

            # Text embeddings
            if text_only_indices:
                t_batch = [texts[i] for i in text_only_indices]
                if any(t_batch):
                    vecs = self._loop.run_until_complete(
                        self._provider.embed_texts([t or " " for t in t_batch])
                    )
                    for idx, vec in zip(text_only_indices, vecs):
                        embeddings[idx] = vec

            batch["embedding"] = embeddings
            return batch

    return EmbedBatch


# ---------------------------------------------------------------------------
# Upsert (runs in Ray remote functions, one per iter_batches chunk)
# ---------------------------------------------------------------------------


def _upsert_batch(
    batch: dict[str, Any],
    store_config_dict: dict[str, Any],
    index: str,
) -> dict[str, int]:
    import asyncio

    from embed_core.stores.factory import store_from_config

    vectors = [
        Vector(
            id=id_,
            values=emb,
            metadata=meta,
            modality=Modality(modality if modality != "multimodal" else "image"),
        )
        for id_, emb, meta, modality in zip(
            batch["id"],
            batch["embedding"],
            batch["metadata"],
            batch["modality"],
        )
        if emb  # skip rows that failed to produce an embedding
    ]

    if not vectors:
        return {"upserted": 0, "failed": 0}

    async def _run() -> Any:
        store = store_from_config(store_config_dict)
        await store.initialize()
        try:
            return await store.upsert(vectors, index=index)
        finally:
            await store.close()

    result = asyncio.run(_run())
    return {"upserted": result.upserted_count, "failed": len(result.failed_ids)}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_pipeline(
    pipeline_cfg: PipelineConfig,
    provider_cfg: ProviderConfig,
    store_cfg: StoreConfig,
    athena_cfg: AthenaConfig,
    ray_cfg: RayConfig,
) -> dict[str, int]:
    """Execute the full embed pipeline using Ray.

    1. Connect to (or start) a Ray cluster.
    2. Load catalog rows from Athena/Parquet → Ray Dataset.
    3. Fetch images from S3 and normalise into pipeline records.
    4. Embed using a pool of warm stateful actors.
    5. Upsert to the configured vector store.

    Returns:
        ``{"upserted": int, "failed": int}``
    """
    import ray

    log = structlog.get_logger(__name__).bind(run_id=pipeline_cfg.run_id)

    if not ray.is_initialized():
        ray.init(
            address=ray_cfg.address,
            namespace=ray_cfg.namespace,
            ignore_reinit_error=True,
            logging_level=pipeline_cfg.log_level,
        )
        log.info("Ray initialised", address=ray_cfg.address)

    provider_config_dict = provider_cfg.to_provider_config_dict()
    store_config_dict = store_cfg.to_store_config_dict()

    log.info("Building dataset from Athena/Parquet source")
    ds = build_dataset(cfg=athena_cfg, limit=pipeline_cfg.limit)

    count = ds.count()
    if count == 0:
        log.warning("No embeddable records — exiting")
        return {"upserted": 0, "failed": 0}

    log.info("Records to embed", count=count)

    # Embed with actor pool
    EmbedBatch = _make_embed_batch_cls(provider_config_dict)
    embedded_ds = ds.map_batches(
        EmbedBatch,
        batch_size=ray_cfg.batch_size,
        concurrency=ray_cfg.num_embedding_actors,
    )

    # Upsert in parallel
    @ray.remote
    def upsert_remote(batch: dict[str, Any]) -> dict[str, int]:
        return _upsert_batch(batch, store_config_dict, pipeline_cfg.index)

    futures = [
        upsert_remote.remote(batch)
        for batch in embedded_ds.iter_batches(batch_size=256)
    ]

    totals: dict[str, int] = {"upserted": 0, "failed": 0}
    for result in ray.get(futures):
        totals["upserted"] += result["upserted"]
        totals["failed"] += result["failed"]

    log.info("Pipeline complete", **totals)
    return totals
