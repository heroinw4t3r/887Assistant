"""S3-compatible storage backend (AWS S3, Cloudflare R2, MinIO, …).

``boto3`` is synchronous, so every blocking client call is dispatched to a
worker thread via :func:`asyncio.to_thread` to keep the event loop responsive.

The combination of a custom ``endpoint_url`` plus ``region_name="auto"`` is
exactly how Cloudflare R2 is addressed through the S3 API.

Some S3-compatible gateways (notably Storj's ``gateway.storjshare.io``) work more
reliably with PATH-STYLE addressing rather than virtual-hosted-style. Pass
``force_path_style=True`` to enable it via a botocore ``Config``.
"""
from __future__ import annotations

import asyncio

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.storage.base import StorageError


class S3StorageBackend:
    """Store blobs in an S3-compatible bucket."""

    name = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        region: str = "auto",
        public_base_url: str | None = None,
        force_path_style: bool = False,
    ) -> None:
        self._bucket = bucket
        self._public_base_url = public_base_url or None
        config = Config(s3={"addressing_style": "path"}) if force_path_style else None
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            aws_access_key_id=access_key_id or None,
            aws_secret_access_key=secret_access_key or None,
            region_name=region or None,
            config=config,
        )

    async def save(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        kwargs: dict[str, object] = {
            "Bucket": self._bucket,
            "Key": key,
            "Body": data,
        }
        if content_type:
            kwargs["ContentType"] = content_type
        try:
            await asyncio.to_thread(lambda: self._client.put_object(**kwargs))
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"failed to upload {key!r}: {exc}") from exc

    async def load(self, key: str) -> bytes:
        def _get() -> bytes:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read()

        try:
            return await asyncio.to_thread(_get)
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"failed to download {key!r}: {exc}") from exc

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(
                lambda: self._client.delete_object(Bucket=self._bucket, Key=key)
            )
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"failed to delete {key!r}: {exc}") from exc

    def public_url(self, key: str) -> str | None:
        if not self._public_base_url:
            return None
        return f"{self._public_base_url.rstrip('/')}/{key}"
