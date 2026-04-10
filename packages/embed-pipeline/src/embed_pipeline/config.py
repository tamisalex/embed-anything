"""
Pipeline configuration — all values sourced from environment variables.

This keeps the pipeline 12-factor-app compliant: the same Docker image
runs against different data sources, providers, and stores by injecting
different environment variables at task launch time.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROVIDER_", extra="ignore")

    type: Literal["clip", "sentence_transformers", "bedrock", "openai"] = "clip"

    # CLIP / SentenceTransformers
    model_name: str = "ViT-B-32"
    pretrained: str = "openai"
    device: str = "cpu"

    # Bedrock
    bedrock_model_id: str = "amazon.titan-embed-image-v1"
    aws_region: str = "us-east-1"

    # OpenAI
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


class AthenaConfig(BaseSettings):
    """Input data source: Athena query whose results drive the pipeline.

    Each row returned by the query must include at minimum:
      - ``ATHENA_ID_COLUMN``      — a unique item identifier
      - ``ATHENA_IMAGE_URI_COLUMN`` — s3://... URI to the image (may be empty)

    Any additional columns are stored as vector metadata verbatim.

    Alternatively, the pipeline can accept a pre-materialised Parquet file
    in S3 (produced by a previous Athena CTAS or Glue job) via
    ``ATHENA_RESULTS_S3_URI``.
    """

    model_config = SettingsConfigDict(env_prefix="ATHENA_", extra="ignore")

    # --- Athena query mode ---
    database: str = ""
    query: str = ""
    workgroup: str = "primary"
    results_bucket: str = ""   # S3 bucket for Athena query results
    results_prefix: str = "athena-results/"
    poll_interval_seconds: float = 2.0
    aws_region: str = "us-east-1"

    # --- Pre-materialised Parquet mode (skips Athena execution) ---
    # Set this to read a Parquet file directly instead of running a query.
    results_s3_uri: str = ""

    # --- Schema ---
    id_column: str = "id"
    image_uri_column: str = "image_s3_uri"
    # Comma-separated list of text columns to embed alongside the image.
    # If empty, only image embeddings are produced.
    text_columns: str = ""
    # Columns to include in vector metadata (empty = all non-embedding columns)
    metadata_columns: str = ""

    @field_validator("text_columns", "metadata_columns", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v

    @property
    def text_column_list(self) -> list[str]:
        return [c.strip() for c in self.text_columns.split(",") if c.strip()]

    @property
    def metadata_column_list(self) -> list[str]:
        return [c.strip() for c in self.metadata_columns.split(",") if c.strip()]

    @model_validator(mode="after")
    def _require_source(self) -> "AthenaConfig":
        has_query = bool(self.database and self.query and self.results_bucket)
        has_parquet = bool(self.results_s3_uri)
        if not has_query and not has_parquet:
            raise ValueError(
                "Provide either (ATHENA_DATABASE + ATHENA_QUERY + ATHENA_RESULTS_BUCKET) "
                "or ATHENA_RESULTS_S3_URI"
            )
        return self


class RayConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RAY_", extra="ignore")

    # "local" starts an in-process Ray cluster inside the container (default).
    # Set to "auto" to connect to an existing external cluster instead.
    address: str = "local"
    namespace: str = "embed-pipeline"
    num_embedding_actors: int = 4
    batch_size: int = 32
    parallelism: int = -1


class PipelineConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PIPELINE_", extra="ignore")

    index: str = "default"
    limit: int = 0
    run_id: str = "local"
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _validate_run_id(self) -> "PipelineConfig":
        if not self.run_id:
            raise ValueError("PIPELINE_RUN_ID must not be empty")
        return self
