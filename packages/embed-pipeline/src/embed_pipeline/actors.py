"""
Ray remote actors for parallel embedding.

Each ``EmbeddingActor`` instance holds a single loaded model in GPU/CPU
memory.  Ray distributes batches across a pool of these actors, keeping
models warm across many batches without reloading for every task.
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _build_provider(provider_config: dict[str, Any]) -> Any:
    """Import and instantiate an EmbeddingProvider inside a worker process."""
    from embed_core.providers.factory import provider_from_config

    return provider_from_config(provider_config)


# Ray is imported lazily so that modules can be imported without a Ray
# cluster present (useful for unit tests and local dev).
def make_embedding_actor_cls(num_cpus: float = 1.0, num_gpus: float = 0.0) -> type:
    """Return a Ray remote actor class with the requested resource spec.

    We use a factory function so the resource requirements can be set at
    runtime based on whether a GPU is available.
    """
    try:
        import ray
    except ImportError as exc:
        raise ImportError("pip install 'ray[default]'") from exc

    @ray.remote(num_cpus=num_cpus, num_gpus=num_gpus)
    class EmbeddingActor:
        """Stateful Ray actor that keeps an EmbeddingProvider loaded in memory."""

        def __init__(self, provider_config: dict[str, Any]) -> None:
            import asyncio

            self._provider = _build_provider(provider_config)
            self._loop = asyncio.get_event_loop()
            logger.info("EmbeddingActor initialised: %s", self._provider)

        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return self._loop.run_until_complete(self._provider.embed_texts(texts))

        def embed_images_b64(self, images_b64: list[str]) -> list[list[float]]:
            """Accepts base-64 encoded JPEG/PNG strings."""
            from PIL import Image

            images = [Image.open(io.BytesIO(base64.b64decode(b64))) for b64 in images_b64]
            return self._loop.run_until_complete(self._provider.embed_images(images))

        def supports_images(self) -> bool:
            return self._provider.supports_images

        def dimension(self) -> int:
            return self._provider.dimension

    return EmbeddingActor
