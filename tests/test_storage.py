"""Unit tests for the pluggable storage backends (no network)."""
from __future__ import annotations

import pytest

from app.storage import (
    StorageBackend,
    StorageError,
    get_storage_backend,
    reset_storage_backend,
)
from app.storage.local import LocalStorageBackend
from app.storage.s3 import S3StorageBackend


class _FakeSettings:
    """Minimal stand-in for app.config.Settings used by the factory."""

    def __init__(self, **kwargs):
        self.storage_backend = kwargs.get("storage_backend", "local")
        self.file_storage_path = kwargs.get("file_storage_path", "./storage")
        self.s3_endpoint_url = kwargs.get("s3_endpoint_url", "")
        self.s3_access_key_id = kwargs.get("s3_access_key_id", "")
        self.s3_secret_access_key = kwargs.get("s3_secret_access_key", "")
        self.s3_bucket = kwargs.get("s3_bucket", "")
        self.s3_region = kwargs.get("s3_region", "auto")
        self.s3_public_base_url = kwargs.get("s3_public_base_url", "")


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_storage_backend()
    yield
    reset_storage_backend()


# --------------------------------------------------------------------------- #
# LocalStorageBackend
# --------------------------------------------------------------------------- #
async def test_local_round_trip(tmp_path):
    backend = LocalStorageBackend(str(tmp_path))
    key = "111/abc_report.pdf"
    payload = b"hello world"

    await backend.save(key, payload, content_type="application/pdf")
    assert (tmp_path / "111" / "abc_report.pdf").read_bytes() == payload

    assert await backend.load(key) == payload

    await backend.delete(key)
    assert not (tmp_path / "111" / "abc_report.pdf").exists()
    # Deleting a missing key is a no-op.
    await backend.delete(key)


async def test_local_load_missing_raises(tmp_path):
    backend = LocalStorageBackend(str(tmp_path))
    with pytest.raises(StorageError):
        await backend.load("nope/missing.bin")


def test_local_public_url_is_none(tmp_path):
    assert LocalStorageBackend(str(tmp_path)).public_url("x/y") is None


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
def test_factory_returns_local_when_not_s3(tmp_path):
    settings = _FakeSettings(storage_backend="local", file_storage_path=str(tmp_path))
    backend = get_storage_backend(settings)
    assert isinstance(backend, LocalStorageBackend)
    assert backend.name == "local"
    assert isinstance(backend, StorageBackend)


def test_factory_falls_back_to_local_without_credentials(tmp_path):
    # storage_backend == "s3" but no bucket/keys -> still Local.
    settings = _FakeSettings(storage_backend="s3", file_storage_path=str(tmp_path))
    assert isinstance(get_storage_backend(settings), LocalStorageBackend)


def test_factory_returns_s3_when_configured():
    settings = _FakeSettings(
        storage_backend="s3",
        s3_bucket="my-bucket",
        s3_access_key_id="key",
        s3_secret_access_key="secret",
        s3_endpoint_url="https://acct.r2.cloudflarestorage.com",
    )
    backend = get_storage_backend(settings)
    assert isinstance(backend, S3StorageBackend)
    assert backend.name == "s3"


def test_factory_is_singleton(tmp_path):
    settings = _FakeSettings(file_storage_path=str(tmp_path))
    assert get_storage_backend(settings) is get_storage_backend(settings)


# --------------------------------------------------------------------------- #
# S3StorageBackend (boto3 client monkeypatched -> no network)
# --------------------------------------------------------------------------- #
class _FakeBody:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


class _FakeS3Client:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.put_calls: list[dict] = []
        self.get_calls: list[dict] = []
        self.delete_calls: list[dict] = []

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        self.objects[kwargs["Key"]] = kwargs["Body"]
        return {}

    def get_object(self, **kwargs):
        self.get_calls.append(kwargs)
        return {"Body": _FakeBody(self.objects[kwargs["Key"]])}

    def delete_object(self, **kwargs):
        self.delete_calls.append(kwargs)
        self.objects.pop(kwargs["Key"], None)
        return {}


def _make_s3(monkeypatch) -> tuple[S3StorageBackend, _FakeS3Client]:
    fake = _FakeS3Client()
    monkeypatch.setattr("boto3.client", lambda *a, **k: fake)
    backend = S3StorageBackend(
        bucket="my-bucket",
        endpoint_url="https://acct.r2.cloudflarestorage.com",
        access_key_id="key",
        secret_access_key="secret",
        region="auto",
        public_base_url="https://cdn.example.com/files",
    )
    return backend, fake


async def test_s3_save_load_delete(monkeypatch):
    backend, fake = _make_s3(monkeypatch)
    key = "111/deadbeef_doc.txt"
    payload = b"binary-ish payload"

    await backend.save(key, payload, content_type="text/plain")
    assert fake.put_calls[0]["Bucket"] == "my-bucket"
    assert fake.put_calls[0]["Key"] == key
    assert fake.put_calls[0]["Body"] == payload
    assert fake.put_calls[0]["ContentType"] == "text/plain"

    loaded = await backend.load(key)
    assert loaded == payload
    assert fake.get_calls[0] == {"Bucket": "my-bucket", "Key": key}

    await backend.delete(key)
    assert fake.delete_calls[0] == {"Bucket": "my-bucket", "Key": key}
    assert key not in fake.objects


async def test_s3_save_without_content_type_omits_it(monkeypatch):
    backend, fake = _make_s3(monkeypatch)
    await backend.save("k", b"x")
    assert "ContentType" not in fake.put_calls[0]


def test_s3_public_url(monkeypatch):
    backend, _ = _make_s3(monkeypatch)
    assert backend.public_url("111/file.txt") == "https://cdn.example.com/files/111/file.txt"


def test_s3_public_url_none_without_base(monkeypatch):
    fake = _FakeS3Client()
    monkeypatch.setattr("boto3.client", lambda *a, **k: fake)
    backend = S3StorageBackend(bucket="b", public_base_url="")
    assert backend.public_url("x") is None


async def test_s3_wraps_errors(monkeypatch):
    from botocore.exceptions import ClientError

    backend, fake = _make_s3(monkeypatch)

    def _boom(**kwargs):
        raise ClientError({"Error": {"Code": "500", "Message": "boom"}}, "GetObject")

    fake.get_object = _boom
    with pytest.raises(StorageError):
        await backend.load("missing")
