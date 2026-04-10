"""
AWS Bedrock embedding provider.

Supports Amazon Titan Text and Titan Multimodal Embeddings G1 via the
Bedrock InvokeModel API.  Authentication is handled by the standard boto3
credential chain (IAM role, env vars, ~/.aws/credentials).

Install extras:
    pip install "embed-core[bedrock]"
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
from typing import TYPE_CHECKING, Any

from embed_core.providers.base import EmbeddingProvider

if TYPE_CHECKING:
    from PIL.Image import Image


# Bedrock model IDs
TITAN_TEXT_V2 = "amazon.titan-embed-text-v2:0"
TITAN_MULTIMODAL_G1 = "amazon.titan-embed-image-v1"


class BedrockEmbeddingProvider(EmbeddingProvider):
    """AWS Bedrock Titan embedding provider.

    Args:
        model_id: Bedrock model ID.  Use ``TITAN_TEXT_V2`` for text-only or
            ``TITAN_MULTIMODAL_G1`` for text + image.
        region_name: AWS region where Bedrock is enabled.
        dimensions: Output dimension override (only for Titan Text v2 which
            supports 256, 512, or 1024).
    """

    _DIMENSION_MAP: dict[str, int] = {
        TITAN_TEXT_V2: 1024,
        TITAN_MULTIMODAL_G1: 1024,
    }

    def __init__(
        self,
        model_id: str = TITAN_MULTIMODAL_G1,
        region_name: str = "us-east-1",
        dimensions: int | None = None,
    ) -> None:
        self._model_id = model_id
        self._region_name = region_name
        self._dimensions = dimensions
        self.__client: Any = None

    def _get_client(self) -> Any:
        if self.__client is None:
            try:
                import boto3
            except ImportError as exc:
                raise ImportError(
                    "Install the 'bedrock' extras: pip install 'embed-core[bedrock]'"
                ) from exc
            self.__client = boto3.client("bedrock-runtime", region_name=self._region_name)
        return self.__client

    @property
    def dimension(self) -> int:
        if self._dimensions is not None:
            return self._dimensions
        return self._DIMENSION_MAP.get(self._model_id, 1024)

    @property
    def supports_images(self) -> bool:
        return self._model_id == TITAN_MULTIMODAL_G1

    # ------------------------------------------------------------------
    # Sync helpers (run in executor to avoid blocking the event loop)
    # ------------------------------------------------------------------

    def _invoke(self, body: dict[str, Any]) -> list[float]:
        client = self._get_client()
        payload = json.dumps(body)
        response = client.invoke_model(
            modelId=self._model_id,
            contentType="application/json",
            accept="application/json",
            body=payload,
        )
        result = json.loads(response["body"].read())
        return result["embedding"]

    def _embed_texts_sync(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            body: dict[str, Any] = {"inputText": text}
            if self._dimensions and self._model_id == TITAN_TEXT_V2:
                body["dimensions"] = self._dimensions
                body["normalize"] = True
            vectors.append(self._invoke(body))
        return vectors

    def _embed_images_sync(self, images: list["Image"]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for img in images:
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            body = {"inputImage": b64}
            vectors.append(self._invoke(body))
        return vectors

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._embed_texts_sync, texts)

    async def embed_images(self, images: list["Image"]) -> list[list[float]]:
        if not self.supports_images:
            raise NotImplementedError(
                f"Model {self._model_id} does not support image embeddings. "
                f"Use {TITAN_MULTIMODAL_G1} instead."
            )
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._embed_images_sync, images)
