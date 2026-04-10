"""
Data source layer: Athena query → Ray Dataset.

Flow
----
1. Execute an Athena SQL query (or read a pre-materialised Parquet).
2. Load results into a pandas DataFrame.
3. For each row, yield a pipeline record containing:
   - ``id``       : value from the configured ID column
   - ``modality`` : "image", "text", or "multimodal"
   - ``image_b64``: base-64 JPEG/PNG bytes fetched from S3 (if image URI present)
   - ``text``     : concatenated text column values (if text columns configured)
   - ``metadata`` : all remaining columns as a dict

The resulting ``ray.data.Dataset`` feeds directly into ``map_batches``
for parallel embedding.
"""

from __future__ import annotations

import base64
import io
import logging
import time
from typing import Any

import boto3
import pandas as pd

from embed_pipeline.config import AthenaConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Athena execution
# ---------------------------------------------------------------------------


def _run_athena_query(cfg: AthenaConfig) -> pd.DataFrame:
    """Execute an Athena query and return results as a DataFrame."""
    athena = boto3.client("athena", region_name=cfg.aws_region)

    response = athena.start_query_execution(
        QueryString=cfg.query,
        QueryExecutionContext={"Database": cfg.database},
        WorkGroup=cfg.workgroup,
        ResultConfiguration={
            "OutputLocation": f"s3://{cfg.results_bucket}/{cfg.results_prefix}"
        },
    )
    execution_id: str = response["QueryExecutionId"]
    logger.info("Athena query submitted: %s", execution_id)

    # Poll until terminal state
    while True:
        status_resp = athena.get_query_execution(QueryExecutionId=execution_id)
        state: str = status_resp["QueryExecution"]["Status"]["State"]
        if state in ("SUCCEEDED",):
            break
        if state in ("FAILED", "CANCELLED"):
            reason = status_resp["QueryExecution"]["Status"].get("StateChangeReason", "")
            raise RuntimeError(f"Athena query {execution_id} {state}: {reason}")
        time.sleep(cfg.poll_interval_seconds)

    # Fetch results via the S3 output (more efficient than paginating the API)
    result_uri: str = (
        status_resp["QueryExecution"]["ResultConfiguration"]["OutputLocation"]
    )
    logger.info("Athena query complete. Reading results from %s", result_uri)
    return _read_parquet_or_csv_from_s3(result_uri, cfg.aws_region)


def _read_parquet_or_csv_from_s3(s3_uri: str, region: str) -> pd.DataFrame:
    """Read a Parquet or CSV file from S3 into a DataFrame."""
    bucket, key = s3_uri.removeprefix("s3://").split("/", 1)
    s3 = boto3.client("s3", region_name=region)
    obj = s3.get_object(Bucket=bucket, Key=key)
    body = obj["Body"].read()

    if key.endswith(".parquet"):
        return pd.read_parquet(io.BytesIO(body))

    # Athena CSV output has a header row
    return pd.read_csv(io.BytesIO(body))


# ---------------------------------------------------------------------------
# Per-row image fetch (runs inside Ray workers)
# ---------------------------------------------------------------------------


def _fetch_image_b64(s3_uri: str) -> str | None:
    """Download an image from S3 and return it as a base-64 string."""
    if not s3_uri or not isinstance(s3_uri, str) or not s3_uri.startswith("s3://"):
        return None
    try:
        bucket, key = s3_uri.removeprefix("s3://").split("/", 1)
        s3 = boto3.client("s3")
        obj = s3.get_object(Bucket=bucket, Key=key)
        return base64.b64encode(obj["Body"].read()).decode()
    except Exception:
        logger.exception("Failed to fetch image from %s", s3_uri)
        return None


# ---------------------------------------------------------------------------
# Row transformation — called inside Ray map()
# ---------------------------------------------------------------------------


def _transform_row(
    row: dict[str, Any],
    id_col: str,
    image_uri_col: str,
    text_cols: list[str],
    metadata_cols: list[str],
) -> dict[str, Any]:
    """Convert a raw DataFrame row into a pipeline record."""
    row_id = str(row.get(id_col, ""))
    image_uri = row.get(image_uri_col, "") or ""
    image_b64 = _fetch_image_b64(image_uri) if image_uri else None

    # Concatenate text columns (skip nulls)
    text_parts = [str(row[c]) for c in text_cols if row.get(c) is not None]
    text = " ".join(text_parts).strip()

    # Determine modality
    has_image = image_b64 is not None
    has_text = bool(text)
    if has_image and has_text:
        modality = "multimodal"
    elif has_image:
        modality = "image"
    elif has_text:
        modality = "text"
    else:
        modality = "skip"

    # Build metadata dict
    if metadata_cols:
        meta = {c: row.get(c) for c in metadata_cols}
    else:
        skip = {id_col, image_uri_col, *text_cols}
        meta = {k: v for k, v in row.items() if k not in skip}

    # Ensure JSON-serialisable
    meta = {
        k: (v if isinstance(v, (str, int, float, bool, type(None))) else str(v))
        for k, v in meta.items()
    }
    meta["image_s3_uri"] = image_uri

    return {
        "id": row_id,
        "modality": modality,
        "image_b64": image_b64 or "",
        "text": text,
        "metadata": meta,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_dataset(cfg: AthenaConfig, limit: int = 0) -> Any:  # ray.data.Dataset
    """Build a Ray Dataset from an Athena query or pre-materialised Parquet.

    Each row in the resulting dataset has the schema::

        {
            "id":        str,
            "modality":  "image" | "text" | "multimodal" | "skip",
            "image_b64": str,   # base-64 JPEG/PNG, empty string if no image
            "text":      str,   # concatenated text fields, empty string if none
            "metadata":  dict,
        }

    Args:
        cfg: :class:`AthenaConfig` instance.
        limit: Maximum number of rows to process (0 = all).

    Returns:
        A ``ray.data.Dataset`` ready for ``.map_batches()``.
    """
    import ray

    if cfg.results_s3_uri:
        logger.info("Reading pre-materialised Parquet: %s", cfg.results_s3_uri)
        df = _read_parquet_or_csv_from_s3(cfg.results_s3_uri, cfg.aws_region)
    else:
        logger.info("Running Athena query in database '%s'", cfg.database)
        df = _run_athena_query(cfg)

    if limit:
        df = df.head(limit)

    logger.info("Loaded %d rows from source", len(df))

    # Convert to list-of-dicts for Ray
    records = df.to_dict(orient="records")

    text_cols = cfg.text_column_list
    metadata_cols = cfg.metadata_column_list

    ds = ray.data.from_items(records)

    def _transform(row: dict[str, Any]) -> dict[str, Any]:
        return _transform_row(
            row,
            id_col=cfg.id_column,
            image_uri_col=cfg.image_uri_column,
            text_cols=text_cols,
            metadata_cols=metadata_cols,
        )

    ds = ds.map(_transform, concurrency=16)

    # Drop rows that have neither image nor text
    ds = ds.filter(lambda row: row["modality"] != "skip")

    logger.info("Dataset ready (after filtering skipped rows)")
    return ds
