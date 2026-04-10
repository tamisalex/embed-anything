"""
Provider factory — instantiate an EmbeddingProvider from a config dict or
environment-variable-friendly string keys.

Usage
-----
    from embed_core.providers.factory import provider_from_config

    provider = provider_from_config({
        "type": "clip",
        "model_name": "ViT-B-32",
        "pretrained": "openai",
    })
"""

from __future__ import annotations

from typing import Any

from embed_core.providers.base import EmbeddingProvider


_REGISTRY: dict[str, str] = {
    "clip": "embed_core.providers.clip.CLIPEmbeddingProvider",
    "sentence_transformers": (
        "embed_core.providers.sentence_transformers.SentenceTransformerProvider"
    ),
    "bedrock": "embed_core.providers.bedrock.BedrockEmbeddingProvider",
    "openai": "embed_core.providers.openai.OpenAIEmbeddingProvider",
}


def provider_from_config(config: dict[str, Any]) -> EmbeddingProvider:
    """Instantiate an :class:`EmbeddingProvider` from a plain config dict.

    The dict must contain a ``"type"`` key whose value is one of:
    ``clip``, ``sentence_transformers``, ``bedrock``, ``openai``.

    All remaining keys are forwarded as keyword arguments to the provider
    constructor.

    Example::

        provider_from_config({"type": "openai", "model": "text-embedding-3-large"})
    """
    config = dict(config)  # shallow copy — don't mutate caller's dict
    provider_type = config.pop("type")

    if provider_type not in _REGISTRY:
        raise ValueError(
            f"Unknown provider type: {provider_type!r}. "
            f"Valid options: {sorted(_REGISTRY)}"
        )

    module_path, cls_name = _REGISTRY[provider_type].rsplit(".", 1)

    import importlib

    module = importlib.import_module(module_path)
    cls = getattr(module, cls_name)
    return cls(**config)  # type: ignore[no-any-return]
