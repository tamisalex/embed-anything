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
│  │         Ray Cluster (EC2 Spot)       │                           │
│  │                                      │                           │
│  │  Head node (t3.medium)               │                           │
│  │    └─ Ray GCS + Dashboard (:8265)    │                           │
│  │                                      │                           │
│  │  Worker nodes (t3.small, ASG Spot)   │                           │
│  │    └─ EmbedBatch actors              │                           │
│  │         ├─ fetch image from S3       │                           │
│  │         └─ embed (CLIP / Bedrock /   │                           │
│  │              SentenceTransformers /  │                           │
│  │              OpenAI)                 │                           │
│  └──────────────┬───────────────────────┘                           │
│                 │ upsert vectors                                     │
│                 ▼                                                    │
│  ┌──────────────────────────┐                                        │
│  │  Vector Store (pluggable)│                                        │
│  │  · pgvector (RDS t4g.micro) ← default, free-tier eligible        │
│  │  · Pinecone serverless                                            │
│  │  · OpenSearch k-NN                                                │
│  └──────────────┬───────────┘                                        │
│                 │                                                    │
│                 ▼                                                    │
│  ┌──────────────────────────┐                                        │
│  │  embed-api (ECS Fargate) │                                        │
│  │  FastAPI + ALB           │                                        │
│  │  POST /search/text       │                                        │
│  │  POST /search/image      │                                        │
│  │  GET  /admin/indices     │                                        │
│  └──────────────────────────┘                                        │
│                                                                     │
│  ECR  — container images for pipeline + api                         │
│  Secrets Manager — DB password                                      │
│  CloudWatch Logs — API task logs                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Packages

| Package | Role |
|---------|------|
| [`packages/embed-core`](packages/embed-core) | Shared library — abstract `EmbeddingProvider` + `VectorStore` ABCs, 4 provider impls, 3 store impls, factory pattern |
| [`packages/embed-pipeline`](packages/embed-pipeline) | Ray-based ingestion pipeline — Athena/Parquet → fetch S3 images → embed → upsert |
| [`packages/embed-api`](packages/embed-api) | FastAPI search service — text and image search, liveness/readiness probes |
| [`infra/terraform`](infra/terraform) | Terraform modules: VPC, ECR, RDS pgvector, Ray cluster (EC2 Spot), ECS Fargate API |

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

### Ray for parallel processing

- **Stateful actors** keep models loaded in GPU/CPU memory across batches (no per-batch reload).
- **ray.data** pipelines handle S3 prefetch and back-pressure automatically.
- Spot instance ASG scales workers to 0 when idle.
- Head node exposes Ray Dashboard at `:8265` for observability.

### Input: Athena query or Parquet

The pipeline doesn't scan S3 by prefix.  Instead it executes a SQL query against your item catalog in Athena (backed by S3 + Glue), where each row carries the S3 URI of its associated image.  A pre-materialised Parquet file can also be provided directly via `ATHENA_RESULTS_S3_URI`.

---

## Quickstart

### 1. Bootstrap infrastructure

```bash
cd infra/terraform/environments/dev
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars — set data_bucket, ssh_key_name, etc.

terraform init
terraform plan
terraform apply
```

### 2. Build and push images

```bash
# Authenticate with ECR
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com

# Build from repo root (Dockerfiles use COPY paths relative to root)
docker build -f packages/embed-pipeline/Dockerfile \
  --build-arg PROVIDER=clip -t <ecr-pipeline-url>:latest .

docker build -f packages/embed-api/Dockerfile \
  --build-arg PROVIDER=clip -t <ecr-api-url>:latest .

docker push <ecr-pipeline-url>:latest
docker push <ecr-api-url>:latest
```

### 3. Run a pipeline job

SSH or SSM to the Ray head node, then:

```bash
pip install embed-pipeline

export ATHENA_DATABASE=my_catalog
export ATHENA_QUERY="SELECT id, image_s3_uri, title, description FROM items LIMIT 1000"
export ATHENA_RESULTS_BUCKET=my-athena-results-bucket
export ATHENA_ID_COLUMN=id
export ATHENA_IMAGE_URI_COLUMN=image_s3_uri
export ATHENA_TEXT_COLUMNS=title,description

export PROVIDER_TYPE=clip
export PROVIDER_MODEL_NAME=ViT-B-32

export STORE_TYPE=pgvector
export STORE_DIMENSION=512
export STORE_PGVECTOR_DSN="postgresql://embedadmin:PASSWORD@<rds-endpoint>/embeddings"

export PIPELINE_INDEX=items
export PIPELINE_RUN_ID=run-001
export RAY_ADDRESS=auto

python -m embed_pipeline.main
```

### 4. Search

```bash
# Text search
curl -X POST http://<alb-dns>/search/text \
  -H "Content-Type: application/json" \
  -d '{"query": "blue ceramic vase", "index": "items", "top_k": 5}'

# Image search (base64-encode your query image)
IMAGE_B64=$(base64 -w0 query.jpg)
curl -X POST http://<alb-dns>/search/image \
  -H "Content-Type: application/json" \
  -d "{\"image_b64\": \"$IMAGE_B64\", \"index\": \"items\", \"top_k\": 5}"

# OpenAPI docs
open http://<alb-dns>/docs
```

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
| `pgvector` | Free-tier eligible (RDS t4g.micro) | `STORE_PGVECTOR_DSN` |
| `pinecone` | Serverless, free tier available | `STORE_PINECONE_API_KEY`, `STORE_PINECONE_INDEX_NAME` |
| `opensearch` | t3.small.search free for 750 hrs | `STORE_OPENSEARCH_HOST`, `STORE_OPENSEARCH_USERNAME` |

---

## Local development

```bash
# Install all packages in editable mode
pip install -e "packages/embed-core[all]"
pip install -e "packages/embed-pipeline"
pip install -e "packages/embed-api"

# Run API locally against a Docker pgvector instance
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=postgres ankane/pgvector

STORE_PGVECTOR_DSN=postgresql://postgres:postgres@localhost/postgres \
PROVIDER_TYPE=clip \
uvicorn embed_api.main:app --reload --port 8080

# Open docs
open http://localhost:8080/docs
```
