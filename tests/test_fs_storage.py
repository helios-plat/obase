"""Tests for obase.fs.LocalFileStorage/S3FileStorage — the S3/Local upload-
download abstraction (SPEC §1 obase.fs)."""

from __future__ import annotations

import os

import pytest

from obase.exceptions import FSError
from obase.fs import FileStorage, LocalFileStorage, S3FileStorage

TEST_S3_ENDPOINT = os.environ.get("TEST_S3_ENDPOINT", "http://localhost:9000")
TEST_S3_ACCESS_KEY = os.environ.get("TEST_S3_ACCESS_KEY", "minioadmin")
TEST_S3_SECRET_KEY = os.environ.get("TEST_S3_SECRET_KEY", "minioadmin")


class TestLocalFileStorage:
    async def test_upload_then_download_roundtrip(self, tmp_path):
        storage = LocalFileStorage(base_dir=tmp_path / "store")
        src = tmp_path / "src.txt"
        src.write_text("hello world")

        key = await storage.upload(local_path=src, key="docs/src.txt")
        assert key == "docs/src.txt"

        dest = tmp_path / "dest.txt"
        await storage.download(key="docs/src.txt", local_path=dest)
        assert dest.read_text() == "hello world"

    async def test_upload_missing_local_file_raises(self, tmp_path):
        storage = LocalFileStorage(base_dir=tmp_path / "store")
        with pytest.raises(FSError, match="not found"):
            await storage.upload(local_path=tmp_path / "missing.txt", key="k")

    async def test_download_missing_key_raises(self, tmp_path):
        storage = LocalFileStorage(base_dir=tmp_path / "store")
        with pytest.raises(FSError, match="not found"):
            await storage.download(key="ghost", local_path=tmp_path / "out.txt")

    async def test_delete_existing_key(self, tmp_path):
        storage = LocalFileStorage(base_dir=tmp_path / "store")
        src = tmp_path / "src.txt"
        src.write_text("x")
        await storage.upload(local_path=src, key="a.txt")

        ok = await storage.delete(key="a.txt")
        assert ok is True

        with pytest.raises(FSError):
            await storage.download(key="a.txt", local_path=tmp_path / "out.txt")

    async def test_delete_missing_key_returns_false(self, tmp_path):
        storage = LocalFileStorage(base_dir=tmp_path / "store")
        ok = await storage.delete(key="ghost")
        assert ok is False

    def test_satisfies_file_storage_protocol(self, tmp_path):
        storage = LocalFileStorage(base_dir=tmp_path / "store")
        assert isinstance(storage, FileStorage)


class TestS3FileStorageValidation:
    async def test_upload_missing_local_file_raises(self, tmp_path):
        storage = S3FileStorage(bucket="test-bucket")
        with pytest.raises(FSError, match="not found"):
            await storage.upload(local_path=tmp_path / "missing.txt", key="k")


class TestS3FileStorageIntegration:
    """Real S3-compatible integration test against a throwaway MinIO container."""

    @pytest.fixture(autouse=True)
    def _require_minio(self):
        try:
            import boto3
        except ImportError:
            pytest.skip("boto3 not installed")

        client = boto3.client(
            "s3",
            endpoint_url=TEST_S3_ENDPOINT,
            aws_access_key_id=TEST_S3_ACCESS_KEY,
            aws_secret_access_key=TEST_S3_SECRET_KEY,
        )
        try:
            client.list_buckets()
        except Exception:
            pytest.skip(f"S3-compatible endpoint not available at {TEST_S3_ENDPOINT}")

        bucket = "obase-test-bucket"
        try:
            client.create_bucket(Bucket=bucket)
        except Exception:
            pass  # already exists
        self._bucket = bucket

    def _storage(self) -> S3FileStorage:
        return S3FileStorage(
            bucket=self._bucket,
            endpoint_url=TEST_S3_ENDPOINT,
            access_key=TEST_S3_ACCESS_KEY,
            secret_key=TEST_S3_SECRET_KEY,
        )

    async def test_upload_download_delete_roundtrip(self, tmp_path):
        storage = self._storage()
        src = tmp_path / "src.txt"
        src.write_text("s3 hello")

        key = await storage.upload(local_path=src, key="it/src.txt")
        assert key == "it/src.txt"

        dest = tmp_path / "dest.txt"
        await storage.download(key="it/src.txt", local_path=dest)
        assert dest.read_text() == "s3 hello"

        ok = await storage.delete(key="it/src.txt")
        assert ok is True

    async def test_download_missing_key_raises(self, tmp_path):
        storage = self._storage()
        with pytest.raises(FSError):
            await storage.download(key="ghost-key", local_path=tmp_path / "out.txt")

    def test_satisfies_file_storage_protocol(self):
        assert isinstance(self._storage(), FileStorage)
