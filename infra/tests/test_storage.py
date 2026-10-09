"""The documents bucket and the ingest queue (#139, PRD §9.5)."""

from aws_cdk.assertions import Match

from tests.test_synth import make_app, template


def test_documents_bucket_is_private_versioned_and_kept() -> None:
    t = template(make_app(), "Storage")
    t.has_resource(
        "AWS::S3::Bucket",
        {
            "DeletionPolicy": "Retain",  # documents are archived, never deleted
            "Properties": Match.object_like(
                {
                    "BucketName": {"Fn::Join": ["", ["smart-tutor-documents-", {"Ref": "AWS::AccountId"}]]},
                    "VersioningConfiguration": {"Status": "Enabled"},
                    "PublicAccessBlockConfiguration": {
                        "BlockPublicAcls": True,
                        "BlockPublicPolicy": True,
                        "IgnorePublicAcls": True,
                        "RestrictPublicBuckets": True,
                    },
                }
            ),
        },
    )


def test_uploads_expire_after_a_day() -> None:
    t = template(make_app(), "Storage")
    t.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "LifecycleConfiguration": {
                "Rules": [
                    Match.object_like(
                        {
                            "Prefix": "uploads/",
                            "ExpirationInDays": 1,
                            "NoncurrentVersionExpiration": {"NoncurrentDays": 1},
                            "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1},
                            "Status": "Enabled",
                        }
                    )
                ]
            }
        },
    )


def test_documents_bucket_cors_allows_only_the_cloudfront_address() -> None:
    t = template(make_app(), "Storage")
    t.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "CorsConfiguration": {
                "CorsRules": [
                    {
                        "AllowedMethods": ["POST"],
                        "AllowedHeaders": ["*"],
                        "AllowedOrigins": [
                            {
                                "Fn::Join": [
                                    "",
                                    [
                                        "https://",
                                        {
                                            "Fn::ImportValue": Match.string_like_regexp(
                                                "SmartTutor-prod-Edge:.*DomainName.*"
                                            )
                                        },
                                    ],
                                ]
                            }
                        ],
                    }
                ]
            }
        },
    )


def test_ingest_queue_outlasts_a_long_ingestion_and_dead_letters_after_5() -> None:
    t = template(make_app(), "Storage")
    t.has_resource_properties(
        "AWS::SQS::Queue",
        {
            "QueueName": "smart-tutor-ingest",
            "VisibilityTimeout": 900,
            "SqsManagedSseEnabled": True,
            "RedrivePolicy": {"deadLetterTargetArn": Match.any_value(), "maxReceiveCount": 5},
        },
    )
    t.has_resource_properties(
        "AWS::SQS::Queue", {"QueueName": "smart-tutor-ingest-dlq", "MessageRetentionPeriod": 1209600}
    )


def test_uploads_notify_the_ingest_queue() -> None:
    t = template(make_app(), "Storage")
    t.has_resource_properties(
        "Custom::S3BucketNotifications",
        {
            "NotificationConfiguration": {
                "QueueConfigurations": [
                    Match.object_like(
                        {
                            "Events": ["s3:ObjectCreated:*"],
                            "Filter": {"Key": {"FilterRules": [{"Name": "prefix", "Value": "uploads/"}]}},
                        }
                    )
                ]
            }
        },
    )


def test_storage_outputs_the_bucket_and_queue() -> None:
    t = template(make_app(), "Storage")
    t.has_output("DocumentsBucketName", {})
    t.has_output("IngestQueueUrl", {})
