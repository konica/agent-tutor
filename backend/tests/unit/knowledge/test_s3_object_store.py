import base64
import json

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
