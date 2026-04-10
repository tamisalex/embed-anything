"""
OpenCLIP embedding provider.

Supports joint text + image embeddings in a shared vector space, which
means a text query can retrieve images and vice-versa — ideal for
cross-modal search.

Install extras:
    pip install "embed-core[clip]"
"""

from __future__ import annotations

import asyncio
from functools import cached_property
from typing import TYPE_CHECKING, Any

from embed_core.providers.base import EmbeddingProvider

if TYPE_CHECKING:
    from PIL.Image import Image


class CLIPEmbeddingProvider(EmbeddingProvider):
    """OpenCLIP-backed multimodal embedding provider.

    Args:
        model_name: Any model name accepted by ``open_clip.create_model_and_transforms``,
            e.g. ``"ViT-B-32"``.
        pretrained: Pretrained weights tag, e.g. ``"openai"`` or ``"laion2b_s34b_b79k"``.
        device: Torch device string (``"cpu"``, ``"cuda"``, ``"mps"``).  Defaults to
            ``"cpu"`` so the image works on AWS t2.micro / Fargate without a GPU.
        batch_size: Maximum images/texts processed per forward pass.
    """

    def __init__(
        self,
        model_name: str = "ViT-B-32",
        pretrained: str = "openai",
        device: str = "cpu",
        batch_size: int = 64,
    ) -> None:
        self._model_name = model_name
        self._pretrained = pretrained
        self._device = device
        self._batch_size = batch_size
        self.__model: Any = None
        self.__preprocess: Any = None
        self.__tokenizer: Any = None

    # ------------------------------------------------------------------
    # Lazy model loading — avoids paying the import cost at module load
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if self.__model is not None:
            return
        try:
            import open_clip
            import torch
        except ImportError as exc:
            raise ImportError(
                "Install the 'clip' extras: pip install 'embed-core[clip]'"
            ) from exc

        model, _, preprocess = open_clip.create_model_and_transforms(
            self._model_name, pretrained=self._pretrained, device=self._device
        )
        model.eval()
        self.__model = model
        self.__preprocess = preprocess
        self.__tokenizer = open_clip.get_tokenizer(self._model_name)
        self.__torch = torch

    @cached_property
    def dimension(self) -> int:
        self._load()
        import open_clip

        cfg = open_clip.get_model_config(self._model_name)
        if cfg is None:
            raise ValueError(f"Unknown OpenCLIP model: {self._model_name}")
        return int(cfg["embed_dim"])

    @property
    def supports_images(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # Core embedding methods — offloaded to a thread so the event loop
    # is not blocked by synchronous PyTorch operations
    # ------------------------------------------------------------------

    def _embed_texts_sync(self, texts: list[str]) -> list[list[float]]:
        self._load()
        import torch

        results: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            tokens = self.__tokenizer(batch).to(self._device)
            with torch.no_grad(), torch.autocast(self._device, enabled=self._device != "cpu"):
                features = self.__model.encode_text(tokens)
                features = features / features.norm(dim=-1, keepdim=True)
            results.extend(features.cpu().float().tolist())
        return results

    def _embed_images_sync(self, images: list["Image"]) -> list[list[float]]:
        self._load()
        import torch

        results: list[list[float]] = []
        for i in range(0, len(images), self._batch_size):
            batch = images[i : i + self._batch_size]
            tensors = self.__torch.stack(
                [self.__preprocess(img) for img in batch]
            ).to(self._device)
            with torch.no_grad(), torch.autocast(self._device, enabled=self._device != "cpu"):
                features = self.__model.encode_image(tensors)
                features = features / features.norm(dim=-1, keepdim=True)
            results.extend(features.cpu().float().tolist())
        return results

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._embed_texts_sync, texts)

    async def embed_images(self, images: list["Image"]) -> list[list[float]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._embed_images_sync, images)
