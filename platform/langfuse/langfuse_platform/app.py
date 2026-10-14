"""Builds the Langfuse-Host stack from `langfuse:*` context (platform/langfuse/cdk.json)."""

import aws_cdk as cdk

from langfuse_platform.host_stack import DEFAULT_INSTANCE_TYPE, LangfuseHostStack


def build_app(app: cdk.App) -> LangfuseHostStack:
    context = app.node.try_get_context
    return LangfuseHostStack(
        app,
        "Langfuse-Host",
        env=cdk.Environment(region=context("langfuse:region") or "us-east-1"),
        instance_type=context("langfuse:instance-type") or DEFAULT_INSTANCE_TYPE,
        domain=context("langfuse:domain") or None,
        admin_email=app.node.get_context("langfuse:admin-email"),
        data_snapshot_id=context("langfuse:data-snapshot-id") or None,
        alert_emails=context("langfuse:alert-emails") or [],
    )
