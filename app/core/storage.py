"""File storage for uploads (event images).

``STORAGE_BACKEND=local`` (default) writes under ``MEDIA_DIR`` and serves the
files from ``/api/v1/media``. ``STORAGE_BACKEND=s3`` uses any S3-compatible
store: SeaweedFS locally (``docker compose --profile storage up``), or a hosted
bucket in production (SRS 9).
"""

import logging
from functools import cache
from pathlib import Path
from typing import Protocol

from starlette.concurrency import run_in_threadpool

from app.core.config import settings

logger = logging.getLogger(__name__)

MEDIA_ROUTE = "/api/v1/media"


class Storage(Protocol):
    async def save(self, key: str, content: bytes, content_type: str) -> str:
        """Store the file and return its public URL."""

    async def delete(self, key: str) -> None: ...


class LocalStorage:
    def __init__(self, root: Path, base_url: str) -> None:
        self.root = root
        self.base_url = base_url.rstrip("/")

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("Storage key escapes the media folder")
        return path

    async def save(self, key: str, content: bytes, content_type: str) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        await run_in_threadpool(path.write_bytes, content)
        return f"{self.base_url}{MEDIA_ROUTE}/{key}"

    async def delete(self, key: str) -> None:
        await run_in_threadpool(self._path(key).unlink, missing_ok=True)


class S3Storage:
    def __init__(self) -> None:
        import boto3

        self.bucket = settings.S3_BUCKET
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION,
        )
        self.public_base = (
            settings.S3_PUBLIC_BASE_URL
            or f"{(settings.S3_ENDPOINT_URL or '').rstrip('/')}/{self.bucket}"
        ).rstrip("/")

    async def save(self, key: str, content: bytes, content_type: str) -> str:
        await run_in_threadpool(
            self.client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
            CacheControl="public, max-age=31536000, immutable",
        )
        return f"{self.public_base}/{key}"

    async def delete(self, key: str) -> None:
        await run_in_threadpool(self.client.delete_object, Bucket=self.bucket, Key=key)


@cache
def get_storage() -> Storage:
    if settings.STORAGE_BACKEND == "s3":
        return S3Storage()
    return LocalStorage(Path(settings.MEDIA_DIR), settings.PUBLIC_BASE_URL)
