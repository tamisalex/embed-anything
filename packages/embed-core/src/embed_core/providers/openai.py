"""
OpenAI embedding provider (text only).

Uses the Embeddings API — typically ``text-embedding-3-small`` or
``text-embedding-3-large``.

Install extras:
    pip install "embed-core[openai]"
"""

from __future__ import annotations

import asyncio
from typing import Any

from embed_core.providers.base import EmbeddingProvider

# Well-known output dimensions
_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI Embeddings API provider.

    Args:
        model: OpenAI model name.
        api_key: API key.  Defaults to ``OPENAI_API_KEY`` env var.
        dimensions: Truncate output to this many dimensions (supported by v3
            models only).  ``None`` keeps the model's default.
        batch_size: Texts sent per API call (max 2048 for most models).
    """

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        dimensions: int | None = None,
        batch_size: int = 512,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._dimensions = dimensions
        self._batch_size = batch_size
        self.__client: Any = None

    def _get_client(self) -> Any:
        if self.__client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise ImportError(
                    "Install the 'openai' extras: pip install 'embed-core[openai]'"
                ) from exc
            kwargs: dict[str, Any] = {}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            self.__client = AsyncOpenAI(**kwargs)
        return self.__client

    @property
    def dimension(self) -> int:
        if self._dimensions is not None:
            return self._dimensions
        return _DIMENSIONS.get(self._model, 1536)

    @property
    def supports_images(self) -> bool:
        return False

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        client = self._get_client()
        all_vectors: list[list[float]] = []

        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            kwargs: dict[str, Any] = {"model": self._model, "input": batch}
            if self._dimensions is not None:
                kwargs["dimensions"] = self._dimensions

            response = await client.embeddings.create(**kwargs)
            # The API guarantees items are returned in the same order as input
            all_vectors.extend([item.embedding for item in response.data])

        return all_vectors
