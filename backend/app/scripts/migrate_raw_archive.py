"""Streaming migration from legacy .json.gz bodies to raw .json bodies."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import os
import tempfile
from pathlib import Path

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete-source", action="store_true")
    parser.add_argument("--work-dir", default=os.environ.get("ARCHIVE_MIGRATION_WORK_DIR", "/borg/work"))
    args = parser.parse_args()
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["ARCHIVE_S3_ENDPOINT_URL"],
        aws_access_key_id=os.environ["ARCHIVE_S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["ARCHIVE_S3_SECRET_ACCESS_KEY"],
        region_name=os.environ.get("ARCHIVE_S3_REGION", "us-east-1"),
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 5, "mode": "standard"}),
    )
    bucket = os.environ["ARCHIVE_S3_BUCKET"]
    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    keys = [
        str(o["Key"])
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix="raw/")
        for o in page.get("Contents", [])
        if str(o.get("Key", "")).endswith(".json.gz")
    ]
    print(f"{bucket}: found {len(keys)} legacy gzip objects", flush=True)
    copied = 0
    for index, key in enumerate(keys, 1):
        destination = key[:-3]
        try:
            existing = s3.head_object(Bucket=bucket, Key=destination)
            if existing.get("ContentEncoding") != "gzip":
                if args.delete_source:
                    s3.delete_object(Bucket=bucket, Key=key)
                continue
        except s3.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
                raise
        fd, name = tempfile.mkstemp(prefix="archive-", suffix=".part", dir=work)
        os.close(fd)
        count = 0
        digest = hashlib.sha256()
        try:
            body = s3.get_object(Bucket=bucket, Key=key)["Body"]
            with gzip.GzipFile(fileobj=body) as source, open(name, "wb", buffering=1024 * 1024) as target:
                while chunk := source.read(8 * 1024 * 1024):
                    target.write(chunk)
                    digest.update(chunk)
                    count += len(chunk)
            s3.upload_file(
                name,
                bucket,
                destination,
                ExtraArgs={"ContentType": "application/json", "Metadata": {"raw-sha256": digest.hexdigest()}},
                Config=TransferConfig(multipart_threshold=8 * 1024 * 1024, multipart_chunksize=8 * 1024 * 1024, max_concurrency=1, use_threads=False),
            )
            verified = s3.head_object(Bucket=bucket, Key=destination)
            if int(verified.get("ContentLength", -1)) != count or verified.get("Metadata", {}).get("raw-sha256") != digest.hexdigest():
                raise RuntimeError(f"verification failed: {destination}")
            if args.delete_source:
                s3.delete_object(Bucket=bucket, Key=key)
            copied += 1
        finally:
            try:
                os.unlink(name)
            except FileNotFoundError:
                pass
        if index % 100 == 0 or index == len(keys):
            print(f"{bucket}: {index}/{len(keys)} copied={copied}", flush=True)


if __name__ == "__main__":
    main()
