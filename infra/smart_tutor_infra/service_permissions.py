"""What each app service may do in AWS, per deployment mode (#139, #149).

Native-cloud gives each service its own Pod Identity role (ClusterStack); on-premise runs every service on one VM, so
the Host's instance role gets all four lists. ARNs are built from ModeNames, never from StorageStack, so neither stack
references Storage.
"""

import aws_cdk as cdk
from aws_cdk import aws_iam as iam
from aws_cdk import aws_ssm as ssm

from smart_tutor_infra.models import (
    AGENT_MODEL,
    AGENT_MODEL_REGIONS,
    AGENT_PROFILE,
    EMBEDDING_MODEL,
    GUARDRAIL_PROFILE,
    GUARDRAIL_PROFILE_REGIONS,
)
from smart_tutor_infra.names import ModeNames

# The agent's CloudWatch namespace (backend constant AGENT_METRICS_NAMESPACE); PutMetricData is granted for it only.
AGENT_METRICS_NAMESPACE = "SmartTutor/Agent"


class ServicePermissions:
    def __init__(self, stack: cdk.Stack, names: ModeNames) -> None:
        self.bucket_arn = f"arn:aws:s3:::{names.documents_bucket(stack.account)}"
        self.queue_arn = f"arn:aws:sqs:{stack.region}:{stack.account}:{names.ingest_queue}"
        self.ssm = iam.PolicyStatement(
            actions=["ssm:GetParameter", "ssm:GetParameters"],
            resources=[f"arn:aws:ssm:{stack.region}:{stack.account}:parameter{names.ssm_path}/*"],
        )
        invoke = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        self.chat = iam.PolicyStatement(
            actions=invoke,
            resources=[
                f"arn:aws:bedrock:{stack.region}:{stack.account}:inference-profile/{AGENT_PROFILE}",
                *(f"arn:aws:bedrock:{r}::foundation-model/{AGENT_MODEL}" for r in AGENT_MODEL_REGIONS),
            ],
        )
        self.embed = iam.PolicyStatement(
            actions=invoke, resources=[f"arn:aws:bedrock:{stack.region}::foundation-model/{EMBEDDING_MODEL}"]
        )
        # The question screen (#199). ConfigStack writes the guardrail's id to SSM; reading it at deploy time needs no
        # cross-stack export, only that the stack deploys after ConfigStack (app_stacks).
        guardrail_id = ssm.StringParameter.value_for_string_parameter(stack, f"{names.ssm_path}/question-guardrail-id")
        self.apply_guardrail = iam.PolicyStatement(
            sid="ApplyQuestionScreen",
            actions=["bedrock:ApplyGuardrail"],
            resources=[
                f"arn:aws:bedrock:{stack.region}:{stack.account}:guardrail/{guardrail_id}",
                *(
                    f"arn:aws:bedrock:{r}:{stack.account}:guardrail-profile/{GUARDRAIL_PROFILE}"
                    for r in GUARDRAIL_PROFILE_REGIONS
                ),
            ],
        )
        # PutMetricData has no resource-level permissions; the namespace condition limits it.
        self.put_agent_metrics = iam.PolicyStatement(
            sid="PublishAgentMetrics",
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
            conditions={"StringEquals": {"cloudwatch:namespace": AGENT_METRICS_NAMESPACE}},
        )

    def api(self) -> list[iam.PolicyStatement]:
        """The API signs uploads into uploads/ (the browser's POST is authorised as this role), presigns the document
        viewer's GET on contents/*.pdf, never the page text (US-4b), sends Retry messages (#95), reads its startup
        parameters, embeds subject names, and deletes a document's files, every version."""
        bucket_arn = self.bucket_arn
        return [
            self.ssm,
            iam.PolicyStatement(actions=["s3:PutObject"], resources=[f"{bucket_arn}/uploads/*"]),
            iam.PolicyStatement(
                actions=["s3:ListBucketVersions"],
                resources=[bucket_arn],
                conditions={"StringLike": {"s3:prefix": ["contents/*"]}},
            ),
            iam.PolicyStatement(actions=["s3:DeleteObjectVersion"], resources=[f"{bucket_arn}/contents/*"]),
            iam.PolicyStatement(actions=["s3:GetObject"], resources=[f"{bucket_arn}/contents/*.pdf"]),
            iam.PolicyStatement(actions=["sqs:SendMessage"], resources=[self.queue_arn]),
            self.embed,
        ]

    def worker(self) -> list[iam.PolicyStatement]:
        """The worker moves an upload into contents/<owner_id>/<content_id>.pdf, writes its page text, and deletes the
        upload; it describes first pages with the agent model and embeds chunks."""
        bucket_arn = self.bucket_arn
        return [
            self.ssm,
            iam.PolicyStatement(
                actions=["s3:GetObject"], resources=[f"{bucket_arn}/uploads/*", f"{bucket_arn}/contents/*"]
            ),
            iam.PolicyStatement(actions=["s3:PutObject"], resources=[f"{bucket_arn}/contents/*"]),
            iam.PolicyStatement(actions=["s3:DeleteObject"], resources=[f"{bucket_arn}/uploads/*"]),
            # GetObject on a missing key returns 404 (NoSuchKey) only when the caller may list the bucket, else 403.
            # S3 makes that check implicitly and it carries no s3:prefix context key, so a prefix condition would
            # never match; the grant is on the bucket ARN with no condition.
            iam.PolicyStatement(actions=["s3:ListBucket"], resources=[bucket_arn]),
            iam.PolicyStatement(
                actions=[
                    "sqs:ReceiveMessage",
                    "sqs:DeleteMessage",
                    "sqs:ChangeMessageVisibility",
                    "sqs:GetQueueAttributes",
                ],
                resources=[self.queue_arn],
            ),
            self.chat,
            self.embed,
        ]

    def agent(self) -> list[iam.PolicyStatement]:
        """The agent chats, applies the question screen's guardrail, and counts the screen's failures (#199)."""
        return [self.chat, self.apply_guardrail, self.put_agent_metrics]

    def mcp(self) -> list[iam.PolicyStatement]:
        return [self.embed]
