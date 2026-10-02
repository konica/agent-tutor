"""CDK entry point. Stacks are empty until their M0/M4 tasks fill them in (PRD §9.12)."""

import aws_cdk as cdk

from smart_tutor_infra.app_stacks import build_app

app = cdk.App()
build_app(app)
app.synth()
