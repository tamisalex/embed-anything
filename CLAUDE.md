# CLAUDE.md

source: https://github.com/forrestchang/andrej-karpathy-skills/blob/main/CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## Project Architecture

### Packages

**`packages/embed-core`** — shared library, no framework dependencies
- `providers/` — `EmbeddingProvider` ABC + implementations: `clip`, `sentence_transformers`, `bedrock`, `openai`
- `stores/` — `VectorStore` ABC + implementations: `pgvector`, `pinecone`, `opensearch`
- `providers/factory.py` / `stores/factory.py` — lazy-import registries keyed by `"type"` string

To add a provider: implement `EmbeddingProvider` in `providers/`, register in `providers/factory.py` `_REGISTRY`.
To add a store: implement `VectorStore` in `stores/`, register in `stores/factory.py` `_REGISTRY`.

**`packages/embed-pipeline`** — Prefect + Ray ingestion pipeline
- `flow.py` — Prefect flow entry point. Reads config from Prefect Variable `embed_pipeline_config`, submits an ECS Fargate task via `boto3`, passes all env overrides as container environment variables.
- `processor.py` — Ray local-mode batch processor. `EmbedBatch` is a Ray stateful actor that keeps the model warm across batches.
- `config.py` — reads all `PIPELINE_*`, `ATHENA_*`, `STORE_*`, `PROVIDER_*` env vars.
- `tracking.py` — writes run metadata to Athena Iceberg tables via Glue catalog.
- `config/pipeline_config.json` — infra values stored as a Prefect Variable (`embed_pipeline_config`).

**`packages/embed-api`** — FastAPI search service
- `main.py` — app factory + lifespan: provider and store loaded once at startup, attached to `app.state`.
- `dependencies.py` — typed FastAPI dependencies that pull provider/store from `app.state`.
- Routes: `POST /search/text`, `POST /search/image`, `GET /admin/indices`, `GET /healthz`, `GET /readyz`.

### Infra (`infra/terraform/`)

Modules: `networking`, `ecr`, `rds-pgvector`, `pipeline-task`, `ecs-api`, `ray-cluster`, `prefect-oidc`, `github-oidc`.
Dev environment: `infra/terraform/environments/dev/`.

`pipeline-task` — ECS Fargate task definition for the embedding pipeline. IAM roles: execution role (Secrets Manager) + task role (S3, Athena, Glue, ECR, CloudWatch). Pinecone API key is optional: pass `pinecone_api_key_secret_arn` to enable.

### Key env vars (pipeline)

| Prefix | Examples |
|--------|---------|
| `PROVIDER_*` | `PROVIDER_TYPE`, `PROVIDER_MODEL_NAME`, `PROVIDER_PRETRAINED` |
| `STORE_*` | `STORE_TYPE`, `STORE_PINECONE_INDEX_NAME`, `STORE_PINECONE_HOST`, `STORE_PGVECTOR_DSN` |
| `ATHENA_*` | `ATHENA_RESULTS_S3_URI`, `ATHENA_ID_COLUMN`, `ATHENA_IMAGE_URI_COLUMN`, `ATHENA_TEXT_COLUMNS` |
| `PIPELINE_*` | `PIPELINE_INDEX`, `PIPELINE_RUN_ID`, `PIPELINE_LIMIT` |
| `TRACKING_*` | `TRACKING_GLUE_DATABASE`, `TRACKING_S3_LOCATION`, `TRACKING_RESULTS_BUCKET` |