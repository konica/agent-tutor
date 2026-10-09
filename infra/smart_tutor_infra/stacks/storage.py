"""Documents bucket and ingest queue (#139, PRD §9.5).

`uploads/<user>/<id>.pdf` (browser presigned POST, expires after 1 day; each upload notifies the ingest queue) and
`contents/<sha256>.pdf` (the worker's deduplicated copies). Versioned and retained on teardown: documents are archived,
never deleted. CORS lets only the web app's address POST (the upload); on-premise has none until its Host stack
has an address (#149).
"""

from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_notifications as s3n
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from smart_tutor_infra.names import ModeNames

# A 500-page PDF is extracted, described, chunked, and embedded in one receive; the SQS default (30 s) would hand the
# same upload to the worker again while it's still working.
INGEST_VISIBILITY = cdk.Duration.minutes(15)


class StorageStack(cdk.Stack):
    def __init__(
        self, scope: Construct, construct_id: str, *, names: ModeNames, web_origin: str | None, **kwargs: Any
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        dlq = sqs.Queue(
            self,
            "IngestDeadLetterQueue",
            queue_name=names.ingest_dlq,
            retention_period=cdk.Duration.days(14),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        queue = sqs.Queue(
            self,
            "IngestQueue",
            queue_name=names.ingest_queue,
            visibility_timeout=INGEST_VISIBILITY,
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            dead_letter_queue=sqs.DeadLetterQueue(queue=dlq, max_receive_count=5),
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        bucket = s3.Bucket(
            self,
            "DocumentsBucket",
            bucket_name=names.documents_bucket(self.account),
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=True,
            removal_policy=cdk.RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    prefix="uploads/",
                    expiration=cdk.Duration.days(1),
                    noncurrent_version_expiration=cdk.Duration.days(1),
                    abort_incomplete_multipart_upload_after=cdk.Duration.days(1),
                )
            ],
            cors=[
                s3.CorsRule(allowed_methods=[s3.HttpMethods.POST], allowed_origins=[web_origin], allowed_headers=["*"])
            ]
            if web_origin
            else None,
        )
        bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED, s3n.SqsDestination(queue), s3.NotificationKeyFilter(prefix="uploads/")
        )

        cdk.CfnOutput(self, "DocumentsBucketName", value=bucket.bucket_name)
        cdk.CfnOutput(self, "IngestQueueUrl", value=queue.queue_url)
