# A learner uploads a PDF and asks a question on AWS — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On the pilot (`https://<id>.cloudfront.net`), a learner uploads a PDF, the worker processes it into the Library, and the learner asks a question answered from it with citations; Retry from the Library works (#95).

**Architecture:** CDK `StorageStack` creates the documents bucket (private, versioned, retained on teardown), the ingest queue and its DLQ, and the `uploads/` → SQS notification; the bucket's CORS allows only the CloudFront address, so Storage takes it from Edge. `ClusterStack` gives `api`, `worker`, `agent`, and `mcp-server` service accounts least-privilege Pod Identity roles, built from fixed resource names in `names.py` and model IDs in `models.py` (no Cluster → Storage reference, so no stack cycle). Helm gets `agent`, `mcp-server`, and `worker` charts in the `api` chart's pattern; the API gets the bucket, queue URL, and in-cluster agent URL. The deploy workflow builds the three new images, passes the Storage outputs to Helm, and checks the in-cluster services. CloudFront's origin read timeout goes to 60 s so a streamed answer isn't cut by a 30 s gap.

**Tech Stack:** aws-cdk-lib (`aws_s3`, `aws_s3_notifications`, `aws_sqs`, `aws_iam`, `aws_cloudfront_origins`), Helm v4.2.1, External Secrets `external-secrets.io/v1`, GitHub Actions, pytest + PyYAML.

**Spec:** GitHub issue #139 (parent #54; also delivers #95); PRD §9.1, §9.2, §9.5, §9.9, §9.11, §9.12, §9.14 (IAM list near `sdd/prd.md:746`, storage near `:440`, uploads near `:381`); plans `2026-10-08-api-on-aws.md` (#58) and `2026-10-08-deploy-on-merge.md` (#59), whose patterns this follows.

**Facts checked 2026-10-08:**
- `SmartTutor-prod-Storage` has no resources; `smart-tutor-documents` doesn't exist in any account (S3 404), so the browser's presigned POST gets `NoSuchBucket` without CORS headers (the reported "CORS error").
- Models (`backend/src/smart_tutor/shared/config.py:20-32`): agent `us.amazon.nova-2-lite-v1:0` (inference profile, ACTIVE; routes to `amazon.nova-2-lite-v1:0` in us-east-1, us-east-2, us-west-2); embedding `amazon.nova-2-multimodal-embeddings-v1:0` (us-east-1, ACTIVE). The judge model is evals-only.
- Who calls what: API — presigned POST (`s3_object_store.py:17`, signs only; the browser's POST is authorised as the API role → `s3:PutObject` on `uploads/*`), SQS send (Retry), SSM, Bedrock embeddings (subject names). Worker — S3 get `uploads/*` and `contents/*`, copy/put `contents/*`, delete `uploads/*` (`ingestion_service.py:95-151`), SQS receive/delete (long-poll 20 s, `sqs_queue.py`), SSM `max-upload-mb`/`max-pages`, Bedrock chat (first-pages description) and embeddings; startup embeds missing subject names (needs DB + Bedrock); no HTTP server. Agent — `POST /ask`, `GET /healthz` on 8080, introspects with `smart-tutor-api` (audience `smart-tutor-api`), SSM `detect-threshold`/`detect-margin`/`multi-margin`, Bedrock chat only, calls MCP at `settings.mcp_url` forwarding the user token; DB (Compose sets `DATABASE_URL`). MCP — streamable HTTP on 8000 at `/mcp`, introspects with `rag-mcp` (audience `rag-mcp`), DB, Bedrock embeddings; no health endpoint. Web tokens already carry both audiences (realm `smart-tutor-web` mappers) — no realm change.
- Local LocalStack init (`local/localstack/init/ready.d/10-smart-tutor.sh`): versioning on; DLQ `smart-tutor-ingest-dlq`, queue `smart-tutor-ingest` with `maxReceiveCount` 5; notification `s3:ObjectCreated:*` with prefix `uploads/`; CORS `POST`, headers `*`.
- API → agent client: `httpx.Timeout(10, read=120)` (`apps/api/services.py:71`); SSE has no heartbeats; CloudFront's VPC origin uses the default 30 s read timeout; the ALB idle timeout is the default 60 s.
- Chart image repositories are wrong today (`smart-tutor-agent`, `smart-tutor-mcp`, `smart-tutor-worker`); ECR has `smart-tutor/agent`, `smart-tutor/mcp`, `smart-tutor/worker` (`registry.py`). The three charts have only `Chart.yaml`, `values.yaml`, `templates/.gitkeep`.

## Global Constraints

- Names (`infra/smart_tutor_infra/names.py`, Task 1): bucket `smart-tutor-documents-<account id>`; queue `smart-tutor-ingest`; DLQ `smart-tutor-ingest-dlq`. Storage outputs `DocumentsBucketName`, `IngestQueueUrl`.
- Bucket: block all public access, SSE-S3, `enforce_ssl`, versioned, `RemovalPolicy.RETAIN` (documents are archived, never deleted; PRD invariant), lifecycle rule on prefix `uploads/`: expire after 1 day, noncurrent versions expire after 1 day, abort incomplete multipart uploads after 1 day. CORS: `AllowedOrigins` = exactly the CloudFront address (`https://<id>.cloudfront.net`), `AllowedMethods` `POST`, `AllowedHeaders` `*`. Notification: `ObjectCreated` with prefix `uploads/` → ingest queue.
- Queues: ingest visibility timeout **900 s** (a 500-page PDF takes minutes; the SQS default 30 s would redeliver mid-processing), SSE-SQS, DLQ after **5** receives, DLQ retention 14 days; both `RemovalPolicy.DESTROY`.
- Models (`infra/smart_tutor_infra/models.py`, Task 2): `AGENT_PROFILE = "us.amazon.nova-2-lite-v1:0"`, `AGENT_MODEL = "amazon.nova-2-lite-v1:0"`, `AGENT_MODEL_REGIONS = ("us-east-1", "us-east-2", "us-west-2")`, `EMBEDDING_MODEL = "amazon.nova-2-multimodal-embeddings-v1:0"`; a test keeps them equal to the backend config.
- Pod Identity (namespace `smart-tutor`), actions on specific resources only:
  - `api` (SA `api`): `ssm:GetParameter(s)` on `parameter/smart-tutor/*` (unchanged); `s3:PutObject` on `<bucket>/uploads/*`; `sqs:SendMessage` on the ingest queue; Bedrock embedding.
  - `worker` (SA `worker`): SSM as above; `s3:GetObject` on `uploads/*` and `contents/*`; `s3:PutObject` on `contents/*`; `s3:DeleteObject` on `uploads/*`; `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:ChangeMessageVisibility`, `sqs:GetQueueAttributes` on the ingest queue; Bedrock agent model and embedding.
  - `agent` (SA `agent`): SSM as above; Bedrock agent model.
  - `mcp-server` (SA `mcp-server`): Bedrock embedding.
  - Bedrock actions `bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream`. Agent model resources: `arn:aws:bedrock:us-east-1:<account>:inference-profile/us.amazon.nova-2-lite-v1:0` plus `arn:aws:bedrock:<r>::foundation-model/amazon.nova-2-lite-v1:0` for each `r` in `AGENT_MODEL_REGIONS`. Embedding: `arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-2-multimodal-embeddings-v1:0`.
- Edge: VPC origin `read_timeout` 60 s (the CloudFront maximum without a quota increase).
- Helm: services `agent` (port 80 → 8080) and `mcp-server` (port 80 → 8000); API `SMART_TUTOR_AGENT_URL=http://agent`; agent and MCP `SMART_TUTOR_MCP_URL=http://mcp-server/mcp`. Images `smart-tutor/agent`, `smart-tutor/mcp`, `smart-tutor/worker`. Globals `global.documentsBucket`, `global.ingestQueueUrl` set at deploy time from the Storage outputs; rendering `api` or `worker` with `global.secretStore` set and either global empty **fails** (as `publicUrl` already does). ExternalSecrets from `smart-tutor/db/app` (URL template as the api chart), `smart-tutor/keycloak/api-client` (agent), `smart-tutor/keycloak/mcp-client` (MCP). Every pod: `runAsNonRoot`, seccomp `RuntimeDefault`, `readOnlyRootFilesystem`, drop ALL, `/tmp` emptyDir, `HOME=/tmp`. Probes: agent `/healthz`; MCP TCP on 8000; worker none (a poller). `values-prod.yaml` turns on `agent` (2), `mcp-server` (1), `worker` (1).
- No secret value in Git, values, manifests, or logs. No realm change.
- Commits: imperative subject, body says why, trailer exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Checks: `cd infra && JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1 uv run pytest -q`; `uv run ruff check` on changed Python; `helm lint deploy/helm/smart-tutor` and the prod lint (`-f values-prod.yaml --set global.publicUrl=https://d111.cloudfront.net`). Never deploy, push, or call AWS from a task.

## Review Focus

1. **The browser's upload from the CloudFront origin.** CORS must name exactly the deployed address. Pinned in Task 1 (`test_documents_bucket_cors_allows_only_the_cloudfront_address`).
2. **A long answer cut off mid-stream.** Pinned in Task 1 (`test_origin_waits_60_seconds_between_bytes`).
3. **The same PDF processed twice or dropped.** Visibility timeout and DLQ pinned in Task 1 (`test_ingest_queue_outlasts_a_long_ingestion_and_dead_letters_after_5`).
4. **A service reaching data it doesn't need** (the API reading documents, the worker deleting `contents/`). Pinned in Task 2 (`test_each_service_gets_only_its_own_s3_sqs_and_bedrock_access`).
5. **Wrong in-cluster wiring** (service names, ports, URLs between API → agent → MCP). Pinned in Task 3 (`test_api_agent_and_mcp_find_each_other`) and Task 5's in-cluster check step.

---

### Task 1: Storage (bucket, queues) and a 60-second origin read timeout

**Files:**
- Create: `infra/smart_tutor_infra/names.py`
- Modify: `infra/smart_tutor_infra/stacks/storage.py`, `infra/smart_tutor_infra/stacks/edge.py`, `infra/smart_tutor_infra/app_stacks.py`
- Test: `infra/tests/test_storage.py` (create), `infra/tests/test_synth.py` (edge test)

**Interfaces:**
- Produces: `names.documents_bucket_name(account: str) -> str` (`f"smart-tutor-documents-{account}"`), `names.INGEST_QUEUE = "smart-tutor-ingest"`, `names.INGEST_DLQ = "smart-tutor-ingest-dlq"`; `EdgeStack.public_url: str` (`f"https://{distribution.distribution_domain_name}"`); `StorageStack(scope, id, *, web_origin: str, **kwargs)`; outputs `DocumentsBucketName`, `IngestQueueUrl`.

- [ ] **Step 1: Write the failing tests** (`infra/tests/test_storage.py`; reuse `make_app`, `template` from `tests.test_synth`)

```python
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
                            {"Fn::Join": ["", ["https://", {"Fn::ImportValue": Match.string_like_regexp("SmartTutor-prod-Edge:.*DomainName.*")}]]}
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
```

Append to `infra/tests/test_synth.py`:

```python
def test_origin_waits_60_seconds_between_bytes() -> None:
    # Answers stream as SSE without heartbeats; CloudFront's default 30 s would cut a slow one with a 504.
    t = template(make_app(), "Edge")
    t.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {"Origins": [Match.object_like({"VpcOriginConfig": Match.object_like({"OriginReadTimeout": 60})})]}
            )
        },
    )
```

The existing `test_all_stacks_synthesize_in_us_east_1` counts 9 stacks (unchanged). If the `CorsConfiguration` import name differs from the regex (CDK names exports itself), adjust the regex to what `cdk synth` shows, keeping the point: the origin is the Edge distribution's domain, not a literal or `*`.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd infra && JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1 uv run pytest tests/test_storage.py tests/test_synth.py -q -k "storage or bucket or uploads or ingest or 60_seconds"`
Expected: FAIL (no bucket, no queue, no `OriginReadTimeout`).

- [ ] **Step 3: Implement**

`infra/smart_tutor_infra/names.py`:

```python
"""Fixed AWS resource names that several stacks use (#139). IAM in ClusterStack builds ARNs from these instead of
referencing StorageStack, so Cluster → Storage → Edge → Cluster can't form a cycle."""

INGEST_QUEUE = "smart-tutor-ingest"
INGEST_DLQ = "smart-tutor-ingest-dlq"


def documents_bucket_name(account: str) -> str:
    return f"smart-tutor-documents-{account}"
```

`stacks/storage.py` (replace the stub; fix the stale Glacier docstring — the PRD dropped Glacier):

```python
"""Documents bucket and ingest queue (#139, PRD §9.5).

`uploads/<user>/<id>.pdf` (browser presigned POST, expires after 1 day; each upload notifies the ingest queue) and
`contents/<sha256>.pdf` (the worker's deduplicated copies). Versioned and retained on teardown: documents are archived,
never deleted. CORS lets only the CloudFront address POST (the web app's upload).
"""

from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_notifications as s3n
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from smart_tutor_infra.names import INGEST_DLQ, INGEST_QUEUE, documents_bucket_name

# A 500-page PDF is extracted, described, chunked, and embedded in one receive; the SQS default (30 s) would hand the
# same upload to the worker again while it's still working.
INGEST_VISIBILITY = cdk.Duration.minutes(15)


class StorageStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, web_origin: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)

        dlq = sqs.Queue(
            self,
            "IngestDeadLetterQueue",
            queue_name=INGEST_DLQ,
            retention_period=cdk.Duration.days(14),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        queue = sqs.Queue(
            self,
            "IngestQueue",
            queue_name=INGEST_QUEUE,
            visibility_timeout=INGEST_VISIBILITY,
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            dead_letter_queue=sqs.DeadLetterQueue(queue=dlq, max_receive_count=5),
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        bucket = s3.Bucket(
            self,
            "DocumentsBucket",
            bucket_name=documents_bucket_name(self.account),
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
            ],
        )
        bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED, s3n.SqsDestination(queue), s3.NotificationKeyFilter(prefix="uploads/")
        )

        cdk.CfnOutput(self, "DocumentsBucketName", value=bucket.bucket_name)
        cdk.CfnOutput(self, "IngestQueueUrl", value=queue.queue_url)
```

`stacks/edge.py`: in `origins.VpcOrigin.with_application_load_balancer(...)` add `read_timeout=cdk.Duration.seconds(60),` with the comment `# answers stream as SSE without heartbeats; 30 s (the default) cut a slow one with a 504`; after the distribution, set `self.public_url = f"https://{distribution.distribution_domain_name}"` and use it in the `CloudFrontUrl` output (same value as today).

`app_stacks.py`: build Storage after Edge and pass `web_origin=edge.public_url`; keep every other dependency. Read the file first: Storage is constructed today as `StorageStack(app, f"{prefix}-Storage", env=env)` (around line 64) and is in the list whose members depend on Network. Moving its construction after Edge's is enough; CDK adds the Storage → Edge dependency from the cross-stack reference.

- [ ] **Step 4: Run all infra tests**

Run: `cd infra && JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1 uv run pytest -q && uv run ruff check smart_tutor_infra tests/test_storage.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add infra/smart_tutor_infra infra/tests
git commit -m "Create the documents bucket and the ingest queue" -m "The pilot had no bucket, so the browser's presigned POST got NoSuchBucket without CORS headers. StorageStack now creates the versioned, retained documents bucket (CORS for the CloudFront address only, uploads/ expiring after a day and notifying the ingest queue), the queue with a 15-minute visibility timeout, and its DLQ. CloudFront waits 60 s between bytes so a streamed answer isn't cut at 30 s."
```

---

### Task 2: Least-privilege Pod Identity for the API, worker, agent, and MCP server

**Files:**
- Create: `infra/smart_tutor_infra/models.py`
- Modify: `infra/smart_tutor_infra/stacks/cluster.py`
- Test: `infra/tests/test_synth.py` (replace `test_api_reads_only_the_smart_tutor_parameters_through_pod_identity`), `infra/tests/test_models.py` (create)

**Interfaces:**
- Consumes: `names.documents_bucket_name`, `names.INGEST_QUEUE` (Task 1).
- Produces: Pod Identity associations `smart-tutor`/`api`, `worker`, `agent`, `mcp-server` (Tasks 3–4 create those ServiceAccounts).

- [ ] **Step 1: Write the failing tests**

`infra/tests/test_models.py`:

```python
"""The Bedrock model IDs that IAM grants match the ones the backend calls."""

from pathlib import Path

from smart_tutor_infra.models import AGENT_PROFILE, EMBEDDING_MODEL

CONFIG = Path(__file__).parents[2] / "backend/src/smart_tutor/shared/config.py"


def test_iam_models_match_the_backend_config() -> None:
    text = CONFIG.read_text(encoding="utf-8")
    assert f'"{AGENT_PROFILE}"' in text
    assert f'"{EMBEDDING_MODEL}"' in text
```

In `infra/tests/test_synth.py`, replace `test_api_reads_only_the_smart_tutor_parameters_through_pod_identity` with:

```python
def _policy_for(t: Template, service_account: str) -> list[dict[str, Any]]:
    """The statements of the managed policy on the role associated with `smart-tutor/<service_account>`."""
    assoc = next(
        a for a in t.find_resources("AWS::EKS::PodIdentityAssociation").values()
        if a["Properties"]["Namespace"] == "smart-tutor" and a["Properties"]["ServiceAccount"] == service_account
    )
    role_id = assoc["Properties"]["RoleArn"]["Fn::GetAtt"][0]
    role = t.find_resources("AWS::IAM::Role")[role_id]
    policy_id = role["Properties"]["ManagedPolicyArns"][0]["Ref"]
    return t.find_resources("AWS::IAM::ManagedPolicy")[policy_id]["Properties"]["PolicyDocument"]["Statement"]


def _grants(statements: list[dict[str, Any]]) -> dict[str, str]:
    """action → JSON of its resources, for compact assertions."""
    out: dict[str, str] = {}
    for s in statements:
        actions = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
        for a in actions:
            out[a] = out.get(a, "") + json.dumps(s["Resource"])
    return out


def test_each_service_gets_only_its_own_s3_sqs_and_bedrock_access() -> None:
    t = template(make_app(), "Cluster")
    api, worker, agent, mcp = (_grants(_policy_for(t, sa)) for sa in ("api", "worker", "agent", "mcp-server"))

    # The API only signs uploads into uploads/ and sends Retry messages; it never reads documents.
    assert "s3:GetObject" not in api and "s3:DeleteObject" not in api
    assert "uploads/*" in api["s3:PutObject"] and "contents/" not in api["s3:PutObject"]
    assert "smart-tutor-ingest" in api["sqs:SendMessage"]
    assert "amazon.nova-2-multimodal-embeddings-v1:0" in api["bedrock:InvokeModel"]
    assert "parameter/smart-tutor/*" in api["ssm:GetParameter"]

    # The worker moves uploads into contents and never deletes a content.
    assert "uploads/*" in worker["s3:GetObject"] and "contents/*" in worker["s3:GetObject"]
    assert "contents/*" in worker["s3:PutObject"] and "uploads/" not in worker["s3:PutObject"]
    assert "uploads/*" in worker["s3:DeleteObject"] and "contents/" not in worker["s3:DeleteObject"]
    for action in ("sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility"):
        assert "smart-tutor-ingest" in worker[action] and "dlq" not in worker[action]
    assert "nova-2-lite" in worker["bedrock:InvokeModel"] and "embeddings" in worker["bedrock:InvokeModel"]

    # The agent only chats; the MCP server only embeds queries.
    assert not any(a.startswith(("s3:", "sqs:")) for a in agent)
    assert "inference-profile/us.amazon.nova-2-lite-v1:0" in agent["bedrock:InvokeModel"]
    for region in ("us-east-1", "us-east-2", "us-west-2"):
        assert f"arn:aws:bedrock:{region}::foundation-model/amazon.nova-2-lite-v1:0" in agent["bedrock:InvokeModel"]
    assert "embeddings" not in agent["bedrock:InvokeModel"]
    assert set(mcp) == {"bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"}
    assert "nova-2-lite" not in mcp["bedrock:InvokeModel"]

    # No wildcard actions or resources on any service.
    for grants in (api, worker, agent, mcp):
        assert not any(a.endswith(":*") or a == "*" for a in grants)
        assert not any(r == '"*"' for r in grants.values())
```

Add `from typing import Any` and `from aws_cdk.assertions import Template` to the test file's imports if missing. Resources may be CloudFormation intrinsics (`Fn::Join` with `AWS::AccountId`); `json.dumps` keeps the literal parts (`uploads/*`, `smart-tutor-ingest`, model IDs) searchable.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd infra && JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1 uv run pytest tests/test_models.py tests/test_synth.py -q -k "models or each_service"`
Expected: FAIL (`smart_tutor_infra.models` missing; no worker/agent/mcp associations).

- [ ] **Step 3: Implement**

`infra/smart_tutor_infra/models.py`:

```python
"""Bedrock models the pilot's services call (backend `shared/config.py` ModelsConfig), for IAM (#139).

The agent model is a US cross-region inference profile: invoking it needs the profile ARN and the foundation model in
every region it routes to (`aws bedrock get-inference-profile --inference-profile-identifier us.amazon.nova-2-lite-v1:0`).
"""

AGENT_PROFILE = "us.amazon.nova-2-lite-v1:0"
AGENT_MODEL = "amazon.nova-2-lite-v1:0"
AGENT_MODEL_REGIONS = ("us-east-1", "us-east-2", "us-west-2")
EMBEDDING_MODEL = "amazon.nova-2-multimodal-embeddings-v1:0"
```

In `stacks/cluster.py` (keep `_pod_identity` as is; update the module docstring to say the app services get roles too), replace the `Api` `_pod_identity` call with four, built from small helpers in the class:

```python
        bucket_arn = f"arn:aws:s3:::{documents_bucket_name(self.account)}"
        queue_arn = f"arn:aws:sqs:{self.region}:{self.account}:{INGEST_QUEUE}"
        ssm = iam.PolicyStatement(
            actions=["ssm:GetParameter", "ssm:GetParameters"],
            resources=[f"arn:aws:ssm:{self.region}:{self.account}:parameter/smart-tutor/*"],
        )
        invoke = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        chat = iam.PolicyStatement(
            actions=invoke,
            resources=[
                f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/{AGENT_PROFILE}",
                *(f"arn:aws:bedrock:{r}::foundation-model/{AGENT_MODEL}" for r in AGENT_MODEL_REGIONS),
            ],
        )
        embed = iam.PolicyStatement(
            actions=invoke, resources=[f"arn:aws:bedrock:{self.region}::foundation-model/{EMBEDDING_MODEL}"]
        )

        # The API signs uploads into uploads/ (the browser's POST is authorised as this role), sends Retry messages
        # (#95), reads its startup parameters, and embeds subject names.
        self._pod_identity("Api", "smart-tutor", "api", iam.PolicyDocument(statements=[
            ssm,
            iam.PolicyStatement(actions=["s3:PutObject"], resources=[f"{bucket_arn}/uploads/*"]),
            iam.PolicyStatement(actions=["sqs:SendMessage"], resources=[queue_arn]),
            embed,
        ]))
        # The worker moves an upload into contents/<sha256>.pdf, writes its page text, and deletes the upload; it
        # describes first pages with the agent model and embeds chunks.
        self._pod_identity("Worker", "smart-tutor", "worker", iam.PolicyDocument(statements=[
            ssm,
            iam.PolicyStatement(actions=["s3:GetObject"], resources=[f"{bucket_arn}/uploads/*", f"{bucket_arn}/contents/*"]),
            iam.PolicyStatement(actions=["s3:PutObject"], resources=[f"{bucket_arn}/contents/*"]),
            iam.PolicyStatement(actions=["s3:DeleteObject"], resources=[f"{bucket_arn}/uploads/*"]),
            iam.PolicyStatement(
                actions=["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes"],
                resources=[queue_arn],
            ),
            chat,
            embed,
        ]))
        self._pod_identity("Agent", "smart-tutor", "agent", iam.PolicyDocument(statements=[ssm, chat]))
        self._pod_identity("Mcp", "smart-tutor", "mcp-server", iam.PolicyDocument(statements=[embed]))
```

Import `documents_bucket_name`, `INGEST_QUEUE` from `smart_tutor_infra.names` and the model constants from `smart_tutor_infra.models`. The `Api` construct IDs stay `ApiRole`/`ApiPolicy`/`ApiPodIdentity`, so CloudFormation updates the existing role in place.

- [ ] **Step 4: Run all infra tests and ruff**

Run: `cd infra && JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1 uv run pytest -q && uv run ruff check smart_tutor_infra tests`
Expected: PASS. If `test_load_balancer_controller_policy_fits_a_managed_policy` or other policy-count tests assume three roles, update their expectations (the assertion's intent stays).

- [ ] **Step 5: Commit**

```bash
git add infra/smart_tutor_infra infra/tests
git commit -m "Give the API, worker, agent, and MCP server their own AWS access" -m "Each service gets a Pod Identity role with only the S3 prefixes, queue, SSM parameters, and Bedrock models it calls. The API can sign uploads and send Retry messages (#95) but never read documents; the worker can't delete a content. ARNs come from fixed names, so ClusterStack doesn't depend on StorageStack."
```

---

### Task 3: The agent and MCP server run on EKS

**Files:**
- Create: `deploy/helm/smart-tutor/charts/agent/templates/{_helpers.tpl,deployment.yaml,service.yaml,serviceaccount.yaml,externalsecrets.yaml}`, `deploy/helm/smart-tutor/charts/mcp-server/templates/{_helpers.tpl,deployment.yaml,service.yaml,serviceaccount.yaml,externalsecrets.yaml}`
- Delete: `charts/agent/templates/.gitkeep`, `charts/mcp-server/templates/.gitkeep`
- Modify: `charts/agent/values.yaml`, `charts/mcp-server/values.yaml`, `charts/api/templates/deployment.yaml` (add `SMART_TUTOR_AGENT_URL`), `deploy/helm/smart-tutor/values-prod.yaml` (`agent.enabled: true`, `replicaCount: 2`; `mcp-server.enabled: true`)
- Test: `infra/tests/test_helm_chart.py`

**Interfaces:**
- Consumes: Pod Identity for SAs `agent`, `mcp-server` (Task 2); secrets `smart-tutor/db/app`, `smart-tutor/keycloak/api-client`, `smart-tutor/keycloak/mcp-client`; the api chart's patterns (read `charts/api/templates/*` first and mirror them: labels/image helpers, security contexts, `HOME=/tmp`, `/tmp` emptyDir, ExternalSecret shape, `fail` guard for a missing `global.publicUrl` when `global.secretStore` is set).
- Produces: Services `agent` (80 → 8080) and `mcp-server` (80 → 8000).

- [ ] **Step 1: Write the failing tests** (append to `infra/tests/test_helm_chart.py`; `render`, `find`, `PROD`, `DEPLOY`, `env_of` exist)

```python
def test_agent_runs_with_the_production_issuer_and_reaches_mcp() -> None:
    docs = render(*PROD, *DEPLOY)
    deploy = find(docs, "Deployment", "agent")
    pod = deploy["spec"]["template"]["spec"]
    (c,) = pod["containers"]
    env = env_of(c)
    assert c["image"] == "reg.example/smart-tutor/agent:abc123"
    assert pod["serviceAccountName"] == "agent"
    assert deploy["spec"]["replicas"] == 2
    assert env["SMART_TUTOR_KEYCLOAK_ISSUER"] == "https://d111.cloudfront.net/auth/realms/smart-tutor"
    assert env["SMART_TUTOR_KEYCLOAK_INTERNAL_URL"] == "http://keycloak/auth/realms/smart-tutor"
    assert env["SMART_TUTOR_KEYCLOAK_CLIENT_ID"] == "smart-tutor-api"
    assert env["SMART_TUTOR_KEYCLOAK_CLIENT_SECRET"] == {"secretKeyRef": {"name": "agent-keycloak", "key": "client-secret"}}
    assert env["SMART_TUTOR_DATABASE_URL"] == {"secretKeyRef": {"name": "agent-db", "key": "url"}}
    assert env["SMART_TUTOR_MCP_URL"] == "http://mcp-server/mcp"
    assert c["readinessProbe"]["httpGet"]["path"] == "/healthz"
    assert c["securityContext"]["readOnlyRootFilesystem"] is True


def test_mcp_server_introspects_as_rag_mcp() -> None:
    docs = render(*PROD, *DEPLOY)
    pod = find(docs, "Deployment", "mcp-server")["spec"]["template"]["spec"]
    (c,) = pod["containers"]
    env = env_of(c)
    assert c["image"] == "reg.example/smart-tutor/mcp:abc123"
    assert pod["serviceAccountName"] == "mcp-server"
    assert env["SMART_TUTOR_KEYCLOAK_CLIENT_ID"] == "rag-mcp"
    assert env["SMART_TUTOR_KEYCLOAK_AUDIENCE"] == "rag-mcp"
    assert env["SMART_TUTOR_KEYCLOAK_CLIENT_SECRET"] == {"secretKeyRef": {"name": "mcp-keycloak", "key": "client-secret"}}
    assert env["SMART_TUTOR_MCP_PORT"] == "8000"
    assert env["SMART_TUTOR_MCP_URL"] == "http://mcp-server/mcp"
    assert c["readinessProbe"]["tcpSocket"]["port"] == 8000
    secret = find(docs, "ExternalSecret", "mcp-keycloak")["spec"]
    assert secret["data"] == [{"secretKey": "client-secret", "remoteRef": {"key": "smart-tutor/keycloak/mcp-client"}}]


def test_api_agent_and_mcp_find_each_other() -> None:
    docs = render(*PROD, *DEPLOY)
    api_env = env_of(find(docs, "Deployment", "api")["spec"]["template"]["spec"]["containers"][0])
    assert api_env["SMART_TUTOR_AGENT_URL"] == "http://agent"
    agent_svc = find(docs, "Service", "agent")["spec"]["ports"][0]
    mcp_svc = find(docs, "Service", "mcp-server")["spec"]["ports"][0]
    assert (agent_svc["port"], agent_svc["targetPort"]) == (80, "http")
    assert (mcp_svc["port"], mcp_svc["targetPort"]) == (80, "http")
    agent_port = find(docs, "Deployment", "agent")["spec"]["template"]["spec"]["containers"][0]["ports"][0]
    mcp_port = find(docs, "Deployment", "mcp-server")["spec"]["template"]["spec"]["containers"][0]["ports"][0]
    assert (agent_port["name"], agent_port["containerPort"]) == ("http", 8080)
    assert (mcp_port["name"], mcp_port["containerPort"]) == ("http", 8000)
    for name in ("agent", "mcp-server"):
        assert find(docs, "ServiceAccount", name)
```

Remove `"agent"` and `"mcp-server"` from `test_production_keeps_the_agent_mcp_and_worker_off` (rename it `test_production_keeps_the_worker_off_until_task_4`; Task 4 deletes it).

The new `publicUrl` guards in the agent and MCP charts would break `test_keycloak_without_public_url_has_no_hostname`, which renders prod values without a public URL and already passes `--set api.enabled=false` to test Keycloak alone: add `--set agent.enabled=false --set mcp-server.enabled=false` to that render.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd infra && uv run pytest tests/test_helm_chart.py -q`
Expected: the three new tests FAIL (`StopIteration`: no agent/mcp-server resources).

- [ ] **Step 3: Write the charts** — mirror `charts/api/templates/*` exactly (helpers named `agent.labels`/`agent.image`, `mcp-server.labels`/`mcp-server.image`; the same pod and container security contexts, `/tmp` emptyDir, `HOME=/tmp`, `fail` guard when `global.secretStore` is set and `global.publicUrl` empty).

`charts/agent/values.yaml`:

```yaml
# The LangGraph agent (POST /ask, GET /healthz on 8080). Only the API calls it, in-cluster at http://agent.
# Image: backend/Dockerfile, target agent.
replicaCount: 1
image:
  repository: smart-tutor/agent
  tag: ""  # defaults to global.imageTag
awsRegion: us-east-1
keycloakInternalUrl: http://keycloak/auth/realms/smart-tutor
keycloakClientId: smart-tutor-api  # the agent introspects the learner's token as the API does (ADR 0007)
mcpUrl: http://mcp-server/mcp
secrets:
  database: smart-tutor/db/app
  keycloakClient: smart-tutor/keycloak/api-client
resources:
  requests: {cpu: 100m, memory: 256Mi}
  limits: {memory: 512Mi}
```

Agent container env: `SMART_TUTOR_ENVIRONMENT=prod`, `SMART_TUTOR_AWS_REGION`, `SMART_TUTOR_KEYCLOAK_ISSUER` (`<publicUrl>/auth/realms/smart-tutor`, as the api chart), `SMART_TUTOR_KEYCLOAK_INTERNAL_URL`, `SMART_TUTOR_KEYCLOAK_CLIENT_ID`, `SMART_TUTOR_KEYCLOAK_CLIENT_SECRET` from `agent-keycloak`/`client-secret`, `SMART_TUTOR_DATABASE_URL` from `agent-db`/`url`, `SMART_TUTOR_MCP_URL`, `HOME=/tmp`. Port `http` 8080; readiness `/healthz` every 10 s, liveness `/healthz` every 20 s. ExternalSecrets `agent-db` (template as `api-db`) and `agent-keycloak` (as `api-keycloak`), only when `global.secretStore` is set. Service `agent` port 80 → `http`. ServiceAccount `agent` with the comment `# Pod Identity associates this account with the agent's IAM role (ClusterStack).`

`charts/mcp-server/values.yaml`:

```yaml
# The RAG MCP server (streamable HTTP at /mcp on 8000). Only the agent calls it, in-cluster at http://mcp-server/mcp,
# forwarding the learner's token; it introspects as rag-mcp (ADR 0007). Image: backend/Dockerfile, target mcp.
replicaCount: 1
image:
  repository: smart-tutor/mcp
  tag: ""  # defaults to global.imageTag
port: 8000
awsRegion: us-east-1
keycloakInternalUrl: http://keycloak/auth/realms/smart-tutor
keycloakClientId: rag-mcp
mcpUrl: http://mcp-server/mcp  # its own public URL in the MCP auth metadata; the agent uses the same
secrets:
  database: smart-tutor/db/app
  keycloakClient: smart-tutor/keycloak/mcp-client
resources:
  requests: {cpu: 100m, memory: 256Mi}
  limits: {memory: 512Mi}
```

MCP env: as the agent's, but `SMART_TUTOR_KEYCLOAK_CLIENT_ID=rag-mcp`, `SMART_TUTOR_KEYCLOAK_AUDIENCE=rag-mcp`, secret `mcp-keycloak`, DB secret `mcp-db`, `SMART_TUTOR_MCP_PORT={{ .Values.port }}` (quoted string `"8000"`), `SMART_TUTOR_MCP_URL`. Port `http` 8000. Probes: `tcpSocket` on 8000 (it has no health endpoint; an unauthenticated `/mcp` answers 401) — readiness every 10 s, liveness every 20 s. Service `mcp-server` port 80 → `http`.

`charts/api/templates/deployment.yaml`: add after `SMART_TUTOR_KEYCLOAK_CLIENT_SECRET`:

```yaml
            - name: SMART_TUTOR_AGENT_URL
              value: {{ .Values.agentUrl | quote }}
```

and in `charts/api/values.yaml`: `agentUrl: http://agent  # in-cluster Service of the agent chart`.

`values-prod.yaml`: `agent: {enabled: true, replicaCount: 2}`, `mcp-server: {enabled: true}` (keep the file's comment style; drop the "#58" off-markers for these two).

- [ ] **Step 4: Run the chart tests and both lints**

Run: `cd infra && uv run pytest tests/test_helm_chart.py -q && cd .. && helm lint deploy/helm/smart-tutor && helm lint deploy/helm/smart-tutor -f deploy/helm/smart-tutor/values-prod.yaml --set global.publicUrl=https://d111.cloudfront.net`
Expected: PASS; `test_rendered_manifests_hold_no_secret_values` still passes.

- [ ] **Step 5: Commit**

```bash
git add deploy/helm/smart-tutor infra/tests/test_helm_chart.py
git commit -m "Run the agent and the MCP server on EKS" -m "The API reaches the agent at http://agent and the agent reaches MCP at http://mcp-server/mcp, forwarding the learner's token; each introspects with its own Keycloak client from Secrets Manager. Chart images now match the ECR repositories."
```

---

### Task 4: The worker runs on EKS and the API knows the bucket and queue

**Files:**
- Create: `deploy/helm/smart-tutor/charts/worker/templates/{_helpers.tpl,deployment.yaml,serviceaccount.yaml,externalsecrets.yaml}`
- Delete: `charts/worker/templates/.gitkeep`
- Modify: `charts/worker/values.yaml`, `charts/api/templates/deployment.yaml`, `deploy/helm/smart-tutor/values.yaml` (globals), `values-prod.yaml` (`worker.enabled: true`), `infra/tests/helm.py` (`DEPLOY`)
- Test: `infra/tests/test_helm_chart.py`

**Interfaces:**
- Consumes: Pod Identity SA `worker` (Task 2); Storage outputs (Task 1) arrive as `global.documentsBucket`, `global.ingestQueueUrl` (Task 5 passes them).
- Produces: globals `documentsBucket`, `ingestQueueUrl` (default `""`); `DEPLOY` in `infra/tests/helm.py` gains `--set global.documentsBucket=docs-bucket --set global.ingestQueueUrl=https://sqs.us-east-1.amazonaws.com/123/smart-tutor-ingest`.

- [ ] **Step 1: Write the failing tests** (append to `test_helm_chart.py`)

```python
QUEUE = "https://sqs.us-east-1.amazonaws.com/123/smart-tutor-ingest"


def test_worker_polls_the_ingest_queue_for_the_documents_bucket() -> None:
    docs = render(*PROD, *DEPLOY)
    deploy = find(docs, "Deployment", "worker")
    pod = deploy["spec"]["template"]["spec"]
    (c,) = pod["containers"]
    env = env_of(c)
    assert c["image"] == "reg.example/smart-tutor/worker:abc123"
    assert pod["serviceAccountName"] == "worker"
    assert env["SMART_TUTOR_DOCUMENTS_BUCKET"] == "docs-bucket"
    assert env["SMART_TUTOR_INGEST_QUEUE_URL"] == QUEUE
    assert env["SMART_TUTOR_DATABASE_URL"] == {"secretKeyRef": {"name": "worker-db", "key": "url"}}
    assert "ports" not in c and "readinessProbe" not in c  # a queue poller with no HTTP server
    assert c["securityContext"]["readOnlyRootFilesystem"] is True
    assert find(docs, "ServiceAccount", "worker")


def test_api_signs_uploads_for_the_bucket_and_sends_retries_to_the_queue() -> None:
    env = env_of(find(render(*PROD, *DEPLOY), "Deployment", "api")["spec"]["template"]["spec"]["containers"][0])
    assert env["SMART_TUTOR_DOCUMENTS_BUCKET"] == "docs-bucket"
    assert env["SMART_TUTOR_INGEST_QUEUE_URL"] == QUEUE


@pytest.mark.parametrize("missing", ["global.documentsBucket", "global.ingestQueueUrl"])
def test_aws_render_refuses_a_missing_bucket_or_queue(missing: str) -> None:
    args = [a for a in DEPLOY]
    i = next(i for i, a in enumerate(args) if a.startswith(missing + "="))
    del args[i - 1 : i + 1]  # drop "--set" and its value
    with pytest.raises(subprocess.CalledProcessError) as e:
        render(*PROD, *args)
    assert missing in e.value.stderr
```

Delete `test_production_keeps_the_worker_off_until_task_4`.

Two existing tests render prod values without some globals, so the new guards affect them:
- `test_keycloak_without_public_url_has_no_hostname`: also add `--set worker.enabled=false` (it already disables api, agent, mcp-server).
- `test_api_refuses_to_render_for_aws_without_public_url` renders without `publicUrl` *and* without the bucket and queue; Helm may report the worker's bucket error first. Pass the bucket and queue `--set`s in that render so the only missing value is `publicUrl`, and keep its assertion that stderr names `global.publicUrl`.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd infra && uv run pytest tests/test_helm_chart.py -q`
Expected: the new tests FAIL.

- [ ] **Step 3: Implement**

`values.yaml` (umbrella), under `global:` after `secretStore`:

```yaml
  # SmartTutor-prod-Storage outputs DocumentsBucketName and IngestQueueUrl, set at deploy time with --set. The API
  # and worker won't render for AWS without them.
  documentsBucket: ""
  ingestQueueUrl: ""
```

`charts/api/templates/deployment.yaml`: extend the top guard and add env:

```yaml
{{- if and .Values.global.secretStore (not .Values.global.documentsBucket) }}
{{- fail "api needs global.documentsBucket on AWS (SmartTutor-prod-Storage output DocumentsBucketName)" }}
{{- end }}
{{- if and .Values.global.secretStore (not .Values.global.ingestQueueUrl) }}
{{- fail "api needs global.ingestQueueUrl on AWS (SmartTutor-prod-Storage output IngestQueueUrl)" }}
{{- end }}
```

```yaml
            - name: SMART_TUTOR_DOCUMENTS_BUCKET
              value: {{ .Values.global.documentsBucket | quote }}
            - name: SMART_TUTOR_INGEST_QUEUE_URL
              value: {{ .Values.global.ingestQueueUrl | quote }}
```

`charts/worker/values.yaml`:

```yaml
# The ingestion worker: long-polls the ingest queue (S3 uploads/ events and Retry messages), extracts, describes,
# chunks, and embeds (PRD §9.5). No HTTP server, so no Service or probes. Image: backend/Dockerfile, target worker.
replicaCount: 1
image:
  repository: smart-tutor/worker
  tag: ""  # defaults to global.imageTag
awsRegion: us-east-1
secrets:
  database: smart-tutor/db/app
resources:
  requests: {cpu: 250m, memory: 512Mi}
  limits: {memory: 1536Mi}  # pypdf on a 500-page PDF
```

Worker Deployment in the api pattern (helpers `worker.labels`/`worker.image`, security contexts, `/tmp` emptyDir), with the same two `fail` guards (worded "worker needs …"), `serviceAccountName: worker`, env `SMART_TUTOR_ENVIRONMENT=prod`, `SMART_TUTOR_AWS_REGION`, `SMART_TUTOR_DOCUMENTS_BUCKET`, `SMART_TUTOR_INGEST_QUEUE_URL`, `SMART_TUTOR_DATABASE_URL` from `worker-db`/`url`, `HOME=/tmp`; `terminationGracePeriodSeconds: 60` (it finishes the current poll on SIGTERM); no ports, no probes. ExternalSecret `worker-db` (as `api-db`). ServiceAccount `worker`.

`infra/tests/helm.py`: append the two `--set` pairs to `DEPLOY`.

`values-prod.yaml`: `worker: {enabled: true}`.

- [ ] **Step 4: Run all infra tests and both lints**

Run: `cd infra && JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1 uv run pytest -q && cd .. && helm lint deploy/helm/smart-tutor && helm lint deploy/helm/smart-tutor -f deploy/helm/smart-tutor/values-prod.yaml --set global.publicUrl=https://d111.cloudfront.net --set global.documentsBucket=b --set global.ingestQueueUrl=q`
Expected: PASS. CI's prod lint in `.github/workflows/ci.yml` needs the same two `--set`s now; add them there (`test_workflows.py`'s CI test still passes).

- [ ] **Step 5: Commit**

```bash
git add deploy/helm/smart-tutor infra/tests .github/workflows/ci.yml
git commit -m "Run the worker on EKS and point the API at the bucket and queue" -m "Uploads now land in the real bucket and Retry (#95) reaches the worker's queue; both refuse to render for AWS without the Storage outputs, rather than fall back to LocalStack defaults."
```

---

### Task 5: The deploy builds the new images, passes the Storage outputs, and checks the services

**Files:**
- Modify: `.github/workflows/deploy-pilot.yml`
- Test: `infra/tests/test_workflows.py`

**Interfaces:**
- Consumes: Storage outputs `DocumentsBucketName`, `IngestQueueUrl` (Task 1); globals (Task 4); Services `agent`, `mcp-server` (Task 3).

- [ ] **Step 1: Write the failing tests** (update/append in `test_workflows.py`)

- In `test_merge_builds_pushes_and_deploys_in_order`, extend the image loop to all six (`smart-tutor/api`, `web`, `keycloak`, `agent`, `mcp`, `worker`) and assert `"--target agent"`, `"--target mcp"`, `"--target worker"` in the text.
- In `test_release_uses_the_tag_and_the_stack_outputs`, extend the outputs to `("RegistryUri", "CloudFrontUrl", "VpcId", "DocumentsBucketName", "IngestQueueUrl")` and assert `'global.documentsBucket="$DOCUMENTS_BUCKET"'` and `'global.ingestQueueUrl="$INGEST_QUEUE_URL"'` in the text.
- In `test_stack_outputs_fail_loudly_when_missing`, change both counts to 5.
- New:

```python
def test_rollback_checks_every_image() -> None:
    step = next(s for s in deploy_job()["steps"] if "describe-images" in str(s.get("run", "")))
    for repo in ("api", "web", "keycloak", "agent", "mcp", "worker"):
        assert repo in step["run"]


def test_release_is_followed_by_an_in_cluster_service_check() -> None:
    steps = deploy_job()["steps"]
    names = [s.get("name") for s in steps]
    check = steps[names.index("Check the in-cluster services")]
    assert names.index("Release the app (Helm)") < names.index("Check the in-cluster services") < names.index(
        "Smoke test the public address"
    )
    assert "http://agent/healthz" in check["run"] and "http://mcp-server/mcp" in check["run"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd infra && uv run pytest tests/test_workflows.py -q`
Expected: the changed and new tests FAIL.

- [ ] **Step 3: Implement in `deploy-pilot.yml`**

- "Read the stack outputs": add `documents_bucket=$(output Storage DocumentsBucketName)` and `ingest_queue_url=$(output Storage IngestQueueUrl)`, each with the same `[[ -n … && … != None ]] || { echo "::error::SmartTutor-prod-Storage has no <Key> output"; exit 1; }` guard, and write `DOCUMENTS_BUCKET` and `INGEST_QUEUE_URL` to `$GITHUB_ENV`.
- "Check the images to roll back to exist": loop over `api web keycloak agent mcp worker`.
- "Build the images": add
  `docker build --target agent -t "$REGISTRY/smart-tutor/agent:$IMAGE_TAG" backend`,
  `docker build --target mcp -t "$REGISTRY/smart-tutor/mcp:$IMAGE_TAG" backend`,
  `docker build --target worker -t "$REGISTRY/smart-tutor/worker:$IMAGE_TAG" backend`.
- "Push the images": loop over all six.
- "Release the app (Helm)": add `--set global.documentsBucket="$DOCUMENTS_BUCKET" --set global.ingestQueueUrl="$INGEST_QUEUE_URL"`.
- New step after the release, before the smoke test:

```yaml
      # The agent and MCP server are in-cluster only, so the smoke test can't reach them: check from an API pod that
      # the names, ports, and auth line up (agent healthy; MCP refuses a call without a token).
      - name: Check the in-cluster services
        run: |
          kubectl -n smart-tutor exec deploy/api -- python -c "import urllib.request as u; u.urlopen('http://agent/healthz', timeout=10)"
          kubectl -n smart-tutor exec deploy/api -- python -c "
          import urllib.error as e, urllib.request as u
          try:
              u.urlopen('http://mcp-server/mcp', timeout=10)
          except e.HTTPError as x:
              raise SystemExit(0 if x.code == 401 else f'MCP answered {x.code} without a token, expected 401')
          raise SystemExit('MCP answered without a token')"
```

(YAML block scalars keep the Python indentation relative to the `kubectl` line; verify by running the parsed `run` string through `python -c "import ast; ast.parse(...)"` in a quick local check of the inner snippet, or keep the second check on one line with `;` and a conditional expression if that's clearer.)
- "Diagnostics": add `kubectl -n smart-tutor logs deploy/worker --tail=50 || true` and `kubectl -n smart-tutor logs deploy/agent --tail=50 || true`.

- [ ] **Step 4: Run the workflow tests**

Run: `cd infra && uv run pytest tests/test_workflows.py tests/test_smoke_test.py -q && uv run ruff check tests/test_workflows.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/deploy-pilot.yml infra/tests/test_workflows.py
git commit -m "Deploy the worker, agent, and MCP server on merge" -m "The workflow builds and pushes their images, passes the Storage outputs to Helm, and checks from an API pod that the agent is healthy and MCP refuses an anonymous call, since neither is reachable from the public address."
```

---

### Task 6: Runbook and PRD

**Files:**
- Modify: `docs/runbooks/pilot-deploy.md`, `docs/runbooks/pilot-environment-overview.md`, `sdd/prd.md`

- [ ] **Step 1: Runbook (`pilot-deploy.md`)**
  - Title adds `#139`; intro says the pilot now runs upload, processing, and chat.
  - Step 2 output reads: add `$Bucket = Get-Output Storage DocumentsBucketName` and `$Queue = Get-Output Storage IngestQueueUrl`.
  - Step 5: build and push `agent`, `mcp`, `worker` (`docker build --target <t> -t "$Registry/smart-tutor/<t>:$Tag" backend`).
  - Step 6: add `--set global.documentsBucket=$Bucket --set global.ingestQueueUrl=$Queue` to the `helm upgrade` line (keep `--wait=legacy --timeout 15m`; `test_release_waits_with_the_legacy_strategy` reads it).
  - Step 7 checks: pods for `agent`, `mcp-server`, `worker` Running; the in-cluster check commands from the workflow; `kubectl -n smart-tutor logs deploy/worker` shows it polling.
  - New "Demo: upload and ask (#139)": as learner A, upload a seed-corpus PDF → it reaches *ready* with a title and subjects; ask a question about it → a streamed answer citing it; as learner B (second account), the document isn't in the Library and a question doesn't cite it; Retry on a failed document (#95) returns it to *processing*.
  - Troubleshooting: an upload stuck in *processing* → worker logs and the DLQ depth (`aws sqs get-queue-attributes --queue-url $Queue-dlq … ApproximateNumberOfMessages` — use the DLQ URL); "CORS error" on upload → the bucket's CORS must name the CloudFront address (`aws s3api get-bucket-cors --bucket $Bucket`); Bedrock `AccessDeniedException` → model access in the Bedrock console for the two models.
  - Teardown (section 10): destroy `SmartTutor-prod-Storage` **before** `SmartTutor-prod-Edge` (it imports Edge's domain); the documents bucket is **retained** — list how to empty and delete it by hand only if the data must go (`aws s3 rm s3://$Bucket --recursive` won't remove versions; use the console's *Empty* action), and that a redeploy reuses the retained bucket name (CloudFormation fails if the bucket exists outside the stack — import it or delete it first).
- [ ] **Step 2: Overview (`pilot-environment-overview.md`)**: the §5 row "S3 documents bucket, SQS, agent, MCP server, worker, Bedrock access — Later slices" becomes `#139`, with `StorageStack`, the Pod Identity roles, and the three charts.
- [ ] **Step 3: PRD (`sdd/prd.md`)**: in the IAM list (near line 746) the worker role reads `uploads/*` and `contents/*`, writes `contents/*`, and **deletes** `uploads/*`; the agent reads `detect-threshold`, `detect-margin`, `multi-margin` (not "answer-floor" — match the code); note the ingest queue's 15-minute visibility timeout and 5-receive DLQ where the queue is described. Bump the status-line version by one minor (e.g. v2.21 → v2.22) and add a one-line change note in the PRD's change log section with `#139`. Update `AGENTS.md`'s PRD version reference to match.
- [ ] **Step 4: Check and commit**

Run: `cd infra && uv run pytest tests/test_workflows.py -q` (reads the runbook).

```bash
git add docs/runbooks sdd/prd.md AGENTS.md
git commit -m "Document upload and ask on the pilot" -m "Runbook: the new images and Storage outputs, the in-cluster check, the #139 demo, troubleshooting, and why Storage goes before Edge on teardown while the documents bucket stays. PRD: the worker's delete on uploads/, the agent's actual SSM parameters, and the queue's timeouts."
```

---

### After the tasks: deploy and demo (human-approved)

1. Optional before merging: `make bedrock-check` from `backend/` (under a cent) confirms the account can invoke both models.
2. Merging the PR runs the deploy: CDK creates Storage and updates Cluster and Edge; Helm installs the three services; the in-cluster check and smoke test run.
3. The demo in the runbook, recorded on the PR (statuses and screenshots, no tokens). The PR closes #139 and #95.
