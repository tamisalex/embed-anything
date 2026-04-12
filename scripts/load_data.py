"""
Seed S3 with a sample image dataset for embed-pipeline ingestion.

Downloads a subset of food101 from HuggingFace, uploads images to S3,
and writes a Parquet manifest the pipeline can read directly via
ATHENA_RESULTS_S3_URI.

Usage:
    pip install datasets pillow boto3 pandas pyarrow tqdm
    python load_data.py --bucket my-bucket --count 500

Pipeline env vars to set after running:
    ATHENA_RESULTS_S3_URI=<printed at end>
    ATHENA_ID_COLUMN=id
    ATHENA_IMAGE_URI_COLUMN=image_s3_uri
    ATHENA_TEXT_COLUMNS=title
"""

import argparse
import io
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
import pandas as pd
from datasets import load_dataset
from tqdm import tqdm


def upload_image(s3, bucket: str, key: str, image) -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=85)
    buf.seek(0)
    s3.put_object(Bucket=bucket, Key=key, Body=buf, ContentType="image/jpeg")
    return f"s3://{bucket}/{key}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True, help="S3 bucket to upload to")
    parser.add_argument("--prefix", default="food101-sample", help="S3 key prefix")
    parser.add_argument("--count", type=int, default=500, help="Number of images to upload")
    parser.add_argument("--workers", type=int, default=16, help="Parallel upload threads")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    # food101 — 101 food categories, real photos, standard HF format, no auth.
    # Category label formatted as human-readable title ("apple_pie" → "Apple Pie").
    print(f"Loading food101 (first {args.count} rows)...")
    ds = load_dataset("food101", split=f"train[:{args.count}]")
    label_names = ds.features["label"].names

    s3 = boto3.client("s3", region_name=args.region)

    rows = []
    futures = {}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, item in enumerate(ds):
            item_id = f"food-{i:05d}"
            key = f"{args.prefix}/images/{item_id}.jpg"
            title = label_names[item["label"]].replace("_", " ").title()
            future = pool.submit(upload_image, s3, args.bucket, key, item["image"])
            futures[future] = (item_id, title)

        print(f"Uploading {len(futures)} images to s3://{args.bucket}/{args.prefix}/images/ ...")
        for future in tqdm(as_completed(futures), total=len(futures)):
            item_id, title = futures[future]
            s3_uri = future.result()
            rows.append({"id": item_id, "image_s3_uri": s3_uri, "title": title})

    df = pd.DataFrame(rows).sort_values("id").reset_index(drop=True)

    manifest_key = f"{args.prefix}/manifest.parquet"
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    buf.seek(0)
    s3.put_object(Bucket=args.bucket, Key=manifest_key, Body=buf)
    manifest_uri = f"s3://{args.bucket}/{manifest_key}"

    print(f"\nDone. {len(df)} rows written.")
    print(f"\nSet these env vars to run the pipeline:")
    print(f"  ATHENA_RESULTS_S3_URI={manifest_uri}")
    print(f"  ATHENA_ID_COLUMN=id")
    print(f"  ATHENA_IMAGE_URI_COLUMN=image_s3_uri")
    print(f"  ATHENA_TEXT_COLUMNS=title")


if __name__ == "__main__":
    main()
