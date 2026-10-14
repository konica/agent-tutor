"""Off-hours for one EC2 host (spec sdd/specs/2026-10-14-off-hours-and-langfuse-host-design.md §4, ADR 0022).

EventBridge Scheduler stops the instance at 18:00 and again at 00:00 (a host someone started by hand in the evening)
and starts it at 07:00, in the given time zone, by calling the EC2 API directly (universal targets): no Lambda, no
alarm, no dead-letter queue. Stopping a stopped instance, or starting a running one, changes nothing, so a person may
start the host at any hour; it then runs until the next stop.

The app host's CDK project keeps its own copy of this construct; keep the two in step when the schedule's shape
changes.
"""

import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_scheduler as scheduler
from constructs import Construct

# (schedule name, cron expression in the time zone, EC2 API action)
SCHEDULES = (
    ("stop", "cron(0 18 * * ? *)", "stopInstances"),
    ("stop-late", "cron(0 0 * * ? *)", "stopInstances"),
    ("start", "cron(0 7 * * ? *)", "startInstances"),
)
RETRY_ATTEMPTS = 2


class OffHours(Construct):
    def __init__(
        self, scope: Construct, construct_id: str, *, instance: ec2.Instance, name_prefix: str, time_zone: str
    ) -> None:
        super().__init__(scope, construct_id)
        stack = cdk.Stack.of(self)
        group = scheduler.CfnScheduleGroup(self, "Group", name=f"{name_prefix}-off-hours")
        role = iam.Role(
            self,
            "Role",
            assumed_by=iam.ServicePrincipal(
                "scheduler.amazonaws.com", conditions={"StringEquals": {"aws:SourceAccount": stack.account}}
            ),
            description=f"EventBridge Scheduler: start and stop the {name_prefix} host outside its hours",
        )
        # The volumes use the AWS-managed aws/ebs key, whose key policy lets EC2 use it for any principal in the
        # account, so starting needs no KMS permission here (a customer-managed key would need kms:CreateGrant).
        role.add_to_policy(
            iam.PolicyStatement(
                sid="StartAndStopTheHost",
                actions=["ec2:StartInstances", "ec2:StopInstances"],
                resources=[stack.format_arn(service="ec2", resource="instance", resource_name=instance.instance_id)],
            )
        )
        for name, expression, action in SCHEDULES:
            scheduler.CfnSchedule(
                self,
                name.title().replace("-", ""),  # Stop, StopLate, Start
                name=name,
                group_name=group.ref,  # Ref of a schedule group is its name
                description=f"{action} the {name_prefix} host ({expression}, {time_zone})",
                schedule_expression=expression,
                schedule_expression_timezone=time_zone,
                flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(mode="OFF"),
                state="ENABLED",
                target=scheduler.CfnSchedule.TargetProperty(
                    arn=f"arn:aws:scheduler:::aws-sdk:ec2:{action}",
                    role_arn=role.role_arn,
                    input=stack.to_json_string({"InstanceIds": [instance.instance_id]}),
                    # A stop or start more than an hour late is dropped; the next schedule catches up.
                    retry_policy=scheduler.CfnSchedule.RetryPolicyProperty(
                        maximum_retry_attempts=RETRY_ATTEMPTS, maximum_event_age_in_seconds=3600
                    ),
                ),
            )
