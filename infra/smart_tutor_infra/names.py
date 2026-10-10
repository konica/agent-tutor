"""Fixed AWS resource names, per deployment mode (#139, #147).

IAM in ClusterStack builds ARNs from these instead of referencing StorageStack, so Cluster → Storage → Edge → Cluster
can't form a cycle. Each mode has its own stacks, bucket, queues, SSM parameters, secrets, and deploy role; the modes
share only the ECR repositories `smart-tutor/<service>`. Native-cloud keeps the names the pilot was deployed with.
"""

from dataclasses import dataclass

ON_PREMISE = "on-premise"
NATIVE_CLOUD = "native-cloud"
MODES = (ON_PREMISE, NATIVE_CLOUD)
DEFAULT_MODE = ON_PREMISE


@dataclass(frozen=True)
class ModeNames:
    mode: str
    stack_prefix: str  # CloudFormation stacks: <stack_prefix>-Storage
    resource_prefix: str  # per-environment resources: the budget, the EKS cluster
    data_prefix: str  # the bucket, queues, SSM path, secrets, and deploy role

    @property
    def ingest_queue(self) -> str:
        return f"{self.data_prefix}-ingest"

    @property
    def ingest_dlq(self) -> str:
        return f"{self.data_prefix}-ingest-dlq"

    @property
    def ssm_path(self) -> str:
        return f"/{self.data_prefix}"

    @property
    def secret_prefix(self) -> str:
        return self.data_prefix

    @property
    def deploy_role(self) -> str:
        return f"{self.data_prefix}-github-deploy"

    @property
    def deploy_document(self) -> str:
        """The SSM Command document that deploys one image tag on the on-premise host (HostStack)."""
        return f"{self.data_prefix}-deploy"

    def documents_bucket(self, account: str) -> str:
        return f"{self.data_prefix}-documents-{account}"


def mode_names(mode: str, env_name: str = "prod") -> ModeNames:
    if mode == NATIVE_CLOUD:
        return ModeNames(mode, f"SmartTutor-{env_name}", f"smart-tutor-{env_name}", "smart-tutor")
    if mode == ON_PREMISE:
        return ModeNames(
            mode, f"SmartTutor-OnPremise-{env_name}", f"smart-tutor-on-premise-{env_name}", "smart-tutor-on-premise"
        )
    raise ValueError(f"Unknown deployment mode {mode!r} in context smart-tutor:mode; use one of: {', '.join(MODES)}")
