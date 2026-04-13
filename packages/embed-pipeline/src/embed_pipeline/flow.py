"""
Prefect flow — embed-pipeline orchestrator.

See QUICKSTART.md for one-time setup, including the Prefect Variable required by this flow.
"""

from __future__ import annotations

import json

import boto3
from prefect import flow, task
from prefect.logging import get_run_logger
from prefect.variables import Variable


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

@task(name="load-config")
def load_config() -> dict:
    """Load infra/store config from the Prefect Variable ``embed_pipeline_config``."""
    raw = Variable.get("embed_pipeline_config")
    return json.loads(raw) if isinstance(raw, str) else raw


@task(name="load-secrets")
def load_secrets(secret_name: str, aws_region: str = "us-east-1") -> dict[str, str]:
    """Load the Pinecone API key from AWS Secrets Manager."""
    logger = get_run_logger()
    client = boto3.client("secretsmanager", region_name=aws_region)
    resp = client.get_secret_value(SecretId=secret_name)
    logger.info("Secret '%s' loaded from Secrets Manager", secret_name)
    return {"PINECONE_API_KEY": resp["SecretString"]}


@task(name="submit-ecs-task", retries=2, retry_delay_seconds=30)
def submit_ecs_task(
    cluster: str,
    task_definition: str,
    subnet_id: str,
    security_group_id: str,
    container_env: dict[str, str],
    aws_region: str = "us-east-1",
) -> str:
    """Submit the embed-pipeline ECS task and return its task ARN."""
    logger = get_run_logger()

    ecs = boto3.client("ecs", region_name=aws_region)
    env_overrides = [{"name": k, "value": v} for k, v in container_env.items()]

    response = ecs.run_task(
        cluster=cluster,
        taskDefinition=task_definition,
        launchType="FARGATE",
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": [subnet_id],
                "securityGroups": [security_group_id],
                "assignPublicIp": "ENABLED",
            }
        },
        overrides={
            "containerOverrides": [{
                "name": "embed-pipeline",
                "environment": env_overrides,
            }]
        },
    )

    failures = response.get("failures", [])
    if failures:
        raise RuntimeError(f"ECS RunTask failed: {failures}")

    task_arn: str = response["tasks"][0]["taskArn"]
    logger.info("ECS task submitted", extra={"task_arn": task_arn})
    return task_arn


# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------

@flow(
    name="embed-pipeline",
    description="Trigger and monitor the embed-pipeline ECS task from Prefect Cloud",
    version="0.3.0",
)
def embed_pipeline_flow(
    # Per-run parameters — everything else lives in the Prefect Variable
    athena_results_s3_uri: str = "s3://embed-anything-input-bucket/food101-sample",
    pipeline_index: str = "default",
    pipeline_run_id: str = "prefect",
    pipeline_limit: int = 0,
) -> None:
    logger = get_run_logger()

    cfg = load_config()

    secrets = load_secrets(cfg["pinecone_secret_name"], aws_region=cfg["aws_region"])

    container_env: dict[str, str] = {
        # Vector store
        "STORE_TYPE":                 "pinecone",
        "STORE_DIMENSION":            str(cfg["store_dimension"]),
        "STORE_PINECONE_API_KEY":     secrets["PINECONE_API_KEY"],
        "STORE_PINECONE_INDEX_NAME":  cfg["pinecone_index_name"],
        "STORE_PINECONE_HOST":        cfg["pinecone_host"],
        "STORE_PINECONE_CLOUD":       cfg["pinecone_cloud"],
        "STORE_PINECONE_REGION":      cfg["pinecone_region"],
        # Tracking
        "TRACKING_GLUE_DATABASE":     cfg["tracking_glue_database"],
        "TRACKING_S3_LOCATION":       cfg["tracking_s3_location"],
        "TRACKING_RESULTS_BUCKET":    cfg["tracking_results_bucket"],
        # Pipeline
        "PIPELINE_INDEX":             pipeline_index,
        "PIPELINE_RUN_ID":            pipeline_run_id,
        "PIPELINE_LIMIT":             str(pipeline_limit),
        # Athena input
        "ATHENA_RESULTS_S3_URI":      athena_results_s3_uri,
        "ATHENA_ID_COLUMN":           cfg["athena_id_column"],
        "ATHENA_IMAGE_URI_COLUMN":    cfg["athena_image_uri_column"],
        "ATHENA_TEXT_COLUMNS":        cfg["athena_text_columns"],
    }

    logger.info(
        "Submitting pipeline",
        extra={"index": pipeline_index, "run_id": pipeline_run_id, "source": athena_results_s3_uri},
    )

    task_arn = submit_ecs_task(
        cluster=cfg["ecs_cluster"],
        task_definition=cfg["ecs_task_definition"],
        subnet_id=cfg["ecs_subnet_id"],
        security_group_id=cfg["ecs_security_group_id"],
        container_env=container_env,
        aws_region=cfg["aws_region"],
    )

    logger.info("ECS task submitted — monitor in CloudWatch /ecs/ea-dev-pipeline", extra={"task_arn": task_arn})


if __name__ == "__main__":
    embed_pipeline_flow()
