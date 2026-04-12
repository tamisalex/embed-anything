"""
Athena Iceberg tracking tables.

Two tables live in a Glue database backed by S3 Iceberg:

    datasources       — one row per unique input manifest
    pipeline_item_log — one row per item per pipeline run

These replace the pgvector tracking tables so the pipeline has no
dependency on RDS at all.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def _sql_escape(val: str) -> str:
    """Minimal escaping for string literals in Athena SQL."""
    return val.replace("'", "''")


class AthenaTracker:
    """Writes pipeline tracking data to Athena Iceberg tables on S3.

    Args:
        glue_database:  Glue Data Catalog database name.
        s3_location:    S3 prefix for Iceberg data files,
                        e.g. ``"s3://my-bucket/iceberg"``.
        results_bucket: S3 bucket for Athena query result output.
        aws_region:     AWS region.
        workgroup:      Athena workgroup (default ``"primary"``).
    """

    def __init__(
        self,
        glue_database: str,
        s3_location: str,
        results_bucket: str,
        aws_region: str = "us-east-1",
        workgroup: str = "primary",
    ) -> None:
        self._db = glue_database
        self._s3 = s3_location.rstrip("/")
        self._results_bucket = results_bucket
        self._region = aws_region
        self._workgroup = workgroup
        self._client: Any = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _athena(self) -> Any:
        if self._client is None:
            import boto3
            self._client = boto3.client("athena", region_name=self._region)
        return self._client

    def _run(self, sql: str) -> None:
        """Submit an Athena query and block until it reaches a terminal state."""
        client = self._athena()
        resp = client.start_query_execution(
            QueryString=sql,
            QueryExecutionContext={"Database": self._db},
            WorkGroup=self._workgroup,
            ResultConfiguration={
                "OutputLocation": f"s3://{self._results_bucket}/athena-tracking-results/"
            },
        )
        qid = resp["QueryExecutionId"]
        while True:
            detail = client.get_query_execution(QueryExecutionId=qid)["QueryExecution"]
            state = detail["Status"]["State"]
            if state == "SUCCEEDED":
                return
            if state in ("FAILED", "CANCELLED"):
                reason = detail["Status"].get("StateChangeReason", "")
                raise RuntimeError(
                    f"Athena query {state}: {reason}\nSQL (truncated): {sql[:300]}"
                )
            time.sleep(1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ensure_tables(self) -> None:
        """Idempotently create the Glue database and both Iceberg tables."""
        import boto3

        # Create Glue database via the Glue API — more reliable than DDL
        glue = boto3.client("glue", region_name=self._region)
        try:
            glue.create_database(
                DatabaseInput={"Name": self._db, "Description": "embed-pipeline tracking"}
            )
            logger.info("Created Glue database '%s'", self._db)
        except glue.exceptions.AlreadyExistsException:
            pass

        self._run(f"""
            CREATE TABLE IF NOT EXISTS {self._db}.datasources (
                name       VARCHAR,
                s3_uri     VARCHAR,
                created_at TIMESTAMP
            )
            LOCATION '{self._s3}/datasources/'
            TBLPROPERTIES ('table_type'='ICEBERG', 'format'='parquet')
        """)

        self._run(f"""
            CREATE TABLE IF NOT EXISTS {self._db}.pipeline_item_log (
                item_id      VARCHAR,
                run_id       VARCHAR,
                datasource   VARCHAR,
                status       VARCHAR,
                processed_at TIMESTAMP,
                error        VARCHAR
            )
            LOCATION '{self._s3}/pipeline_item_log/'
            TBLPROPERTIES ('table_type'='ICEBERG', 'format'='parquet')
        """)
        logger.info("Iceberg tracking tables ready")

    def register_datasource(self, name: str, s3_uri: str) -> None:
        """Upsert a datasource row (insert or update s3_uri if name exists)."""
        self._run(f"""
            MERGE INTO {self._db}.datasources AS t
            USING (VALUES ('{_sql_escape(name)}', '{_sql_escape(s3_uri)}'))
                AS s(name, s3_uri)
            ON t.name = s.name
            WHEN MATCHED THEN
                UPDATE SET s3_uri = s.s3_uri
            WHEN NOT MATCHED THEN
                INSERT VALUES (s.name, s.s3_uri, CURRENT_TIMESTAMP)
        """)
        logger.info("Datasource registered: %s", name)

    def log_items(
        self,
        items: list[dict[str, Any]],
        run_id: str,
        datasource: str,
    ) -> None:
        """INSERT one row per item into pipeline_item_log.

        Each dict must have keys: ``item_id``, ``status``
        (``'success'`` | ``'failed'`` | ``'skipped'``), and optionally ``error``.

        Uses INSERT rather than MERGE — re-running the same run_id will
        produce duplicate rows, which is acceptable for an audit log.
        """
        if not items:
            return

        import datetime

        now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        run_id_esc = _sql_escape(run_id)
        ds_esc = _sql_escape(datasource)

        def _error_col(err: str | None) -> str:
            return "NULL" if err is None else f"'{_sql_escape(err)}'"

        value_rows = ",\n    ".join(
            f"('{_sql_escape(item['item_id'])}', '{run_id_esc}', '{ds_esc}', "
            f"'{item['status']}', TIMESTAMP '{now}', {_error_col(item.get('error'))})"
            for item in items
        )
        self._run(f"""
            INSERT INTO {self._db}.pipeline_item_log
            VALUES
            {value_rows}
        """)
        logger.debug("Logged %d items for run %s", len(items), run_id)
