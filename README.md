# embed-anything

A production-grade, multi-modal embedding pipeline and vector search service.  
Built to demonstrate senior ML engineering: clean abstractions, distributed compute, infrastructure as code, and provider/store portability.

This project was started as an experiment of how fast I could replicate the work I did at my previous company. When I started work there, it was my first time professionally using cloud services, and GPT style AI was just taking off.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          AWS Account                                │
│                                                                     │
│  S3 (catalog + images)                                              │
│       │                                                             │
│       ▼                                                             │
│  Athena Query ──► Parquet results                                   │
│       │                                                             │
│       ▼                                                             │
│  ┌──────────────────────────────────────┐                           │
│  │   ECS Fargate Task (on-demand)       │                           │
│  │   2 vCPU / 8 GB — $0 when idle      │                           │
│  │                                      │                           │
│  │   Ray local mode (single container)  │                           │
│  │     └─ EmbedBatch actors             │                           │
│  │          ├─ fetch image from S3      │                           │
│  │          └─ embed (CLIP / Bedrock /  │                           │
│  │               SentenceTransformers / │                           │
│  │               OpenAI)               │                           │
│  └──────────────┬───────────────────────┘                           │
│                 │ upsert vectors                                     │
│                 ▼                                                    │
│  ┌──────────────────────────┐                                        │
│  │  Vector Store (pluggable)│                                        │
│  │  · Pinecone serverless      ← default                             │
│  │  · pgvector (RDS t4g.micro)                                        │
│  │  · OpenSearch k-NN                                                │
│  └──────────────┬───────────┘                                        │
│                 │                                                    │
│                 ▼                                                    │
│  ┌──────────────────────────┐                                        │
│  │  embed-api (ECS Fargate) │                                        │
│  │  FastAPI, direct public  │                                        │
│  │  IP, port 8080           │                                        │
│  │  POST /search/text       │                                        │
│  │  POST /search/image      │                                        │
│  │  GET  /admin/indices     │                                        │
│  └──────────────────────────┘                                        │
│                                                                     │
│  ECR             — container images for pipeline + api              │
│  Secrets Manager — Pinecone API key injected at container startup   │
│  CloudWatch Logs — pipeline + API task logs                         │
│  GitHub Actions  — builds + pushes images to ECR on merge to main  │
└─────────────────────────────────────────────────────────────────────┘

Orchestration: Prefect Managed (free tier)
  Prefect Cloud triggers the ECS Fargate task via boto3 and polls for
  completion — no persistent infrastructure required outside of run time.
```

---

## Packages

| Package | Role |
|---------|------|
| [`packages/embed-core`](packages/embed-core) | Shared library — abstract `EmbeddingProvider` + `VectorStore` ABCs, 4 provider impls, 3 store impls, factory pattern |
| [`packages/embed-pipeline`](packages/embed-pipeline) | Ray-based ingestion pipeline — Athena/Parquet → fetch S3 images → embed → upsert |
| [`packages/embed-api`](packages/embed-api) | FastAPI search service — text and image search, liveness/readiness probes |
| [`infra/terraform`](infra/terraform) | OpenTofu modules: VPC, ECR, RDS pgvector, ECS Fargate pipeline + API, GitHub Actions OIDC, Prefect OIDC |
| [`scripts`](scripts) | Dev utilities — seed S3 with sample data for local pipeline runs |

---

## Key design decisions

### Provider abstraction

```python
class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def dimension(self) -> int: ...

    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_images(self, images: list[Image]) -> list[list[float]]: ...
```

Swap models by changing one environment variable — `PROVIDER_TYPE=clip|sentence_transformers|bedrock|openai`.  
No application code changes required.

### Store abstraction

```python
class VectorStore(ABC):
    async def upsert(self, vectors, index) -> UpsertResult: ...
    async def search(self, query_vector, index, top_k, filters) -> list[SearchResult]: ...
    async def delete(self, ids, index) -> None: ...
```

Swap backends by changing `STORE_TYPE=pgvector|pinecone|opensearch`.

### Ray for parallel processing (local mode inside ECS)

- **Stateful actors** keep models loaded in CPU memory across batches (no per-batch reload).
- **ray.data** pipelines handle S3 prefetch and back-pressure automatically.
- Ray runs in **local mode** (`RAY_ADDRESS=local`) inside a single 2 vCPU / 8 GB Fargate container — no persistent cluster, zero cost when idle.
- The ECS task is launched on-demand by Prefect and terminates when the job completes.

### Input: Athena query or Parquet

The pipeline doesn't scan S3 by prefix. Instead it executes a SQL query against your item catalog in Athena (backed by S3 + Glue), where each row carries the S3 URI of its associated image. A pre-materialised Parquet file can also be provided directly via `ATHENA_RESULTS_S3_URI` — useful for local runs and one-off ingestion jobs.

### Secrets Manager injection

The DB connection string is stored in Secrets Manager and injected into containers at startup via the ECS `secrets` block. Password rotation or endpoint changes require no Terraform apply and no new task definition — just update the secret and restart the containers.

### CI/CD — GitHub Actions + OIDC

Images are built and pushed to ECR on every merge to main. The workflow authenticates to AWS via OIDC (no stored credentials) using an IAM role managed by Terraform.

---

## Getting started

See [QUICKSTART.md](QUICKSTART.md) for the one-time manual setup steps and how to run your first pipeline job.

---

## Provider reference

| `PROVIDER_TYPE` | Modalities | Key env vars |
|----------------|-----------|-------------|
| `clip` | text + image | `PROVIDER_MODEL_NAME`, `PROVIDER_PRETRAINED`, `PROVIDER_DEVICE` |
| `sentence_transformers` | text only | `PROVIDER_MODEL_NAME`, `PROVIDER_DEVICE` |
| `bedrock` | text + image | `PROVIDER_BEDROCK_MODEL_ID`, `PROVIDER_AWS_REGION` |
| `openai` | text only | `PROVIDER_OPENAI_API_KEY`, `PROVIDER_OPENAI_MODEL` |

## Store reference

| `STORE_TYPE` | Notes | Key env vars |
|-------------|-------|-------------|
| `pinecone` | Serverless, free tier — **default** | `STORE_PINECONE_API_KEY`, `STORE_PINECONE_HOST` |
| `pgvector` | Free-tier eligible (RDS t4g.micro) | `STORE_PGVECTOR_DSN` |
| `opensearch` | t3.small.search free for 750 hrs | `STORE_OPENSEARCH_HOST`, `STORE_OPENSEARCH_USERNAME` |
