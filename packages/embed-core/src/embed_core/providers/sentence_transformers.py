"""
Sentence-Transformers embedding provider (text only).

A wide range of pre-trained models is available at
https://www.sbert.net/docs/pretrained_models.html.

Install extras:
    pip install "embed-core[sentence-transformers]"
"""

from __future__ import annotations

import asyncio
from functools import cached_property
from typing import Any

from embed_core.providers.base import EmbeddingProvider


class SentenceTransformerProvider(EmbeddingProvider):
    """Sentence-Transformers-backed text embedding provider.

    Args:
        model_name_or_path: Any model identifier accepted by
            ``sentence_transformers.SentenceTransformer``, e.g.
            ``"all-MiniLM-L6-v2"`` or a local path.
        device: Torch device string.  Defaults to ``"cpu"``.
        batch_size: Sentences processed per forward pass.
        normalize_embeddings: L2-normalise output vectors (recommended for
            cosine similarity).
    """

    def __init__(
        self,
        model_name_or_path: str = "all-MiniLM-L6-v2",
        device: str = "cpu",
        batch_size: int = 128,
        normalize_embeddings: bool = True,
    ) -> None:
        self._model_name = model_name_or_path
        self._device = device
        self._batch_size = batch_size
        self._normalize = normalize_embeddings
        self.__model: Any = None

    def _load(self) -> None:
        if self.__model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "Install the 'sentence-transformers' extras: "
                "pip install 'embed-core[sentence-transformers]'"
            ) from exc

        self.__model = SentenceTransformer(self._model_name, device=self._device)

    @cached_property
    def dimension(self) -> int:
        self._load()
        return int(self.__model.get_sentence_embedding_dimension())

    @property
    def supports_images(self) -> bool:
        return False

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        self._load()
        vectors = self.__model.encode(
            texts,
            batch_size=self._batch_size,
            normalize_embeddings=self._normalize,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [v.tolist() for v in vectors]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._embed_sync, texts)
