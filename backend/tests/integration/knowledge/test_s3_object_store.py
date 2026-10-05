"""S3ObjectStore against LocalStack (`make up`): the POST policy is enforced by S3, not by our code."""

import uuid

import boto3
import httpx
import pytest
from botocore.config import Config

from smart_tutor.knowledge.adapters.s3_object_store import S3ObjectStore
from smart_tutor.knowledge.ports.object_store import ObjectNotFoundError, PresignedPost

pytestmark = pytest.mark.integration

ENDPOINT = "http://localhost:10402"
BUCKET = "smart-tutor-documents"


@pytest.fixture
def store() -> S3ObjectStore:
    client = boto3.client(
        "s3",
        region_name="us-east-1",
        endpoint_url=ENDPOINT,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        config=Config(s3={"addressing_style": "path"}),
    )
    return S3ObjectStore(client, BUCKET)


def post(p: PresignedPost, data: bytes, content_type: str = "application/pdf", **override: str) -> httpx.Response:
    fields = {**p.fields, "Content-Type": content_type, **override}
    return httpx.post(p.url, data=fields, files={"file": ("x.pdf", data, content_type)})


def presign(store: S3ObjectStore, max_bytes: int = 1024) -> tuple[str, PresignedPost]:
    key = f"uploads/it-{uuid.uuid4()}/{uuid.uuid4()}.pdf"
    return key, store.presign_post(key, content_type="application/pdf", max_bytes=max_bytes, expires_in=600)


def test_a_pdf_within_the_limit_is_stored_then_copied_and_deleted(store: S3ObjectStore) -> None:
    key, p = presign(store)
    assert post(p, b"%PDF ok").status_code in (200, 201, 204)
    assert store.read(key) == b"%PDF ok"
    dest = f"contents/it-{uuid.uuid4()}.pdf"
    store.copy(key, dest)
    store.delete(key)
    assert store.read(dest) == b"%PDF ok"
    with pytest.raises(ObjectNotFoundError):
        store.read(key)
    store.delete(dest)


def test_over_the_size_limit_is_rejected(store: S3ObjectStore) -> None:
    key, p = presign(store, max_bytes=1024)
    assert post(p, b"x" * 1025).status_code in (400, 403)
    with pytest.raises(ObjectNotFoundError):
        store.read(key)


def test_another_content_type_is_rejected(store: S3ObjectStore) -> None:
    _, p = presign(store)
    assert post(p, b"hello", content_type="text/plain").status_code in (400, 403)


def test_another_key_is_rejected(store: S3ObjectStore) -> None:
    _, p = presign(store)
    other = f"uploads/someone-else/{uuid.uuid4()}.pdf"
    assert post(p, b"%PDF", key=other).status_code in (400, 403)
    with pytest.raises(ObjectNotFoundError):
        store.read(other)


def test_put_stores_bytes_with_the_content_type_and_replaces(store: S3ObjectStore) -> None:
    key = f"contents/it-{uuid.uuid4()}.pages.json"
    store.put(key, b'{"pages": []}', "application/json")
    store.put(key, b'{"pages": [1]}', "application/json")
    assert store.read(key) == b'{"pages": [1]}'
    store.delete(key)
