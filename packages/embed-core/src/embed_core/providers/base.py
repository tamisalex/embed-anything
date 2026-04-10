"""
Abstract base class for all embedding providers.

Providers are responsible for converting raw text or images into dense
float vectors.  Consumers should always depend on this ABC, never on a
concrete implementation, so that the underlying model can be swapped
without touching business logic.
"""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image


class EmbeddingProvider(abc.ABC):
    """Stateless embedding backend.

    All methods are synchronous-but-optionally-awaitable: concrete providers
    should implement the async variants; a sync shim is provided for scripts
    and tests.
    """

    # ------------------------------------------------------------------
    # Required overrides
    # ------------------------------------------------------------------

    @property
    @abc.abstractmethod
    def dimension(self) -> int:
        """Dimensionality of the output vectors."""

    @property
    @abc.abstractmethod
    def supports_images(self) -> bool:
        """True if embed_images() is implemented."""

    @abc.abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of text strings.

        Args:
            texts: Non-empty list of UTF-8 strings.

        Returns:
            List of float vectors, same length and order as *texts*.
        """

    # ------------------------------------------------------------------
    # Optional override (text-only providers may raise NotImplementedError)
    # ------------------------------------------------------------------

    async def embed_images(self, images: list["Image"]) -> list[list[float]]:
        """Embed a batch of PIL images.

        Args:
            images: Non-empty list of PIL.Image instances.

        Returns:
            List of float vectors, same length and order as *images*.

        Raises:
            NotImplementedError: If the provider is text-only.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support image embedding")

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    async def embed_single_text(self, text: str) -> list[float]:
        results = await self.embed_texts([text])
        return results[0]

    async def embed_single_image(self, image: "Image") -> list[float]:
        results = await self.embed_images([image])
        return results[0]

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"dim={self.dimension}, "
            f"images={self.supports_images})"
        )
