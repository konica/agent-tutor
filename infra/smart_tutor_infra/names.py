"""Fixed AWS resource names that several stacks use (#139). IAM in ClusterStack builds ARNs from these instead of
referencing StorageStack, so Cluster → Storage → Edge → Cluster can't form a cycle."""

INGEST_QUEUE = "smart-tutor-ingest"
INGEST_DLQ = "smart-tutor-ingest-dlq"


def documents_bucket_name(account: str) -> str:
    return f"smart-tutor-documents-{account}"
