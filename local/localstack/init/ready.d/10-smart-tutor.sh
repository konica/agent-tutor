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

# Learner uploads (presigned POST to uploads/<user_id>/<upload_id>.pdf) -> SQS -> worker (PRD §9.5).
# The worker hashes the bytes and stores new contents at contents/<sha256>.pdf (no events there).
awslocal s3api put-bucket-notification-configuration --bucket "$BUCKET" --notification-configuration "{
  \"QueueConfigurations\": [{
    \"QueueArn\": \"$QUEUE_ARN\",
    \"Events\": [\"s3:ObjectCreated:*\"],
    \"Filter\": {\"Key\": {\"FilterRules\": [{\"Name\": \"prefix\", \"Value\": \"uploads/\"}]}}
  }]
}"

# Browser uploads from the local web app.
awslocal s3api put-bucket-cors --bucket "$BUCKET" --cors-configuration '{
  "CORSRules": [{"AllowedOrigins": ["http://localhost:10453"], "AllowedMethods": ["POST"], "AllowedHeaders": ["*"]}]
}'

awslocal ssm put-parameter --name /smart-tutor/learning-record-idle-minutes --type String --value 10 --overwrite

# Per-file limits (PRD §11): the API presigns and serves them, the worker checks pages.
awslocal ssm put-parameter --name /smart-tutor/max-upload-mb --type String --value 50 --overwrite
awslocal ssm put-parameter --name /smart-tutor/max-pages --type String --value 500 --overwrite

echo "smart-tutor LocalStack resources ready"
