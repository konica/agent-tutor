#!/bin/bash
# Mirrors the CDK storage/config stacks for local development (PRD §9.5, §9.12).
set -euo pipefail

REGION=us-east-1
BUCKET=smart-tutor-documents
QUEUE=smart-tutor-ingest
DLQ=smart-tutor-ingest-dlq

awslocal s3 mb "s3://$BUCKET" --region "$REGION"
awslocal s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled

DLQ_URL=$(awslocal sqs create-queue --queue-name "$DLQ" --query QueueUrl --output text)
DLQ_ARN=$(awslocal sqs get-queue-attributes --queue-url "$DLQ_URL" --attribute-names QueueArn --query Attributes.QueueArn --output text)
QUEUE_URL=$(awslocal sqs create-queue --queue-name "$QUEUE" \
  --attributes "{\"RedrivePolicy\":\"{\\\"deadLetterTargetArn\\\":\\\"$DLQ_ARN\\\",\\\"maxReceiveCount\\\":\\\"5\\\"}\"}" \
  --query QueueUrl --output text)
QUEUE_ARN=$(awslocal sqs get-queue-attributes --queue-url "$QUEUE_URL" --attribute-names QueueArn --query Attributes.QueueArn --output text)

# Add, new version, archive (tag), unarchive (tag removed) -> SQS (PRD §9.5 table).
awslocal s3api put-bucket-notification-configuration --bucket "$BUCKET" --notification-configuration "{
  \"QueueConfigurations\": [{
    \"QueueArn\": \"$QUEUE_ARN\",
    \"Events\": [\"s3:ObjectCreated:*\", \"s3:ObjectTagging:*\"],
    \"Filter\": {\"Key\": {\"FilterRules\": [{\"Name\": \"prefix\", \"Value\": \"subjects/\"}]}}
  }]
}"

awslocal ssm put-parameter --name /smart-tutor/learning-record-idle-minutes --type String --value 10 --overwrite

echo "smart-tutor LocalStack resources ready"
