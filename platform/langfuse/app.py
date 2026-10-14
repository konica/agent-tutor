"""CDK entry point for the shared Langfuse host (spec sdd/specs/2026-10-14-off-hours-and-langfuse-host-design.md §6)."""

import aws_cdk as cdk

from langfuse_platform.app import build_app

app = cdk.App()
build_app(app)
app.synth()
