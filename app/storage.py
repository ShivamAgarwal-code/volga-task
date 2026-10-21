"""Object-storage abstraction for audio files.

Audio blobs are large and don't belong in the database, so they go to an
S3-compatible store (AWS S3 in production, MinIO locally). The rest of the code
only ever sees an opaque `key`; this module is the only place that knows about
buckets and byte streams, so switching providers never leaks outward.
"""
import io

import boto3
from botocore.config import Config

from app.config import settings

_s3 = boto3.client(
    "s3",
    endpoint_url=settings.s3_endpoint_url,   # None => real AWS
    aws_access_key_id=settings.s3_access_key,
    aws_secret_access_key=settings.s3_secret_key,
    region_name=settings.s3_region,
    config=Config(signature_version="s3v4"),
)


def ensure_bucket() -> None:
    """Create the bucket on first run so a fresh environment just works."""
    existing = {b["Name"] for b in _s3.list_buckets().get("Buckets", [])}
    if settings.s3_bucket not in existing:
        _s3.create_bucket(Bucket=settings.s3_bucket)


def put_audio(key: str, data: bytes, content_type: str | None = None) -> None:
    _s3.put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=data,
        ContentType=content_type or "application/octet-stream",
    )


def get_audio(key: str) -> bytes:
    obj = _s3.get_object(Bucket=settings.s3_bucket, Key=key)
    return obj["Body"].read()


def download_to_file(key: str, dest_path: str) -> None:
    """Stream an object to local disk so ffmpeg/whisper can read it as a file."""
    _s3.download_file(settings.s3_bucket, key, dest_path)


def delete_audio(key: str) -> None:
    _s3.delete_object(Bucket=settings.s3_bucket, Key=key)
