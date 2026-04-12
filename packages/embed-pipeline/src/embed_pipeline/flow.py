"""
Prefect flow — embed-pipeline orchestrator.

Runs in Prefect Managed (free tier) infrastructure — lightweight, no ML deps
needed here.  The actual embedding work runs in your ECS Fargate task.

Flow steps:
  1. Load secrets from Prefect Secret blocks (Pinecone API key).
  2. Build the full environment for the ECS container / Ray workers.
  3. Submit an ECS RunTask with those env vars injected.
  4. Poll until the task completes.
  5. Report success / failure back to Prefect Cloud.

Secrets stored as Prefect blocks (never in flow parameters):
  - ``pinecone-api-key``  → PINECONE_API_KEY env var

AWS credentials are loaded from a Prefect AwsCredentials block stored in
Prefect Cloud (never committed to source control).

Usage (local dev):
    prefect cloud login
    python -m embed_pipeline.flow

Usage (deploy):
    prefect deploy --all      # reads prefect.yaml
"""

from __future__ import annotations

import time

import boto3
from prefect import flow, task
from prefect.logging import get_run_logger


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

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


@task(name="wait-for-ecs-task")
def wait_for_ecs_task(
    cluster: str,
    task_arn: str,
    poll_interval_seconds: int = 30,
    timeout_seconds: int = 7200,
    aws_region: str = "us-east-1",
) -> str:
    """Poll ECS until the task reaches a terminal state. Returns stop reason."""
    logger = get_run_logger()

    ecs = boto3.client("ecs", region_name=aws_region)

    elapsed = 0
    while elapsed < timeout_seconds:
        resp = ecs.describe_tasks(cluster=cluster, tasks=[task_arn])
        task_detail = resp["tasks"][0]
        last_status: str = task_detail["lastStatus"]
        logger.info("ECS task status", extra={"status": last_status, "elapsed_s": elapsed})

        if last_status == "STOPPED":
            container = task_detail["containers"][0]
            exit_code = container.get("exitCode")
            stop_reason = task_detail.get("stoppedReason", "")

            if exit_code != 0:
                raise RuntimeError(
                    f"Pipeline task failed — exit code {exit_code}. "
                    f"Reason: {stop_reason}. "
                    f"Check CloudWatch logs for details."
                )

            logger.info("ECS task completed successfully", extra={"exit_code": exit_code})
            return stop_reason or "success"

        time.sleep(poll_interval_seconds)
        elapsed += poll_interval_seconds

    raise TimeoutError(f"ECS task {task_arn} did not complete within {timeout_seconds}s")


# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------

@flow(
    name="embed-pipeline",
    description="Trigger and monitor the embed-pipeline ECS task from Prefect Cloud",
    version="0.2.0",
)
def embed_pipeline_flow(
    # ---------- Input data source ----------
    athena_results_s3_uri: str = "",
    athena_database: str = "",
    athena_query: str = "",
    athena_results_bucket: str = "",
    athena_id_column: str = "id",
    athena_image_uri_column: str = "image_s3_uri",
    athena_text_columns: str = "title",
    # ---------- Vector store (Pinecone) ----------
    pinecone_index_name: str = "embed-anything",
    pinecone_host: str = "embed-anything-49vf4of.svc.aped-4627-b74a.pinecone.io",
    pinecone_cloud: str = "aws",
    pinecone_region: str = "us-east-1",
    store_dimension: int = 512,
    # ---------- Tracking (Athena Iceberg) ----------
    tracking_glue_database: str = "embed_tracking",
    tracking_s3_location: str = "",   # e.g. s3://my-bucket/iceberg
    tracking_results_bucket: str = "",
    # ---------- Pipeline ----------
    pipeline_index: str = "default",
    pipeline_run_id: str = "prefect",
    pipeline_limit: int = 0,
    # ---------- ECS infrastructure ----------
    ecs_cluster: str = "ea-dev-pipeline-cluster",
    ecs_task_definition: str = "ea-dev-pipeline",
    ecs_subnet_id: str = "",
    ecs_security_group_id: str = "sg-0a00f58ab58b353dd",
    aws_region: str = "us-east-1",
    # ---------- Secrets Manager ----------
    pinecone_secret_name: str = "pinecone_api_key",
    # ---------- Timeouts ----------
    poll_interval_seconds: int = 30,
    timeout_seconds: int = 7200,
) -> None:
    """Orchestrate the embed pipeline via ECS.

    Secrets (Pinecone API key) are pulled from Prefect Secret blocks —
    never pass them as flow parameters.
    """
    logger = get_run_logger()

    if not ecs_subnet_id:
        raise ValueError("ecs_subnet_id is required. Find it with: tofu output")

    if not tracking_s3_location or not tracking_results_bucket:
        raise ValueError(
            "tracking_s3_location and tracking_results_bucket are required."
        )

    # Load secrets from AWS Secrets Manager
    secrets = load_secrets(pinecone_secret_name, aws_region=aws_region)

    # Build the full environment the ECS container (and Ray workers) will see.
    # Ray workers inherit the parent process env, so injecting here is sufficient.
    container_env: dict[str, str] = {
        # Vector store
        "STORE_TYPE": "pinecone",
        "STORE_DIMENSION": str(store_dimension),
        "STORE_PINECONE_API_KEY": secrets["PINECONE_API_KEY"],
        "STORE_PINECONE_INDEX_NAME": pinecone_index_name,
        "STORE_PINECONE_HOST": pinecone_host,
        "STORE_PINECONE_CLOUD": pinecone_cloud,
        "STORE_PINECONE_REGION": pinecone_region,
        # Tracking
        "TRACKING_GLUE_DATABASE": tracking_glue_database,
        "TRACKING_S3_LOCATION": tracking_s3_location,
        "TRACKING_RESULTS_BUCKET": tracking_results_bucket,
        # Pipeline
        "PIPELINE_INDEX": pipeline_index,
        "PIPELINE_RUN_ID": pipeline_run_id,
        "PIPELINE_LIMIT": str(pipeline_limit),
        # Athena columns
        "ATHENA_ID_COLUMN": athena_id_column,
        "ATHENA_IMAGE_URI_COLUMN": athena_image_uri_column,
        "ATHENA_TEXT_COLUMNS": athena_text_columns,
    }

    # Input source — exactly one of pre-materialised Parquet or live query
    if athena_results_s3_uri:
        container_env["ATHENA_RESULTS_S3_URI"] = athena_results_s3_uri
    else:
        if not (athena_database and athena_query and athena_results_bucket):
            raise ValueError(
                "Provide either athena_results_s3_uri or all three of "
                "(athena_database, athena_query, athena_results_bucket)."
            )
        container_env["ATHENA_DATABASE"] = athena_database
        container_env["ATHENA_QUERY"] = athena_query
        container_env["ATHENA_RESULTS_BUCKET"] = athena_results_bucket

    logger.info(
        "Submitting pipeline",
        extra={
            "cluster": ecs_cluster,
            "index": pipeline_index,
            "run_id": pipeline_run_id,
            "source": athena_results_s3_uri or f"athena://{athena_database}",
        },
    )

    task_arn = submit_ecs_task(
        cluster=ecs_cluster,
        task_definition=ecs_task_definition,
        subnet_id=ecs_subnet_id,
        security_group_id=ecs_security_group_id,
        container_env=container_env,
        aws_region=aws_region,
    )

    wait_for_ecs_task(
        cluster=ecs_cluster,
        task_arn=task_arn,
        poll_interval_seconds=poll_interval_seconds,
        timeout_seconds=timeout_seconds,
        aws_region=aws_region,
    )


if __name__ == "__main__":
    embed_pipeline_flow()
