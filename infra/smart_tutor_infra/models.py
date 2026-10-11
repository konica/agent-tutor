"""Bedrock models the pilot's services call (backend `shared/config.py` ModelsConfig), for IAM (#139).

The agent model is a US cross-region inference profile: invoking it needs the profile ARN and the foundation model in
every region it routes to (`aws bedrock get-inference-profile --inference-profile-identifier us.amazon.nova-2-lite-v1:0`).

The CI evals role (`docs/runbooks/evals-ci.md`, #226) is granted the same models plus the eval judge, `JUDGE_MODEL`.
"""

AGENT_PROFILE = "us.amazon.nova-2-lite-v1:0"
AGENT_MODEL = "amazon.nova-2-lite-v1:0"
AGENT_MODEL_REGIONS = ("us-east-1", "us-east-2", "us-west-2")
EMBEDDING_MODEL = "amazon.nova-2-multimodal-embeddings-v1:0"
JUDGE_MODEL = "qwen.qwen3-32b-v1:0"
