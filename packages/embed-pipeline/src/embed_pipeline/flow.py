"""
Prefect flow — embed-pipeline orchestrator.

Runs in Prefect Managed (free tier) infrastructure — lightweight, no ML deps
needed here.  The actual embedding work runs in your ECS Fargate task.

Flow steps:
  1. Validate parameters
  2. Submit an ECS RunTask with the pipeline env vars
  3. Poll until the task completes
  4. Report success / failure back to Prefect Cloud

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

from prefect import flow, task
from prefect.logging import get_run_logger
from prefect_aws import AwsCredentials


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

@task(name="submit-ecs-task", retries=2, retry_delay_seconds=30)
def submit_ecs_task(
    aws_credentials_block: str,
    cluster: str,
    task_definition: str,
    subnet_id: str,
    security_group_id: str,
    container_env: dict[str, str],
) -> str:
    """Submit the embed-pipeline ECS task and return its task ARN."""
    logger = get_run_logger()

    aws_creds = AwsCredentials.load(aws_credentials_block)
    boto_session = aws_creds.get_boto3_session()
    ecs = boto_session.client("ecs", region_name=aws_creds.region_name or "us-east-1")

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
    logger.info("ECS task submitted", task_arn=task_arn)
    return task_arn


@task(name="wait-for-ecs-task")
def wait_for_ecs_task(
    aws_credentials_block: str,
    cluster: str,
    task_arn: str,
    poll_interval_seconds: int = 30,
    timeout_seconds: int = 7200,
) -> str:
    """Poll ECS until the task reaches a terminal state. Returns exit reason."""
    logger = get_run_logger()

    aws_creds = AwsCredentials.load(aws_credentials_block)
    boto_session = aws_creds.get_boto3_session()
    ecs = boto_session.client("ecs", region_name=aws_creds.region_name or "us-east-1")

    elapsed = 0
    while elapsed < timeout_seconds:
        resp = ecs.describe_tasks(cluster=cluster, tasks=[task_arn])
        task_detail = resp["tasks"][0]
        last_status: str = task_detail["lastStatus"]
        logger.info("ECS task status", status=last_status, elapsed_s=elapsed)

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

            logger.info("ECS task completed successfully", exit_code=exit_code)
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
    version="0.1.0",
)
def embed_pipeline_flow(
    # Athena source
    athena_database: str = "",
    athena_query: str = "",
    athena_results_bucket: str = "",
    athena_results_s3_uri: str = "",
    athena_id_column: str = "id",
    athena_image_uri_column: str = "image_s3_uri",
    athena_text_columns: str = "",
    # Pipeline
    pipeline_index: str = "default",
    pipeline_run_id: str = "prefect",
    pipeline_limit: int = 0,
    # ECS infrastructure (defaults mirror Terraform outputs)
    ecs_cluster: str = "ea-dev-pipeline-cluster",
    ecs_task_definition: str = "ea-dev-pipeline",
    ecs_subnet_id: str = "",
    ecs_security_group_id: str = "",
    # Prefect block names
    aws_credentials_block: str = "embed-anything-aws",
    # Timeouts
    poll_interval_seconds: int = 30,
    timeout_seconds: int = 7200,
) -> None:
    """Orchestrate the embed pipeline via ECS.

    All parameters are editable in the Prefect Cloud UI before each run.
    Store AWS credentials once as a Prefect AwsCredentials block named
    'embed-anything-aws' — never pass them as flow parameters.
    """
    logger = get_run_logger()

    if not ecs_subnet_id or not ecs_security_group_id:
        raise ValueError(
            "ecs_subnet_id and ecs_security_group_id are required. "
            "Find them with: tofu output"
        )

    # Build the env vars to inject into the ECS container
    container_env: dict[str, str] = {
        "PIPELINE_INDEX": pipeline_index,
        "PIPELINE_RUN_ID": pipeline_run_id,
        "PIPELINE_LIMIT": str(pipeline_limit),
    }
    if athena_database:
        container_env["ATHENA_DATABASE"] = athena_database
    if athena_query:
        container_env["ATHENA_QUERY"] = athena_query
    if athena_results_bucket:
        container_env["ATHENA_RESULTS_BUCKET"] = athena_results_bucket
    if athena_results_s3_uri:
        container_env["ATHENA_RESULTS_S3_URI"] = athena_results_s3_uri
    if athena_id_column:
        container_env["ATHENA_ID_COLUMN"] = athena_id_column
    if athena_image_uri_column:
        container_env["ATHENA_IMAGE_URI_COLUMN"] = athena_image_uri_column
    if athena_text_columns:
        container_env["ATHENA_TEXT_COLUMNS"] = athena_text_columns

    logger.info(
        "Submitting pipeline",
        cluster=ecs_cluster,
        index=pipeline_index,
        run_id=pipeline_run_id,
    )

    task_arn = submit_ecs_task(
        aws_credentials_block=aws_credentials_block,
        cluster=ecs_cluster,
        task_definition=ecs_task_definition,
        subnet_id=ecs_subnet_id,
        security_group_id=ecs_security_group_id,
        container_env=container_env,
    )

    wait_for_ecs_task(
        aws_credentials_block=aws_credentials_block,
        cluster=ecs_cluster,
        task_arn=task_arn,
        poll_interval_seconds=poll_interval_seconds,
        timeout_seconds=timeout_seconds,
    )


if __name__ == "__main__":
    embed_pipeline_flow()
