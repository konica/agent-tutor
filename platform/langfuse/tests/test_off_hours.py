"""Off-hours: the host stops at 18:00 and 00:00 and starts at 07:00 (spec 2026-10-14 §4, ADR 0022)."""

import json
from typing import Any

import aws_cdk as cdk
import pytest
from aws_cdk import aws_ec2 as ec2
from aws_cdk.assertions import Template

from langfuse_platform.off_hours import OffHours

ACCOUNT = "123456789012"


@pytest.fixture(scope="module")
def t() -> Template:
    app = cdk.App()
    stack = cdk.Stack(app, "Test", env=cdk.Environment(account=ACCOUNT, region="us-east-1"))
    vpc = ec2.Vpc(
        stack,
        "Vpc",
        max_azs=1,
        nat_gateways=0,
        subnet_configuration=[ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC)],
    )
    instance = ec2.Instance(
        stack,
        "Instance",
        vpc=vpc,
        instance_type=ec2.InstanceType("t3.micro"),
        machine_image=ec2.MachineImage.latest_amazon_linux2023(),
    )
    OffHours(stack, "OffHours", instance=instance, name_prefix="test", time_zone="Asia/Ho_Chi_Minh")
    return Template.from_stack(stack)


def _instance_id(t: Template) -> str:
    (instance_id,) = t.find_resources("AWS::EC2::Instance")
    return instance_id


def _schedules(t: Template) -> dict[str, dict[str, Any]]:
    return {s["Properties"]["Name"]: s["Properties"] for s in t.find_resources("AWS::Scheduler::Schedule").values()}


def _scheduler_role(t: Template) -> tuple[str, dict[str, Any]]:
    ((role_id, role),) = (
        (rid, r)
        for rid, r in t.find_resources("AWS::IAM::Role").items()
        if "scheduler.amazonaws.com" in json.dumps(r["Properties"]["AssumeRolePolicyDocument"])
    )
    return role_id, role


def test_the_host_stops_at_18_and_00_and_starts_at_07(t: Template) -> None:
    assert {name: (s["ScheduleExpression"], s["Target"]["Arn"]) for name, s in _schedules(t).items()} == {
        "test-stop": ("cron(0 18 * * ? *)", "arn:aws:scheduler:::aws-sdk:ec2:stopInstances"),
        "test-stop-late": ("cron(0 0 * * ? *)", "arn:aws:scheduler:::aws-sdk:ec2:stopInstances"),
        "test-start": ("cron(0 7 * * ? *)", "arn:aws:scheduler:::aws-sdk:ec2:startInstances"),
    }


def test_schedule_names_carry_the_prefix_so_they_never_clash_with_another_stacks(t: Template) -> None:
    # CloudFormation identifies a schedule by its name alone, whatever its group: another stack in the account that
    # owns a schedule `start` makes a second `start` fail with "start already exists in stack ...".
    assert all(name.startswith("test-") for name in _schedules(t))


def test_schedules_run_on_time_in_the_time_zone_and_retry_twice(t: Template) -> None:
    for schedule in _schedules(t).values():
        assert schedule["ScheduleExpressionTimezone"] == "Asia/Ho_Chi_Minh"
        assert schedule["FlexibleTimeWindow"] == {"Mode": "OFF"}
        assert schedule["State"] == "ENABLED"
        assert schedule["Target"]["RetryPolicy"]["MaximumRetryAttempts"] == 2


def test_schedules_name_this_instance_and_live_in_the_hosts_group(t: Template) -> None:
    (group_id,) = t.find_resources("AWS::Scheduler::ScheduleGroup")
    t.has_resource_properties("AWS::Scheduler::ScheduleGroup", {"Name": "test-off-hours"})
    for schedule in _schedules(t).values():
        assert schedule["GroupName"] == {"Ref": group_id}
        target_input = json.dumps(schedule["Target"]["Input"])
        assert "InstanceIds" in target_input
        assert json.dumps({"Ref": _instance_id(t)}) in target_input


def test_only_this_accounts_scheduler_assumes_the_role(t: Template) -> None:
    _, role = _scheduler_role(t)
    (statement,) = role["Properties"]["AssumeRolePolicyDocument"]["Statement"]
    assert statement["Principal"] == {"Service": "scheduler.amazonaws.com"}
    assert statement["Condition"] == {"StringEquals": {"aws:SourceAccount": ACCOUNT}}


def test_the_role_only_starts_and_stops_this_instance(t: Template) -> None:
    role_id, _ = _scheduler_role(t)
    (policy,) = (
        p["Properties"]
        for p in t.find_resources("AWS::IAM::Policy").values()
        if p["Properties"]["Roles"] == [{"Ref": role_id}]
    )
    (granted,) = policy["PolicyDocument"]["Statement"]
    assert sorted(granted["Action"]) == ["ec2:StartInstances", "ec2:StopInstances"]
    resource = json.dumps(granted["Resource"])
    assert ":instance/" in resource and json.dumps({"Ref": _instance_id(t)}) in resource
    for schedule in _schedules(t).values():
        assert schedule["Target"]["RoleArn"] == {"Fn::GetAtt": [role_id, "Arn"]}


def test_no_alarm_and_no_queue(t: Template) -> None:
    t.resource_count_is("AWS::CloudWatch::Alarm", 0)
    t.resource_count_is("AWS::SQS::Queue", 0)
