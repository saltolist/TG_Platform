"""Private media asset storage (S3/MinIO)."""

from __future__ import annotations

import hashlib
import asyncio
import logging
import uuid
from typing import Any

from app.core.config import Settings

logger = logging.getLogger(__name__)


class MediaStorage:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = None

    @property
    def enabled(self) -> bool:
        return bool(self._settings.s3_endpoint and self._settings.s3_bucket)

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.enabled:
            return None
        try:
            import boto3
            from botocore.client import Config

            self._client = boto3.client(
                "s3",
                endpoint_url=self._settings.s3_endpoint or None,
                aws_access_key_id=self._settings.s3_access_key or None,
                aws_secret_access_key=self._settings.s3_secret_key or None,
                config=Config(signature_version="s3v4"),
            )
        except Exception as exc:
            logger.warning("S3 client init failed: %s", exc)
            return None
        return self._client

    def object_key(self, *, user_id: uuid.UUID, asset_id: uuid.UUID, ext: str) -> str:
        return f"users/{user_id}/assets/{asset_id}.{ext.lstrip('.')}"

    @staticmethod
    def checksum(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    async def put_bytes(
        self,
        *,
        object_key: str,
        data: bytes,
        mime_type: str,
    ) -> dict[str, Any]:
        client = self._get_client()
        if client is None:
            raise RuntimeError("media_storage_not_configured")

        def _put() -> None:
            try:
                client.head_bucket(Bucket=self._settings.s3_bucket)
            except Exception:
                client.create_bucket(Bucket=self._settings.s3_bucket)
            client.put_object(
                Bucket=self._settings.s3_bucket,
                Key=object_key,
                Body=data,
                ContentType=mime_type,
            )

        await asyncio.to_thread(_put)
        return {
            "object_key": object_key,
            "stored": True,
            "byte_size": len(data),
            "checksum": self.checksum(data),
        }

    def signed_preview_url(self, object_key: str, *, ttl_sec: int = 3600) -> str:
        client = self._get_client()
        if client is None:
            return ""
        try:
            public_endpoint = self._settings.s3_public_endpoint.strip()
            if public_endpoint and public_endpoint != self._settings.s3_endpoint:
                import boto3
                from botocore.client import Config

                client = boto3.client(
                    "s3",
                    endpoint_url=public_endpoint,
                    aws_access_key_id=self._settings.s3_access_key or None,
                    aws_secret_access_key=self._settings.s3_secret_key or None,
                    config=Config(signature_version="s3v4"),
                )
            return client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._settings.s3_bucket, "Key": object_key},
                ExpiresIn=ttl_sec,
            )
        except Exception as exc:
            logger.warning("presign failed for %s: %s", object_key, exc)
            return ""
