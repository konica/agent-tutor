"""CDK entry for the CI evals role (#337), apart from the deployment modes' `app.py`:
`npx --yes aws-cdk@2.1145.0 deploy --app "uv run python evals_ci_app.py" SmartTutor-EvalsCI` (make evals-ci-deploy).
It reads the same context from cdk.json."""

import aws_cdk as cdk

from smart_tutor_infra.app_stacks import build_evals_ci

app = cdk.App()
build_evals_ci(app)
app.synth()
