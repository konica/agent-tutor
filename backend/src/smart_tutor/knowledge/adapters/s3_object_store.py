"""ObjectStore on S3 (LocalStack locally)."""

from typing import TYPE_CHECKING

from botocore.exceptions import ClientError

from smart_tutor.knowledge.ports.object_store import ObjectNotFoundError, ObjectStore, PresignedPost

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


class S3ObjectStore(ObjectStore):
    def __init__(self, client: "S3Client", bucket: str) -> None:
        self._client, self._bucket = client, bucket

    def presign_post(self, key: str, *, content_type: str, max_bytes: int, expires_in: int) -> PresignedPost:
        # boto3 adds {"bucket": …} and {"key": key} to the policy, so the browser can't pick another key.
        post = self._client.generate_presigned_post(
            Bucket=self._bucket,
            Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[{"Content-Type": content_type}, ["content-length-range", 1, max_bytes]],
            ExpiresIn=expires_in,
        )
        return PresignedPost(url=post["url"], fields={k: str(v) for k, v in post["fields"].items()})

    def read(self, key: str) -> bytes:
        try:
            return self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                raise ObjectNotFoundError(key) from None
            raise

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)

    def copy(self, source_key: str, dest_key: str) -> None:
        self._client.copy_object(
            Bucket=self._bucket, Key=dest_key, CopySource={"Bucket": self._bucket, "Key": source_key}
        )

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)
