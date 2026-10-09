import base64
import json
import time
from urllib.parse import parse_qs, urlparse

import boto3

from smart_tutor.knowledge.adapters.s3_object_store import S3ObjectStore


def test_presigned_post_binds_key_type_and_size() -> None:
    client = boto3.client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        endpoint_url="http://localhost:10402",
    )
    post = S3ObjectStore(client, "bucket").presign_post(
        "uploads/ada/u1.pdf", content_type="application/pdf", max_bytes=52_428_800, expires_in=600
    )
    policy = json.loads(base64.b64decode(post.fields["policy"]))
    assert post.fields["key"] == "uploads/ada/u1.pdf"
    assert post.fields["Content-Type"] == "application/pdf"
    assert {"key": "uploads/ada/u1.pdf"} in policy["conditions"]
    assert {"Content-Type": "application/pdf"} in policy["conditions"]
    assert ["content-length-range", 1, 52_428_800] in policy["conditions"]


def test_presigned_get_binds_key_content_type_and_expiry() -> None:
    client = boto3.client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        endpoint_url="http://localhost:10402",
    )
    url = S3ObjectStore(client, "bucket").presign_get("contents/ada/c1.pdf", expires_in=300)
    query = parse_qs(urlparse(url).query)
    assert urlparse(url).path.endswith("/contents/ada/c1.pdf")
    assert query["response-content-type"] == ["application/pdf"]
    assert abs(int(query["Expires"][0]) - time.time() - 300) < 30
