"""API service configuration — sourced from environment variables."""

from __future__ import annotations

from typing import Any, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROVIDER_", extra="ignore")

    type: Literal["clip", "sentence_transformers", "bedrock", "openai"] = "clip"
    model_name: str = "ViT-B-32"
    pretrained: str = "openai"
    device: str = "cpu"
    bedrock_model_id: str = "amazon.titan-embed-image-v1"
    aws_region: str = "us-east-1"
    openai_model: str = "text-embedding-3-small"
    openai_api_key: str | None = None
    openai_dimensions: int | None = None

    def to_provider_config_dict(self) -> dict[str, Any]:
        base: dict[str, Any] = {"type": self.type}
        if self.type == "clip":
            base.update(
                model_name=self.model_name,
                pretrained=self.pretrained,
                device=self.device,
            )
        elif self.type == "sentence_transformers":
            base.update(model_name_or_path=self.model_name, device=self.device)
        elif self.type == "bedrock":
            base.update(model_id=self.bedrock_model_id, region_name=self.aws_region)
        elif self.type == "openai":
            base.update(model=self.openai_model)
            if self.openai_api_key:
                base["api_key"] = self.openai_api_key
            if self.openai_dimensions:
                base["dimensions"] = self.openai_dimensions
        return base


class StoreConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STORE_", extra="ignore")

    type: Literal["pgvector", "pinecone", "opensearch"] = "pgvector"
    dimension: int = 512

    pgvector_dsn: str = "postgresql://postgres:postgres@localhost:5432/embeddings"
    pinecone_api_key: str | None = None
    pinecone_index_name: str = "embed-anything"
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-east-1"
    opensearch_host: str = "https://localhost:9200"
    opensearch_username: str | None = None
    opensearch_password: str | None = None

    def to_store_config_dict(self) -> dict[str, Any]:
        base: dict[str, Any] = {"type": self.type, "dimension": self.dimension}
        if self.type == "pgvector":
            base["dsn"] = self.pgvector_dsn
        elif self.type == "pinecone":
            base.update(index_name=self.pinecone_index_name)
            if self.pinecone_api_key:
                base["api_key"] = self.pinecone_api_key
            base.update(cloud=self.pinecone_cloud, region=self.pinecone_region)
        elif self.type == "opensearch":
            base["host"] = self.opensearch_host
            if self.opensearch_username and self.opensearch_password:
                base["http_auth"] = (self.opensearch_username, self.opensearch_password)
        return base


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="API_", extra="ignore")

    title: str = "Embed Anything Search API"
    version: str = "0.1.0"
    log_level: str = "INFO"
    # CORS origins (comma-separated)
    cors_origins: str = "*"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
