"""Private artifact backends for local disks and ephemeral AWS workers."""

from __future__ import annotations

import tempfile
from pathlib import Path

from rag_runtime.contracts import digest
from rag_runtime.errors import Problem


class S3ArtifactBackend:
    def __init__(self, bucket: str, region: str, client=None):
        if client is None:
            try:
                import boto3
                from botocore.config import Config
            except ImportError as error:  # pragma: no cover - cloud-only path
                raise RuntimeError("boto3 is required when RAG_ARTIFACT_BUCKET is configured") from error
            client = boto3.client(
                "s3", region_name=region, config=Config(s3={"addressing_style": "path"})
            )
        self.bucket, self.client = bucket, client

    def put(self, key: str, content: bytes) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType="application/octet-stream",
            Metadata={"sha256": digest(content)},
        )

    def read(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        content = response["Body"].read()
        expected = response.get("Metadata", {}).get("sha256")
        if expected and expected != digest(content):
            raise Problem("INTERNAL_ERROR", "Stored artifact failed its integrity check.", 500)
        return content

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def materialize(self, key: str) -> Path:
        handle = tempfile.NamedTemporaryFile(prefix="rag-artifact-", delete=False)
        try:
            handle.write(self.read(key))
            handle.close()
            return Path(handle.name)
        except BaseException:
            Path(handle.name).unlink(missing_ok=True)
            raise
