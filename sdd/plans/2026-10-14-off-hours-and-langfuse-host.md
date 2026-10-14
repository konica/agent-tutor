# Off-hours hosts and a shared Langfuse host — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop both on-premise hosts 18:00–07:00 (Asia/Ho_Chi_Minh) with EventBridge Scheduler, remove the app host's CloudWatch alarms, and add a self-hosted Langfuse host in its own CDK project.

**Architecture:** An `OffHours` construct (one schedule group, three EventBridge Scheduler schedules that call `ec2:StopInstances`/`StartInstances` directly, and one narrowly scoped role) is added to the app's `HostStack`, which also loses its four alarms and moves its patch window to Sunday 07:20. A new uv/CDK project `platform/langfuse` defines `Langfuse-Host`: a t3.xlarge VM in its own VPC that runs Langfuse v4 (web, worker, ClickHouse, Postgres, Valkey, Caddy) with Docker Compose, deployed by an SSM document, with its own copy of `OffHours`.

**Tech Stack:** AWS CDK v2 (Python, `aws-cdk-lib` 2.272), EventBridge Scheduler (L1 `CfnSchedule`), EC2, EBS, DLM, S3, Secrets Manager, SSM, Docker Compose, Caddy, Langfuse 4.47.0, pytest with `aws_cdk.assertions`, GitHub Actions.

**Spec:** `sdd/specs/2026-10-14-off-hours-and-langfuse-host-design.md`

## Global Constraints

- Time zone for every schedule and window: `Asia/Ho_Chi_Minh` (the app time zone, `APP_TIME_ZONE` in `infra/smart_tutor_infra/stacks/config.py`).
- Schedules, exactly: `stop` = `cron(0 18 * * ? *)`, `stop-late` = `cron(0 0 * * ? *)`, `start` = `cron(0 7 * * ? *)`; flexible time window `OFF`; 2 retry attempts; targets `arn:aws:scheduler:::aws-sdk:ec2:stopInstances` / `...:startInstances` with input `{"InstanceIds": ["<id>"]}`.
- The scheduler role is assumed only by `scheduler.amazonaws.com` with `aws:SourceAccount` = the account and may only `ec2:StartInstances` and `ec2:StopInstances` on that one instance.
- **No CloudWatch alarm, no Route 53 health check, no dead-letter queue** in either project. The patch-failure email stays an EventBridge rule to SNS.
- Patch window on both hosts: `cron(20 7 ? * SUN *)` in the app time zone.
- Postgres (both hosts) and ClickHouse: `stop_grace_period: 60s`. Both hosts' `deploy.sh` write a Docker drop-in `TimeoutStopSec=120`.
- The Langfuse project never mentions Smart Tutor (no `smart-tutor` in its template or files) and never references `infra/` stacks, parameters, or secrets. Names: resources `langfuse`, stack `Langfuse-Host`, SSM `/langfuse/host/*`, secrets `langfuse/*`.
- Langfuse images, pinned: `langfuse/langfuse:4.47.0`, `langfuse/langfuse-worker:4.47.0`, `clickhouse/clickhouse-server:25.12.11.4`, `postgres:17.11-alpine`, `valkey/valkey:8.1.10-alpine`, `caddy:2.11.4-alpine` (all on Docker Hub; each at least two weeks old on 2026-10-14).
- Langfuse settings: `AUTH_DISABLE_SIGNUP` true unless SSM `/langfuse/host/allow-signup` is `true`; `TELEMETRY_ENABLED=false`; `CLICKHOUSE_CLUSTER_ENABLED=false`; no `LANGFUSE_S3_*_ACCESS_KEY_ID`/`SECRET_ACCESS_KEY` (Langfuse's `S3StorageService` falls back to the default AWS credential chain, i.e. the instance role).
- Secrets never reach a command line, the template, outputs, user data, or logs (`deploy.sh` renders them into a root-only env file; never `set -x`).
- Files the VMs run keep LF line endings (`.gitattributes`).
- Backend is untouched. Checks per PR: `cd infra && uv run pytest` (PR 1), plus `cd platform/langfuse && uv run pytest` (PR 2).
- Commits: imperative subject, a body that says why, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Windows: `make` may be missing; run the Makefile line directly. Use PowerShell for commands containing `--extra eval`.

## Review Focus

1. **A stop kills Postgres or ClickHouse mid-shutdown.** `StopInstances` shuts the OS down; Docker must get longer than the containers' 60 s grace. Expect `deploy.sh` on both hosts to write `TimeoutStopSec=120` for `docker.service` (tests in Tasks 3 and 8).
2. **A host started by hand at any hour comes up without a deploy.** Every long-running service has `restart: unless-stopped` and Docker waits for `/data`. Expect a test over every Compose service on both hosts (Tasks 3 and 8).
3. **Langfuse's encryption key changes on a redeploy**, making stored LLM-connection secrets unreadable. Expect `deploy.sh` to derive it deterministically from the `encryption-seed` secret (SHA-256, 64 hex characters) and never generate one (test in Task 8).
4. **Caddy can't reach Langfuse web** because Next.js binds to the container's hostname. Expect `HOSTNAME: 0.0.0.0` on `langfuse-web` (test in Task 8).
5. **Sign-up stays open, or can never be opened.** Expect `AUTH_DISABLE_SIGNUP` to be `true` unless `/langfuse/host/allow-signup` is exactly `true`, and the stack to create that parameter as `false` (tests in Tasks 7 and 8).

---

## PR 1: off-hours and no alarms on the app host (branch `off-hours-langfuse-host`)

The spec is already committed on this branch.

### Task 1: The `OffHours` construct

**Files:**
- Create: `infra/smart_tutor_infra/off_hours.py`
- Test: `infra/tests/test_off_hours.py`

**Interfaces:**
- Produces: `OffHours(scope: Construct, construct_id: str, *, instance: ec2.Instance, name_prefix: str, time_zone: str)`; module constants `SCHEDULES: tuple[tuple[str, str, str], ...]` and `RETRY_ATTEMPTS = 2`. Task 2 uses it in `HostStack`; Task 6 copies the file.

- [ ] **Step 1: Write the failing test** `infra/tests/test_off_hours.py`:

```python
"""Off-hours: the host stops at 18:00 and 00:00 and starts at 07:00 (spec 2026-10-14 §4, ADR 0022)."""

import json
from typing import Any

import aws_cdk as cdk
import pytest
from aws_cdk import aws_ec2 as ec2
from aws_cdk.assertions import Template

from smart_tutor_infra.off_hours import OffHours

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
        "stop": ("cron(0 18 * * ? *)", "arn:aws:scheduler:::aws-sdk:ec2:stopInstances"),
        "stop-late": ("cron(0 0 * * ? *)", "arn:aws:scheduler:::aws-sdk:ec2:stopInstances"),
        "start": ("cron(0 7 * * ? *)", "arn:aws:scheduler:::aws-sdk:ec2:startInstances"),
    }


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
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd infra && uv run pytest tests/test_off_hours.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'smart_tutor_infra.off_hours'`.

- [ ] **Step 3: Write the construct** `infra/smart_tutor_infra/off_hours.py`:

```python
"""Off-hours for one EC2 host (spec sdd/specs/2026-10-14-off-hours-and-langfuse-host-design.md §4, ADR 0022).

EventBridge Scheduler stops the instance at 18:00 and again at 00:00 (a host someone started by hand in the evening)
and starts it at 07:00, in the given time zone, by calling the EC2 API directly (universal targets): no Lambda, no
alarm, no dead-letter queue. Stopping a stopped instance, or starting a running one, changes nothing, so a person may
start the host at any hour; it then runs until the next stop.

platform/langfuse keeps its own copy of this file, so that project can move to a repository of its own.
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
                    retry_policy=scheduler.CfnSchedule.RetryPolicyProperty(
                        maximum_retry_attempts=RETRY_ATTEMPTS, maximum_event_age_in_seconds=3600
                    ),
                ),
            )
```

- [ ] **Step 4: Run the test to see it pass**

Run: `cd infra && uv run pytest tests/test_off_hours.py -q`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add infra/smart_tutor_infra/off_hours.py infra/tests/test_off_hours.py
git commit -m "Add an OffHours construct that stops a host 18:00-07:00" -m "EventBridge Scheduler calls the EC2 API directly, so the schedule needs no Lambda, alarm, or queue; the role may only start and stop its one instance. The 00:00 stop catches a host someone started by hand in the evening." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: The app host stops off-hours and loses its alarms

**Files:**
- Modify: `infra/smart_tutor_infra/stacks/host.py`
- Test: `infra/tests/test_host.py`

**Interfaces:**
- Consumes: `OffHours` from Task 1; `APP_TIME_ZONE` (already imported in `host.py`).

- [ ] **Step 1: Change the tests first** in `infra/tests/test_host.py`:
  1. In `test_instance_role_pulls_images_reads_its_own_settings_and_secrets_and_is_managed_by_ssm`, change the `"*"` list to `["EcrLogin", "PublishAgentMetrics"]` (remove `"PublishJobMetrics"`) and its comment to `# Only the ECR login and the agent's metrics, which have no resource, may use "*".`
  2. Delete `test_instance_role_publishes_metrics_only_to_its_own_namespace`.
  3. Delete both `_alarm` helpers and these tests: `test_a_failed_database_backup_raises_an_alarm_that_emails_the_alert_addresses`, `test_a_failed_snapshot_raises_an_alarm`, `test_system_status_check_alarm_recovers_the_instance_and_emails`, `test_uptime_check_probes_the_api_health_route_over_https_on_the_domain`, `test_uptime_check_follows_the_sslip_io_fallback`, `test_uptime_alarm_emails_when_the_check_fails_and_when_it_recovers`.
  4. Rename `test_alarms_email_the_budget_recipients` to `test_alert_topic_emails_the_budget_recipients` (body unchanged) and change the section comment `# --- monitoring and patching (#152)---…` to `# --- off-hours, alerts, and patching (#152, ADR 0022) ---…` (keep the dash padding).
  5. In `test_weekly_maintenance_window_patches_the_host_then_checks_the_services`, change `"cron(0 4 ? * SUN *)"` to `"cron(20 7 ? * SUN *)"`.
  6. Add, below `test_alert_topic_emails_the_budget_recipients`:

```python
def test_the_host_stops_at_18_and_00_and_starts_at_07_in_the_app_time_zone(t: Template) -> None:
    (instance_id,) = t.find_resources("AWS::EC2::Instance")
    t.has_resource_properties("AWS::Scheduler::ScheduleGroup", {"Name": "smart-tutor-on-premise-prod-off-hours"})
    schedules = {s["Properties"]["Name"]: s["Properties"] for s in t.find_resources("AWS::Scheduler::Schedule").values()}
    assert {name: s["ScheduleExpression"] for name, s in schedules.items()} == {
        "stop": "cron(0 18 * * ? *)",
        "stop-late": "cron(0 0 * * ? *)",
        "start": "cron(0 7 * * ? *)",
    }
    for schedule in schedules.values():
        assert schedule["ScheduleExpressionTimezone"] == "Asia/Ho_Chi_Minh"
        assert json.dumps({"Ref": instance_id}) in json.dumps(schedule["Target"]["Input"])


def test_no_cloudwatch_alarm_or_route53_health_check(t: Template) -> None:
    # Alarms cost money and the uptime alarm would email at every stop and start (ADR 0022). EC2's default automatic
    # recovery still moves the instance off failed hardware.
    t.resource_count_is("AWS::CloudWatch::Alarm", 0)
    t.resource_count_is("AWS::Route53::HealthCheck", 0)
```

- [ ] **Step 2: Run them to see the new ones fail**

Run: `cd infra && uv run pytest tests/test_host.py -q`
Expected: FAIL in `test_the_host_stops_at_18_...` (no schedule group), `test_no_cloudwatch_alarm_or_route53_health_check` (4 alarms), the `"*"` list test (extra `PublishJobMetrics`), and the maintenance window test (`cron(0 4 …)`).

- [ ] **Step 3: Change `infra/smart_tutor_infra/stacks/host.py`**
  1. In the module docstring, replace the two bullets `- Monitoring (#152): …` and `- Patching (#152): …` with:

```
- Off-hours (ADR 0022): EventBridge Scheduler stops the instance at 18:00 and 00:00 and starts it at 07:00 in the app
  time zone (OffHours). A person may start it at any hour; Docker brings every service back.
- No CloudWatch alarms (ADR 0022). The topic `<prefix>-alerts` emails the budget recipients when the weekly patching
  fails. EC2's default automatic recovery moves the instance off failed hardware. Runbook:
  docs/runbooks/on-premise-monitoring.md.
- Patching (#152): a weekly maintenance window installs security patches (rebooting if needed), then runs
  `deploy/on-premise/ensure-healthy.sh` so every service is back and healthy.
```

  2. Imports: delete `from aws_cdk import aws_cloudwatch as cloudwatch`, `from aws_cdk import aws_cloudwatch_actions as cloudwatch_actions`, and `from aws_cdk import aws_route53 as route53`. Add `from smart_tutor_infra.off_hours import OffHours` after `from smart_tutor_infra.names import ModeNames`.
  3. Delete the `HEALTH_PATH` constant and its comment line. Replace the `PATCH_SCHEDULE` comment and value with:

```python
# Weekly patching: Sunday 07:20 in the app time zone, twenty minutes after the off-hours start (07:00), so Docker has the
# services up; it reboots only when a patch needs it.
PATCH_SCHEDULE = "cron(20 7 ? * SUN *)"
```

  4. Delete the constants `JOB_METRICS_NAMESPACE` and `BACKUP_JOB` and their comment lines.
  5. Delete the `role.add_to_policy(... sid="PublishJobMetrics" ...)` block.
  6. After `cdk.Tags.of(instance).add("PatchGroup", names.resource_prefix)` add:

```python
        OffHours(self, "OffHours", instance=instance, name_prefix=names.resource_prefix, time_zone=APP_TIME_ZONE)
```

  7. Replace `_alarms(self, names, instance, domain, alerts)` with nothing (delete the line) and keep `alerts = self._backups(names, alert_emails)` and `_patching(...)`.
  8. In `_backups`: change the docstring to `"""Daily snapshots of the data volume (#151). Returns the alerts topic, which the patching rule (#152) emails."""`; change `policy = dlm.CfnLifecyclePolicy(` to `dlm.CfnLifecyclePolicy(`; delete the comment `# Monitoring (#152) adds its alarms…` and replace it with `# The patching rule emails this topic. Each address confirms its subscription once.`; delete `alarm_action = …` and the whole `for construct_name, description, metric in (…): … alarm.add_alarm_action(alarm_action)` loop, leaving `return topic`.
  9. Delete the function `_alarms` entirely.

- [ ] **Step 4: Run the infra tests**

Run: `cd infra && uv run pytest -q`
Expected: all pass. If a test elsewhere (for example `tests/test_synth.py` or `tests/test_mode_isolation.py`) asserted one of the removed resources, change it to assert the resource is absent, never re-add the resource.

- [ ] **Step 5: Commit**

```bash
git add infra/smart_tutor_infra/stacks/host.py infra/tests/test_host.py
git commit -m "Stop the on-premise host 18:00-07:00 and drop its CloudWatch alarms" -m "The product owner wants the host off outside 07:00-18:00 (GMT+7) to save cost, and no CloudWatch alarms: they cost money and the uptime alarm would email at every stop and start. Patching moves to Sunday 07:20, after the start." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: VM files: no failure metric, clean shutdowns

**Files:**
- Delete: `deploy/on-premise/report-failure.sh`, `deploy/on-premise/systemd/smart-tutor-job-failed@.service`
- Modify: `deploy/on-premise/systemd/smart-tutor-backup.service`, `deploy/on-premise/backup.sh` (header comment), `deploy/on-premise/ensure-healthy.sh` (header comment), `deploy/on-premise/deploy.sh`, `deploy/on-premise/compose.yaml`
- Test: `infra/tests/test_host.py`

- [ ] **Step 1: Change the tests first** in `infra/tests/test_host.py`:
  1. In `SCRIPTS`, change `("backup.sh", "restore.sh", "report-failure.sh")` to `("backup.sh", "restore.sh")`.
  2. Delete `test_a_failed_job_publishes_the_metric_the_alarm_watches`.
  3. Replace `test_backup_service_runs_the_script_and_reports_a_failure` with:

```python
def test_backup_service_runs_the_script_and_leaves_failures_in_its_journal() -> None:
    service = _unit("smart-tutor-backup.service")
    assert service["Service"]["Type"] == "oneshot"
    assert service["Service"]["ExecStart"] == "/usr/bin/bash /opt/smart-tutor/on-premise/backup.sh"
    assert "OnFailure" not in service["Unit"]  # no CloudWatch metric or alarm (ADR 0022)
    assert "docker.service" in service["Unit"]["Requires"]
    assert not (ON_PREMISE_DIR / "report-failure.sh").exists()
    assert not (SYSTEMD_DIR / "smart-tutor-job-failed@.service").exists()
```

  4. Add:

```python
def test_deploy_removes_the_retired_failure_unit_from_the_vm() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    removal = "rm -f /etc/systemd/system/smart-tutor-job-failed@.service"
    assert removal in script
    assert script.index(removal) < script.index('install -m 644 "$here"/systemd/* /etc/systemd/system/')


def test_deploy_gives_docker_time_to_stop_the_containers_when_the_instance_stops() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "/etc/systemd/system/docker.service.d/stop-timeout.conf" in script
    assert "TimeoutStopSec=120" in script  # longer than Postgres's 60 s grace


def test_postgres_shuts_down_cleanly_when_the_instance_stops(compose: dict[str, Any]) -> None:
    assert compose["services"]["postgres"]["stop_grace_period"] == "60s"


def test_every_long_running_service_comes_back_after_a_boot(compose: dict[str, Any]) -> None:
    # A scheduled 07:00 start or a person's start at any hour brings everything back without a deploy.
    jobs = {name for name, s in compose["services"].items() if "jobs" in s.get("profiles", [])} | {"migrate"}
    for name, service in compose["services"].items():
        if name not in jobs:
            assert service.get("restart") == "unless-stopped", name
```

Before adding the last test, read `compose.yaml`: if one-off services other than `migrate` and the `jobs` profile exist (for example `pg-dump`), add them to `jobs` by the same rule (services that run and exit). Keep the rule general, not a list of the long-running ones.

- [ ] **Step 2: Run them to see them fail**

Run: `cd infra && uv run pytest tests/test_host.py -q`
Expected: FAIL in the four new or changed tests.

- [ ] **Step 3: Change the files**
  1. `git rm deploy/on-premise/report-failure.sh deploy/on-premise/systemd/smart-tutor-job-failed@.service`
  2. `deploy/on-premise/systemd/smart-tutor-backup.service`: delete the line `OnFailure=smart-tutor-job-failed@%N.service`, and change the first comment line to `# Nightly pg_dump of the app and Keycloak databases to S3 (#151); smart-tutor-backup.timer starts it. A failure is in its journal.`
  3. `deploy/on-premise/backup.sh`: replace the two lines `# The bucket expires backups/ after 30 days. A failure exits non-zero, and systemd's OnFailure reports it to CloudWatch` / `# (report-failure.sh), which raises the backup alarm. It prints no secret.` with `# The bucket expires backups/ after 30 days. A failure exits non-zero and is in journalctl -u smart-tutor-backup (no alarm,` / `# ADR 0022). It prints no secret.`
  4. `deploy/on-premise/ensure-healthy.sh`: in the header, replace `fails the maintenance window and emails the alarm recipients.` with `fails the maintenance window and emails the alert addresses.`
  5. `deploy/on-premise/deploy.sh`:
     - In the header list item 3, after `Installs and enables the scheduled jobs' systemd units (the nightly backup, #151).` add a line `#    Gives Docker two minutes to stop the containers when the instance stops (off-hours, ADR 0022).`
     - Directly before `echo "Pulling $tag from $registry/$repository_prefix"` add:

```bash
# Off-hours (ADR 0022): EC2 stops the instance by shutting the OS down, and systemd stops Docker. Postgres needs up to
# 60 s (stop_grace_period) to shut down cleanly, so Docker gets longer than systemd's default.
mkdir -p /etc/systemd/system/docker.service.d
printf '[Service]\nTimeoutStopSec=120\n' > /etc/systemd/system/docker.service.d/stop-timeout.conf
systemctl daemon-reload
```

     - Directly before `install -m 644 "$here"/systemd/* /etc/systemd/system/` add:

```bash
# Retired with the CloudWatch alarms (ADR 0022); a VM deployed before keeps the file until this removes it.
rm -f /etc/systemd/system/smart-tutor-job-failed@.service
```

  6. `deploy/on-premise/compose.yaml`, service `postgres`: after `restart: unless-stopped` add `    stop_grace_period: 60s  # a clean shutdown when the instance stops (off-hours, ADR 0022)`.

- [ ] **Step 4: Run the infra tests**

Run: `cd infra && uv run pytest -q`
Expected: all pass (including `test_scripts_parse` and `test_files_the_vm_runs_keep_lf_line_endings`).

- [ ] **Step 5: Commit**

```bash
git add -A deploy/on-premise infra/tests/test_host.py
git commit -m "Retire the backup failure metric and let Postgres stop cleanly" -m "With no CloudWatch alarms the JobFailed metric has no reader, so the failure unit and script go; a failed dump stays in the journal. A daily stop shuts the OS down, so Postgres gets 60 s and Docker 120 s to stop." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4: PRD, ADR 0022, runbooks, and PR 1

**Files:**
- Modify: `sdd/prd.md`, `sdd/adr/README.md`, `docs/runbooks/on-premise-monitoring.md`, `docs/runbooks/on-premise-backups.md`, `docs/runbooks/on-premise-deploy.md`, `AGENTS.md`
- Create: `sdd/adr/0022-on-premise-off-hours-and-no-alarms.md`

- [ ] **Step 1: PRD (v2.62 → v2.63)** in `sdd/prd.md`:
  1. Status line: `Draft v2.62` → `Draft v2.63`.
  2. Insert directly above the line starting `| **Changes from v2.61** |`:

```
| **Changes from v2.62** | On-premise hours (ADR 0022, §9.10, §9.12, Appendix A): the on-premise product runs **07:00–18:00 Asia/Ho_Chi_Minh, every day**. EventBridge Scheduler stops the host at 18:00 and 00:00 and starts it at 07:00; outside those hours the site doesn't answer. An operator may start it at any hour. The recovery alarm, the uptime check, and the backup and snapshot alarms are removed (no CloudWatch alarms); EC2's default automatic recovery stays, and a failed patching window still emails. Weekly patching moves to Sunday 07:20. |
```

  3. §9.10, the row starting `| **One VM is a single point of failure (on-premise).**`: replace its mitigation cell text `Accepted for the pilot: Docker health checks and restart policies, an EC2 status-check recovery alarm, an uptime check on `/api/healthz`.` with `Accepted for the pilot: Docker health checks and restart policies, and EC2's default automatic recovery. The product is also off 18:00–07:00 by design (ADR 0022), and no alarm tells anyone it is down.` (keep the rest of the cell).
  4. §9.12, on-premise bullet: replace `(the EC2 instance with its Elastic IP, data volume, IAM role, status-check recovery alarm, and snapshot policy)` with `(the EC2 instance with its Elastic IP, data volume, IAM role, snapshot policy, and off-hours schedule)`; replace `A failed snapshot or dump emails the alert addresses.` with `A failed dump is in the VM's journal; there is no backup alarm (ADR 0022).`; replace the Monitoring sub-bullet with `  - Hours and monitoring: the host runs 07:00–18:00 Asia/Ho_Chi_Minh and is stopped otherwise (ADR 0022); Docker health checks and restart policies, log rotation, EC2's default automatic recovery, budgets, and weekly SSM patching (Sunday 07:20; a failed window emails). No CloudWatch alarms.`
  5. Appendix A, Host stack line: replace `a status-check recovery alarm, and daily EBS snapshots kept 7 days.` with `daily EBS snapshots kept 7 days, and an EventBridge Scheduler group that stops it at 18:00 and 00:00 and starts it at 07:00 (Asia/Ho_Chi_Minh).`; in the S3 line, delete `; the uptime check on `/api/healthz``.

- [ ] **Step 2: ADR 0022** `sdd/adr/0022-on-premise-off-hours-and-no-alarms.md`:

```markdown
# 0022. On-premise hosts run 07:00–18:00 and carry no CloudWatch alarms

- Status: accepted
- Date: 2026-10-14
- Supersedes: #152's recovery alarm and uptime check, and #151's backup and snapshot alarms

## Context

The on-premise host runs around the clock, but learners use the pilot during the day. The product owner wants it off
00:00–07:00 and 18:00–24:00 in Asia/Ho_Chi_Minh (GMT+7), every day, to save cost, and no CloudWatch alarms: they cost
money, and with a daily stop the uptime alarm would email twice a day. The same applies to the shared Langfuse host
(ADR 0021). Spec: `sdd/specs/2026-10-14-off-hours-and-langfuse-host-design.md`.

## Decision

- **Schedule.** Each host has an EventBridge Scheduler group `<prefix>-off-hours` with three schedules in
  Asia/Ho_Chi_Minh: `stop` at 18:00, `stop-late` at 00:00, `start` at 07:00. They call `ec2:StopInstances` and
  `ec2:StartInstances` directly (universal targets), retry twice, and use a role that may only start and stop that
  instance. No Lambda, no dead-letter queue.
- **Manual starts.** Anyone with EC2 access may start a host at any hour; it boots as at 07:00 (the data volume
  mounts, Docker starts every service, the Elastic IP and certificates stay). `stop-late` stops a host started in the
  evening; an operator who needs it overnight disables `stop-late` and enables it again afterwards.
- **Clean stops.** A stop shuts the OS down. Postgres (and ClickHouse on the Langfuse host) get a 60 s grace period, and
  Docker's systemd unit gets 120 s to stop.
- **No CloudWatch alarms.** The recovery alarm, uptime check, and backup and snapshot alarms are removed, with the
  `JobFailed` metric that fed one of them. EC2's default automatic recovery still moves an instance off failed
  hardware. The weekly patching window moves to Sunday 07:20 and still emails its alert topic when it fails (an
  EventBridge rule, not an alarm).

## Consequences

- Learners can't use the product 18:00–07:00; the site doesn't answer (the DuckDNS name points at the host). The PRD
  states the hours.
- Nobody is told when the site is down during the day, when a nightly dump fails (`journalctl -u smart-tutor-backup`),
  or when a snapshot fails. The runbooks list the checks to run by hand.
- A deploy still running at 18:00 is cut off; deploy before 17:30 or start the host first.
- The nightly dump (03:00) runs at the next boot (`Persistent=true`); the 02:00 snapshot works on a stopped instance.
- Compute cost falls to about 46% of always-on. The two Elastic IPs are charged whether the hosts run or not.
```

- [ ] **Step 3: ADR index** `sdd/adr/README.md`: add after the 0020 row:

```
| [0022](0022-on-premise-off-hours-and-no-alarms.md) | On-premise hosts run 07:00–18:00 Asia/Ho_Chi_Minh (EventBridge Scheduler stops them at 18:00 and 00:00, starts at 07:00; anyone may start one by hand) and carry no CloudWatch alarms (supersedes #151's and #152's alarms) |
```

(0021 is added in PR 2; numbering leaves room for it.)

- [ ] **Step 4: `docs/runbooks/on-premise-monitoring.md`**
  1. Title → `# On-premise hours, monitoring, and patching (#152, ADR 0022)`. First paragraph → `The host runs 07:00–18:00 Asia/Ho_Chi_Minh and patches itself weekly (PRD §9.12, ADR 0012, ADR 0022). There are no CloudWatch alarms: nobody is emailed when the product is down, so check it by hand when in doubt. All of it is in the Host stack (`infra/smart_tutor_infra/stacks/host.py`) and deploys with it (`on-premise-deploy.md` §2). For deploys, the VM's layout, and Session Manager, see `on-premise-deploy.md`.`
  2. **Who gets the emails**: replace the first paragraph with `The SNS topic **`smart-tutor-on-premise-prod-alerts`** emails the budget's recipients (`smart-tutor:budget-alert-emails` in `infra/cdk.json`) when the weekly patching fails. It is the only email the Host stack sends.` Keep the confirmation instructions.
  3. Replace the section **The alarms** (with its subsections **Recovery alarm** and **Uptime alarm**) by:

```markdown
## Emails

| Email | What happened | Section |
|---|---|---|
| "The patching window smart-tutor-on-premise-prod-patching ended FAILED" (or `TIMED_OUT`) | The weekly patching, or the health check after it, failed. | [Patching](#patching-failed) |
| AWS Budgets: `smart-tutor-on-premise-prod-monthly` | Actual spend passed 80% of the monthly budget, or the forecast passed 100%. | [Budget](#budget-alert) |

## Hours (ADR 0022)

| Local time (Asia/Ho_Chi_Minh) | Schedule | What it does |
|---|---|---|
| 18:00 | `stop` | Stops the instance |
| 00:00 | `stop-late` | Stops it again, in case someone started it in the evening |
| 07:00 | `start` | Starts it; Docker brings every service back within a few minutes |

The schedules are in the group `smart-tutor-on-premise-prod-off-hours`. A stop shuts the OS down: Postgres gets 60 s and Docker 120 s to stop. Outside the hours the site doesn't answer.

**Start the host by hand** (any hour; it runs until the next `stop` or `stop-late`):

```powershell
aws ec2 start-instances --instance-ids $InstanceId
aws ec2 wait instance-running --instance-ids $InstanceId
# A few minutes later:
Invoke-WebRequest "$Url/api/healthz" -UseBasicParsing | Select-Object StatusCode
```

Nothing else is needed: the data volume mounts, Docker starts every service, and the Elastic IP, DuckDNS name, and certificates stay. Uploads queued overnight are processed, and a nightly dump that was missed runs.

**Keep it up past midnight:** disable `stop-late`, then enable it again the next morning. `update-schedule` replaces the whole schedule, so read it first and send it back with the new state:

```powershell
$Group = "smart-tutor-on-premise-prod-off-hours"
$s = aws scheduler get-schedule --group-name $Group --name stop-late | ConvertFrom-Json
$s.Target | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8NoBOM stop-late-target.json  # a file, not inline JSON
aws scheduler update-schedule --group-name $Group --name stop-late --state DISABLED `
    --schedule-expression $s.ScheduleExpression --schedule-expression-timezone $s.ScheduleExpressionTimezone `
    --flexible-time-window Mode=OFF --target file://stop-late-target.json
# Next morning: the same command with --state ENABLED
```

**Stop it now:** `aws ec2 stop-instances --instance-ids $InstanceId`.

**Did a schedule run?** The instance's state history shows each stop and start: `aws ec2 describe-instances --instance-ids $InstanceId --query "Reservations[0].Instances[0].[State.Name, StateTransitionReason]"`. In CloudWatch, the free `AWS/Scheduler` metrics `InvocationAttemptCount` and `TargetErrorCount` (dimension `ScheduleGroup`) show attempts and failures.

**Is the product up?** No alarm watches it. Open `$Url`, or `Invoke-WebRequest "$Url/api/healthz"`. If the host is running but the site isn't, [bring the services back](#bring-the-services-back). If AWS reports a hardware problem, EC2's default automatic recovery moves the instance to healthy hardware without an email; the instance keeps its id, address, and volumes.
```

  4. **Patching failed**, step 2: delete the sentence `The uptime alarm fires too if the API is down.`
  5. **Weekly patching** table: `When` → `Every **Sunday at 07:20 Asia/Ho_Chi_Minh**, twenty minutes after the 07:00 start, for at most 3 hours; no task starts in the last hour`; `On failure` → `An email to the alert topic (EventBridge rule on the window's FAILED or TIMED_OUT state)`. Replace `A reboot takes the product down for a few minutes, which the uptime alarm tolerates.` with `A reboot takes the product down for a few minutes.`
  6. Delete the section **Test the alarms**.

- [ ] **Step 5: `docs/runbooks/on-premise-backups.md`**, section **Alerts**: replace the section body (the confirmation paragraph, the alarm table, and the paragraph after it) with:

```markdown
There is no backup alarm (ADR 0022). Check the backups by hand (next section) after a deploy, a restore, or anything unusual. A failed dump is in the VM's journal: `journalctl -u smart-tutor-backup -n 100`. A failed snapshot shows in **EC2 → Lifecycle Manager → the policy → Monitoring**. The host is off 18:00–07:00, so the 03:00 dump runs at the 07:00 start (`Persistent=true`); the 02:00 snapshot works on the stopped instance.
```

  In **Add a scheduled job**: in step 2, delete the `OnFailure=smart-tutor-job-failed@%N.service` line from the example unit and change `` `OnFailure=` reports a failure, and `%N` is the unit's name without `.service`: `` to `A failure stays in the unit's journal:`; delete step 4 (**Alarm**) and renumber **Deploy** to 4. Add to its **Keep in mind** list: `- The host is off 18:00–07:00 (ADR 0022). Give the timer `Persistent=true` so a run missed while it was off happens at the next start.`

- [ ] **Step 6: `docs/runbooks/on-premise-deploy.md`**
  1. In section **4. Deploy an image tag by hand**, add at its start: `The host is off 18:00–07:00 (ADR 0022). Deploy before 17:30, or start the host first (`on-premise-monitoring.md`, Hours): a deploy running at 18:00 is cut off, and the next deploy starts it again from the top.` Add the same sentence under **3. Deploy on merge (#150)**, worded for merges: `A merge after 17:30 deploys only if the host is running; start it first, or re-run the deploy the next morning.`
  2. In the teardown table, `Deleted | Host: …`, replace `the alarms and alert topic, the uptime check, the patching window` with `the alert topic, the off-hours schedules, the patching window`.

- [ ] **Step 7: `AGENTS.md`**: `sdd/prd.md` (v2.62) → (v2.63); `sdd/adr/` (0001–0020) → (0001–0022).

- [ ] **Step 8: Run all checks**

Run: `cd infra && uv run pytest -q` and `helm lint deploy/helm/smart-tutor`
Expected: all pass; `1 chart(s) linted, 0 chart(s) failed`.

- [ ] **Step 9: Commit, push, and open PR 1**

```bash
git add sdd/prd.md sdd/adr docs/runbooks AGENTS.md
git commit -m "Document the on-premise hours and the removed alarms (ADR 0022)" -m "The PRD, ADR 0022, and runbooks say the product runs 07:00-18:00 Asia/Ho_Chi_Minh, how to start the host by hand or keep it up overnight, and how to check the product and backups without alarms." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
gh pr create --title "Stop the on-premise host 18:00-07:00 and drop its CloudWatch alarms" --body-file <body>
```

The PR body lists: the spec and plan, the product owner's decisions (hours, no alarms, separate Langfuse project), what changed, the by-hand checks of Task 5 as an unchecked list, the cost note (spec §9; the $20 budget is the product owner's to set), and ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

### Task 5: Deploy PR 1 and check by hand (operator, AWS)

Needs AWS credentials for the account; an agent may run these when the person has them configured, otherwise it hands them over.

- [ ] **Step 1:** `cd infra && npx aws-cdk@latest diff SmartTutor-OnPremise-prod-Host -c smart-tutor:mode=on-premise`. Expected: adds a schedule group, three schedules, a role and policy; removes four alarms and a health check; changes the maintenance window's schedule and the instance role's policy. **No replacement of `AWS::EC2::Instance`** (the user data is unchanged). Stop and report if the instance would be replaced.
- [ ] **Step 2:** Deploy (`npx aws-cdk@latest deploy SmartTutor-OnPremise-prod-Host -c smart-tutor:mode=on-premise`), then redeploy the current tag (`on-premise-deploy.md` §4) so the VM gets the new `deploy.sh` (Docker stop timeout, retired unit removed).
- [ ] **Step 3:** After the next 18:00, `aws ec2 describe-instances` shows `stopped` with a `User initiated` reason; after 07:00 it is `running` and `/api/healthz` answers 200 within 5 minutes.
- [ ] **Step 4:** Start the host by hand in the evening; `/api/healthz` answers 200 within 5 minutes; at 00:00 it is stopped.
- [ ] **Step 5:** Record the results in the PR, then merge it (squash) once CI is green and the person approves.

---

## PR 2: the shared Langfuse host (branch `langfuse-host`)

Start from `main` after PR 1 merges. If PR 1 hasn't merged, branch from `off-hours-langfuse-host` and follow AGENTS.md's stacked-PR rule.

### Task 6: The `platform/langfuse` CDK project and its `OffHours` copy

**Files:**
- Create: `platform/langfuse/pyproject.toml`, `platform/langfuse/cdk.json`, `platform/langfuse/app.py`, `platform/langfuse/README.md`, `platform/langfuse/langfuse_platform/__init__.py`, `platform/langfuse/langfuse_platform/off_hours.py`, `platform/langfuse/tests/__init__.py`, `platform/langfuse/tests/test_off_hours.py`, `platform/langfuse/uv.lock` (generated)
- Modify: `.github/workflows/ci.yml`, `infra/tests/test_workflows.py`, `.gitattributes`

**Interfaces:**
- Produces: package `langfuse_platform` with `off_hours.OffHours` (same signature as Task 1). Task 7 adds `host_stack.py` and `app.build_app`.

- [ ] **Step 1: Project files.**

`platform/langfuse/pyproject.toml`:

```toml
[project]
name = "langfuse-platform"
version = "0.1.0"
description = "AWS CDK app for a shared, self-hosted Langfuse host (us-east-1)"
requires-python = ">=3.12,<3.14"
dependencies = [
    "aws-cdk-lib>=2.200",
    "constructs>=10.4",
]

[dependency-groups]
dev = ["pytest>=8.4", "pyyaml>=6"]

[tool.uv]
package = false

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

`platform/langfuse/cdk.json`:

```json
{
  "app": "uv run python app.py",
  "context": {
    "langfuse:region": "us-east-1",
    "langfuse:instance-type": "t3.xlarge",
    "langfuse:domain": "",
    "langfuse:admin-email": "dtrungthao@gmail.com",
    "langfuse:alert-emails": ["dtrungthao@gmail.com"],
    "langfuse:data-snapshot-id": ""
  }
}
```

`platform/langfuse/app.py` (Task 7 adds `build_app`; until then this file imports nothing from the package):

```python
"""CDK entry point for the shared Langfuse host (spec sdd/specs/2026-10-14-off-hours-and-langfuse-host-design.md §6)."""

import aws_cdk as cdk

app = cdk.App()
app.synth()
```

`platform/langfuse/langfuse_platform/__init__.py` and `platform/langfuse/tests/__init__.py`: empty.

`platform/langfuse/README.md`:

```markdown
# Langfuse host

A self-hosted Langfuse v4 on one EC2 VM (Docker Compose behind Caddy), shared by any app that sends it traces, scores,
and datasets. Its own CDK project, so it deploys and is destroyed apart from any app (ADR 0021); it runs 07:00–18:00
Asia/Ho_Chi_Minh (ADR 0022).

| Path | What |
|---|---|
| `langfuse_platform/` | The stack `Langfuse-Host` and the `OffHours` construct |
| `deploy/` | What the VM runs: `compose.yaml`, `Caddyfile`, `deploy.sh`, `ensure-healthy.sh` |
| `tests/` | `uv run pytest` |

Runbook: `docs/runbooks/langfuse-host.md`.
```

- [ ] **Step 2: Copy the construct.** Copy `infra/smart_tutor_infra/off_hours.py` to `platform/langfuse/langfuse_platform/off_hours.py` and change only the docstring's last paragraph to: `infra/smart_tutor_infra/off_hours.py keeps its own copy for the Smart Tutor host; change both when the schedule's shape changes.`

- [ ] **Step 3: Copy the test.** Copy `infra/tests/test_off_hours.py` to `platform/langfuse/tests/test_off_hours.py`, changing the import to `from langfuse_platform.off_hours import OffHours`.

- [ ] **Step 4: Lock and run.**

Run: `cd platform/langfuse && uv lock && uv sync && uv run pytest -q`
Expected: `6 passed`.

- [ ] **Step 5: CI job.** Write the failing workflow test first: in `infra/tests/test_workflows.py`, `test_ci_is_reusable_and_runs_infra_tests`, change the last assertion to `assert {"backend", "web", "design", "helm", "infra", "langfuse"} <= set(ci["jobs"])` and add:

```python
    langfuse = ci["jobs"]["langfuse"]
    assert langfuse["defaults"]["run"]["working-directory"] == "platform/langfuse"
    assert "uv sync --frozen" in steps_text(langfuse) and "uv run pytest" in steps_text(langfuse)
```

Run `cd infra && uv run pytest tests/test_workflows.py -q` (FAIL: no `langfuse` job), then add to `.github/workflows/ci.yml` after the `infra` job:

```yaml
  langfuse:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: platform/langfuse
    env:
      JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION: "1"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --frozen
      - name: CDK and Compose tests
        run: uv run pytest -q
```

Run `cd infra && uv run pytest tests/test_workflows.py -q` again. Expected: pass.

- [ ] **Step 6: Line endings.** In `.gitattributes`, after `deploy/** text eol=lf`, add:

```
# Files the Langfuse VM runs (its CDK asset bundles the working copy).
platform/langfuse/deploy/** text eol=lf
```

- [ ] **Step 7: Commit**

```bash
git add platform/langfuse .github/workflows/ci.yml infra/tests/test_workflows.py .gitattributes
git commit -m "Start the platform/langfuse CDK project with its own OffHours" -m "Langfuse is shared by other apps later, so it gets a CDK project of its own that never references Smart Tutor's stacks (ADR 0021). It keeps its own copy of OffHours so the folder can move to a repository of its own." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 7: The `Langfuse-Host` stack

**Files:**
- Create: `platform/langfuse/langfuse_platform/host_stack.py`, `platform/langfuse/langfuse_platform/app.py`, `platform/langfuse/deploy/.gitkeep` (removed in Task 8)
- Modify: `platform/langfuse/app.py`
- Test: `platform/langfuse/tests/test_host_stack.py`

**Interfaces:**
- Consumes: `OffHours` (Task 6).
- Produces: `langfuse_platform.app.build_app(app: cdk.App) -> LangfuseHostStack`; `LangfuseHostStack(scope, construct_id, *, instance_type: str, domain: str | None, admin_email: str, alert_emails: Sequence[str], data_snapshot_id: str | None, **kwargs)`; constants `PREFIX = "langfuse"`, `DEPLOY_DOCUMENT = "langfuse-deploy"`, `BUNDLE_DIR` (`platform/langfuse/deploy`), `COMPOSE_VERSION`, `COMPOSE_SHA256`. SSM parameters `/langfuse/host/{domain,bundle,bucket,allow-signup}` and secrets `langfuse/{nextauth-secret,salt,encryption-seed,db/postgres,clickhouse,valkey,init-project-keys,admin}` that Task 8's `deploy.sh` reads.

- [ ] **Step 1: Write the failing test** `platform/langfuse/tests/test_host_stack.py`:

```python
"""The Langfuse-Host stack (spec 2026-10-14 §6, ADR 0021, ADR 0022)."""

import json
from typing import Any

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

from langfuse_platform.app import build_app

CONTEXT = {
    "langfuse:region": "us-east-1",
    "langfuse:instance-type": "t3.xlarge",
    "langfuse:domain": "example-langfuse.duckdns.org",
    "langfuse:admin-email": "admin@example.com",
    "langfuse:alert-emails": ["ops@example.com"],
    "langfuse:data-snapshot-id": "",
}


def stack_template(**context: Any) -> Template:
    app = cdk.App(context={**CONTEXT, **context})
    return Template.from_stack(build_app(app))


@pytest.fixture(scope="module")
def t() -> Template:
    return stack_template()


def _statements(t: Template) -> dict[str, dict[str, Any]]:
    return {
        s["Sid"]: s
        for p in t.find_resources("AWS::IAM::Policy").values()
        for s in p["Properties"]["PolicyDocument"]["Statement"]
        if "Sid" in s
    }


def _parameter(t: Template, name: str) -> Any:
    (value,) = (
        p["Properties"]["Value"]
        for p in t.find_resources("AWS::SSM::Parameter").values()
        if p["Properties"]["Name"] == name
    )
    return value


def test_stack_is_named_for_langfuse_and_mentions_no_app(t: Template) -> None:
    text = json.dumps(t.to_json()).lower()
    assert "smart-tutor" not in text and "smarttutor" not in text and "smart_tutor" not in text


def test_own_vpc_with_one_public_subnet_and_only_http_and_https_in(t: Template) -> None:
    t.resource_count_is("AWS::EC2::VPC", 1)
    t.resource_count_is("AWS::EC2::Subnet", 1)
    t.resource_count_is("AWS::EC2::NatGateway", 0)
    t.has_resource_properties("AWS::EC2::VPC", {"CidrBlock": "10.42.0.0/16"})
    (group,) = t.find_resources("AWS::EC2::SecurityGroup").values()
    ingress = group["Properties"]["SecurityGroupIngress"]
    assert sorted((r["FromPort"], r["CidrIp"]) for r in ingress) == [(80, "0.0.0.0/0"), (443, "0.0.0.0/0")]


def test_instance_type_comes_from_context_with_imdsv2_and_no_ssh_key() -> None:
    t = stack_template(**{"langfuse:instance-type": "r7i.large"})
    (instance,) = t.find_resources("AWS::EC2::Instance").values()
    props = instance["Properties"]
    assert props["InstanceType"] == "r7i.large"
    assert "KeyName" not in props
    assert props["MetadataOptions"] == {"HttpTokens": "required", "HttpPutResponseHopLimit": 2}


def test_data_volume_is_100_gib_encrypted_and_snapshotted_daily_for_7_days(t: Template) -> None:
    t.has_resource_properties("AWS::EC2::Volume", {"Size": 100, "VolumeType": "gp3", "Encrypted": True})
    (policy,) = t.find_resources("AWS::DLM::LifecyclePolicy").values()
    (schedule,) = policy["Properties"]["PolicyDetails"]["Schedules"]
    assert schedule["CreateRule"]["Times"] == ["19:00"]  # 02:00 Asia/Ho_Chi_Minh
    assert schedule["RetainRule"] == {"Interval": 7, "IntervalUnit": "DAYS"}


def test_bucket_is_private_encrypted_tls_only_and_kept(t: Template) -> None:
    (bucket_id, bucket) = next(iter(t.find_resources("AWS::S3::Bucket").items()))
    props = bucket["Properties"]
    assert props["PublicAccessBlockConfiguration"] == {
        "BlockPublicAcls": True,
        "BlockPublicPolicy": True,
        "IgnorePublicAcls": True,
        "RestrictPublicBuckets": True,
    }
    assert props["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]["ServerSideEncryptionByDefault"] == {
        "SSEAlgorithm": "AES256"
    }
    assert bucket["DeletionPolicy"] == "Retain"
    (policy,) = t.find_resources("AWS::S3::BucketPolicy").values()
    assert "aws:SecureTransport" in json.dumps(policy)
    (rule,) = props["CorsConfiguration"]["CorsRules"]
    assert sorted(rule["AllowedMethods"]) == ["GET", "PUT"]
    assert rule["AllowedOrigins"] == ["https://example-langfuse.duckdns.org"]


def test_instance_role_reads_only_its_own_settings_and_secrets_and_uses_its_bucket(t: Template) -> None:
    statements = _statements(t)
    assert "parameter/langfuse/host/*" in json.dumps(statements["ReadSettings"]["Resource"])
    assert "secret:langfuse/*" in json.dumps(statements["ReadSecrets"]["Resource"])
    every = json.dumps([p["Properties"] for p in t.find_resources("AWS::IAM::Policy").values()])
    assert "s3:PutObject" in every and "s3:DeleteObject" in every


def test_settings_for_deploy_sh(t: Template) -> None:
    assert _parameter(t, "/langfuse/host/domain") == "example-langfuse.duckdns.org"
    assert _parameter(t, "/langfuse/host/allow-signup") == "false"
    _parameter(t, "/langfuse/host/bundle")
    _parameter(t, "/langfuse/host/bucket")


def test_empty_domain_falls_back_to_the_elastic_ip_on_sslip_io() -> None:
    t = stack_template(**{"langfuse:domain": ""})
    (eip_id,) = t.find_resources("AWS::EC2::EIP")
    assert _parameter(t, "/langfuse/host/domain") == {
        "Fn::Join": ["", [{"Fn::GetAtt": [eip_id, "PublicIp"]}, ".sslip.io"]]
    }


def test_secrets_are_generated_under_langfuse(t: Template) -> None:
    names = sorted(s["Properties"]["Name"] for s in t.find_resources("AWS::SecretsManager::Secret").values())
    assert names == sorted(
        f"langfuse/{n}"
        for n in (
            "admin",
            "clickhouse",
            "db/postgres",
            "encryption-seed",
            "init-project-keys",
            "nextauth-secret",
            "salt",
            "valkey",
        )
    )
    (admin,) = (
        s["Properties"]
        for s in t.find_resources("AWS::SecretsManager::Secret").values()
        if s["Properties"]["Name"] == "langfuse/admin"
    )
    assert json.loads(admin["GenerateSecretString"]["SecretStringTemplate"]) == {"email": "admin@example.com"}
    assert admin["GenerateSecretString"]["GenerateStringKey"] == "password"


def test_deploy_document_takes_no_parameter_and_runs_the_bundled_script(t: Template) -> None:
    (document,) = t.find_resources("AWS::SSM::Document").values()
    props = document["Properties"]
    assert props["Name"] == "langfuse-deploy"
    assert "parameters" not in props["Content"]
    (step,) = props["Content"]["mainSteps"]
    commands = step["inputs"]["runCommand"]
    assert commands[-1] == "bash /opt/langfuse/deploy.sh"
    assert any(c.startswith("cloud-init status --wait") for c in commands)


def test_off_hours_and_patching_without_alarms(t: Template) -> None:
    t.has_resource_properties("AWS::Scheduler::ScheduleGroup", {"Name": "langfuse-off-hours"})
    t.resource_count_is("AWS::Scheduler::Schedule", 3)
    t.resource_count_is("AWS::CloudWatch::Alarm", 0)
    t.resource_count_is("AWS::Route53::HealthCheck", 0)
    t.has_resource_properties(
        "AWS::SSM::MaintenanceWindow",
        {"Schedule": "cron(20 7 ? * SUN *)", "ScheduleTimezone": "Asia/Ho_Chi_Minh"},
    )
    t.has_resource_properties("AWS::SNS::Topic", {"TopicName": "langfuse-alerts"})
    t.has_resource_properties("AWS::SNS::Subscription", {"Protocol": "email", "Endpoint": "ops@example.com"})


def test_no_secret_reaches_the_template_or_the_user_data(t: Template) -> None:
    (instance,) = t.find_resources("AWS::EC2::Instance").values()
    user_data = json.dumps(instance["Properties"]["UserData"])
    assert "secretsmanager" not in user_data
    for secret in t.find_resources("AWS::SecretsManager::Secret").values():
        assert "SecretString" not in secret["Properties"]
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd platform/langfuse && uv run pytest tests/test_host_stack.py -q`
Expected: `ModuleNotFoundError: No module named 'langfuse_platform.app'`.

- [ ] **Step 3: Write `platform/langfuse/langfuse_platform/host_stack.py`**

```python
"""Langfuse host: one EC2 VM that runs self-hosted Langfuse v4 with Docker Compose behind Caddy, shared by any app that
sends it traces, scores, and datasets (spec sdd/specs/2026-10-14-off-hours-and-langfuse-host-design.md §6, ADR 0021).

- Network: a VPC of its own (10.42.0.0/16) with one public subnet, no NAT, and an S3 gateway endpoint. The security
  group admits only TCP 80 and 443; no SSH and no key pair (SSM Session Manager).
- Instance: Amazon Linux 2023, IMDSv2 with a hop limit of 2 so containers get the instance role, and an Elastic IP.
  The address is the context `langfuse:domain` (a DuckDNS name) or `<eip>.sslip.io`.
- Data: a separate encrypted gp3 volume at /data (Postgres, ClickHouse, Valkey, Caddy's certificates), attached at first
  boot by id so it outlives a replaced instance, snapshotted daily (kept 7 days).
- Files: an S3 bucket for Langfuse's event and media uploads, reached with the instance role (no access keys).
- Deploy: `cdk deploy` uploads `deploy/` as an asset; the SSM document `langfuse-deploy` unpacks it to /opt/langfuse and
  runs deploy.sh, which renders settings and secrets into a root-only env file. No secret is in the template, the
  outputs, or the user data.
- Off-hours (ADR 0022): stopped at 18:00 and 00:00, started at 07:00, Asia/Ho_Chi_Minh. No CloudWatch alarms; a failed
  weekly patching window emails `langfuse-alerts`.
"""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_dlm as dlm
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as events_targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_assets as s3_assets
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as sns_subscriptions
from aws_cdk import aws_ssm as ssm
from constructs import Construct

from langfuse_platform.off_hours import OffHours

PREFIX = "langfuse"
TIME_ZONE = "Asia/Ho_Chi_Minh"
DEFAULT_INSTANCE_TYPE = "t3.xlarge"
DATA_VOLUME_GIB = 100
ROOT_VOLUME_GIB = 30
DATA_MOUNT = "/data"
COMPOSE_VERSION = "v5.5.1"
COMPOSE_SHA256 = "db1889184726840f75c4f9c001048430d4f25b3be3cb084d3ddd762bc0aed576"
BUNDLE_DIR = Path(__file__).parents[1] / "deploy"
DEPLOY_DOCUMENT = f"{PREFIX}-deploy"
HOST_TAG = "langfuse:host"
SNAPSHOT_TAG = "langfuse:snapshots"
SNAPSHOT_TIME_UTC = "19:00"  # 02:00 in TIME_ZONE
SNAPSHOT_RETENTION_DAYS = 7
PATCH_SCHEDULE = "cron(20 7 ? * SUN *)"  # twenty minutes after the 07:00 start
ENSURE_HEALTHY = "/opt/langfuse/ensure-healthy.sh"
ENSURE_HEALTHY_COMMAND = (
    f"[ -f {ENSURE_HEALTHY} ] || {{ echo 'ensure-healthy.sh is missing: run the deploy document"
    f" (docs/runbooks/langfuse-host.md)' >&2; exit 1; }}; bash {ENSURE_HEALTHY}"
)
# Generated secrets deploy.sh reads: (construct id, name under langfuse/, length). Never rotate encryption-seed: deploy.sh
# derives Langfuse's ENCRYPTION_KEY from it, and data encrypted with the old key can't be read with a new one.
GENERATED_SECRETS = (
    ("NextAuthSecret", "nextauth-secret", 64),
    ("SaltSecret", "salt", 64),
    ("EncryptionSeedSecret", "encryption-seed", 64),
    ("PostgresSecret", "db/postgres", 32),
    ("ClickHouseSecret", "clickhouse", 32),
    ("ValkeySecret", "valkey", 32),
    ("InitProjectKeysSecret", "init-project-keys", 48),
)


class LangfuseHostStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        instance_type: str = DEFAULT_INSTANCE_TYPE,
        domain: str | None = None,
        admin_email: str,
        alert_emails: Sequence[str] = (),
        data_snapshot_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        vpc = ec2.Vpc(
            self,
            "Vpc",
            ip_addresses=ec2.IpAddresses.cidr("10.42.0.0/16"),
            max_azs=1,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24)
            ],
            gateway_endpoints={"S3": ec2.GatewayVpcEndpointOptions(service=ec2.GatewayVpcEndpointAwsService.S3)},
        )
        subnet = vpc.public_subnets[0]
        security_group = ec2.SecurityGroup(
            self,
            "SecurityGroup",
            vpc=vpc,
            description="Langfuse host: HTTP and HTTPS only",
            allow_all_outbound=True,  # Docker Hub, Let's Encrypt, S3, SSM, Secrets Manager, DuckDNS
        )
        security_group.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(80), "ACME HTTP-01 challenge, HTTPS redirect")
        security_group.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443), "HTTPS")

        volume = ec2.Volume(
            self,
            f"DataVolumeFrom{data_snapshot_id}" if data_snapshot_id else "DataVolume",
            availability_zone=subnet.availability_zone,
            size=cdk.Size.gibibytes(DATA_VOLUME_GIB),
            snapshot_id=data_snapshot_id,
            volume_type=ec2.EbsDeviceVolumeType.GP3,
            encrypted=True,
            removal_policy=cdk.RemovalPolicy.SNAPSHOT,
            volume_name=f"{PREFIX}-data",
        )
        cdk.Tags.of(volume).add(HOST_TAG, PREFIX)
        cdk.Tags.of(volume).add(SNAPSHOT_TAG, PREFIX)

        bundle = s3_assets.Asset(self, "Bundle", path=str(BUNDLE_DIR))

        role = iam.Role(
            self,
            "InstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            description="Langfuse host: read its settings and secrets, use its bucket, managed by SSM",
            managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")],
        )
        role.add_to_policy(
            iam.PolicyStatement(
                sid="ReadSettings",
                actions=["ssm:GetParameter", "ssm:GetParameters"],
                resources=[self.format_arn(service="ssm", resource="parameter", resource_name=f"{PREFIX}/host/*")],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                sid="ReadSecrets",
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    self.format_arn(
                        service="secretsmanager",
                        resource="secret",
                        resource_name=f"{PREFIX}/*",
                        arn_format=cdk.ArnFormat.COLON_RESOURCE_NAME,
                    )
                ],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                sid="AttachDataVolume",
                actions=["ec2:AttachVolume"],
                resources=[
                    self.format_arn(service="ec2", resource="volume", resource_name=volume.volume_id),
                    self.format_arn(service="ec2", resource="instance", resource_name="*"),
                ],
                conditions={"StringEquals": {f"aws:ResourceTag/{HOST_TAG}": PREFIX}},
            )
        )
        bundle.grant_read(role)

        instance = ec2.Instance(
            self,
            "Instance",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnets=[subnet]),
            instance_type=ec2.InstanceType(instance_type),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(),
            security_group=security_group,
            role=role,
            user_data=_user_data(volume.volume_id, self.region, data_snapshot_id),
            http_tokens=ec2.HttpTokens.REQUIRED,
            http_put_response_hop_limit=2,  # one hop for the host, one for the Docker bridge
            user_data_causes_replacement=True,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/xvda",
                    volume=ec2.BlockDeviceVolume.ebs(
                        ROOT_VOLUME_GIB, volume_type=ec2.EbsDeviceVolumeType.GP3, encrypted=True
                    ),
                )
            ],
        )
        cdk.Tags.of(instance).add(HOST_TAG, PREFIX)
        cdk.Tags.of(instance).add("Name", PREFIX)
        cdk.Tags.of(instance).add("PatchGroup", PREFIX)

        address = ec2.CfnEIP(self, "Address", domain="vpc")
        ec2.CfnEIPAssociation(
            self, "AddressAssociation", allocation_id=address.attr_allocation_id, instance_id=instance.instance_id
        )
        domain = domain or cdk.Fn.join("", [address.attr_public_ip, ".sslip.io"])
        origin = f"https://{domain}" if not cdk.Token.is_unresolved(domain) else "https://*.sslip.io"

        bucket = s3.Bucket(
            self,
            "Bucket",
            bucket_name=f"{PREFIX}-{self.account}-{self.region}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=cdk.RemovalPolicy.RETAIN,
            # Langfuse's media uploads and views use presigned URLs from the browser.
            cors=[
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.GET, s3.HttpMethods.PUT],
                    allowed_origins=[origin],
                    allowed_headers=["*"],
                    max_age=3000,
                )
            ],
        )
        bucket.grant_read_write(role)

        for construct_name, name, length in GENERATED_SECRETS:
            secretsmanager.Secret(
                self,
                construct_name,
                secret_name=f"{PREFIX}/{name}",
                description=f"Langfuse host: {name}",
                generate_secret_string=secretsmanager.SecretStringGenerator(
                    exclude_punctuation=True, password_length=length
                ),
            )
        secretsmanager.Secret(
            self,
            "AdminSecret",
            secret_name=f"{PREFIX}/admin",
            description="Langfuse host: the first admin, created by headless initialization",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template=json.dumps({"email": admin_email}),
                generate_string_key="password",
                exclude_punctuation=True,
                password_length=24,
                require_each_included_type=True,
            ),
        )

        for name, value in (
            ("domain", domain),
            ("bundle", bundle.s3_object_url),
            ("bucket", bucket.bucket_name),
            # Sign-up stays off; the runbook sets this to true for one deploy while an invited person signs up.
            ("allow-signup", "false"),
        ):
            ssm.StringParameter(self, f"Host-{name}", parameter_name=f"/{PREFIX}/host/{name}", string_value=value)

        document = ssm.CfnDocument(
            self,
            "DeployDocument",
            name=DEPLOY_DOCUMENT,
            document_type="Command",
            update_method="NewVersion",
            content={
                "schemaVersion": "2.2",
                "description": "Deploy Langfuse on the Langfuse host (docs/runbooks/langfuse-host.md)",
                "mainSteps": [
                    {
                        "action": "aws:runShellScript",
                        "name": "deploy",
                        "inputs": {"timeoutSeconds": "1800", "runCommand": _deploy_commands(self.region)},
                    }
                ],
            },
        )

        topic = sns.Topic(self, "Alerts", topic_name=f"{PREFIX}-alerts")
        for email in alert_emails:
            topic.add_subscription(sns_subscriptions.EmailSubscription(email))
        self._snapshots()
        _patching(self, instance, topic)
        OffHours(self, "OffHours", instance=instance, name_prefix=PREFIX, time_zone=TIME_ZONE)

        cdk.CfnOutput(self, "InstanceId", value=instance.instance_id)
        cdk.CfnOutput(self, "PublicIp", value=address.attr_public_ip)
        cdk.CfnOutput(self, "PublicUrl", value=f"https://{domain}")
        cdk.CfnOutput(self, "DataVolumeId", value=volume.volume_id)
        cdk.CfnOutput(self, "BucketName", value=bucket.bucket_name)
        cdk.CfnOutput(self, "DeployDocumentName", value=document.ref)

    def _snapshots(self) -> None:
        role = iam.Role(
            self,
            "SnapshotRole",
            assumed_by=iam.ServicePrincipal("dlm.amazonaws.com"),
            description="Data Lifecycle Manager: snapshot the Langfuse data volume",
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSDataLifecycleManagerServiceRole")
            ],
        )
        dlm.CfnLifecyclePolicy(
            self,
            "DataVolumeSnapshots",
            description=f"{PREFIX} data volume daily kept {SNAPSHOT_RETENTION_DAYS} days",
            state="ENABLED",
            execution_role_arn=role.role_arn,
            policy_details=dlm.CfnLifecyclePolicy.PolicyDetailsProperty(
                policy_type="EBS_SNAPSHOT_MANAGEMENT",
                resource_types=["VOLUME"],
                target_tags=[cdk.CfnTag(key=SNAPSHOT_TAG, value=PREFIX)],
                schedules=[
                    dlm.CfnLifecyclePolicy.ScheduleProperty(
                        name="daily",
                        copy_tags=True,
                        create_rule=dlm.CfnLifecyclePolicy.CreateRuleProperty(
                            interval=24, interval_unit="HOURS", times=[SNAPSHOT_TIME_UTC]
                        ),
                        retain_rule=dlm.CfnLifecyclePolicy.RetainRuleProperty(
                            interval=SNAPSHOT_RETENTION_DAYS, interval_unit="DAYS"
                        ),
                    )
                ],
            ),
        )


def _user_data(volume_id: str, region: str, data_snapshot_id: str | None) -> ec2.UserData:
    """First boot: attach and mount the data volume, then install Docker and Compose. Holds no secret."""
    user_data = ec2.UserData.for_linux()
    user_data.add_commands(
        f"# Data volume from snapshot: {data_snapshot_id or 'none'}",
        "set -euo pipefail",
        f"volume_id={volume_id}",
        f"region={region}",
        "imds=http://169.254.169.254/latest",
        'token=$(curl -sf -X PUT "$imds/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 300")',
        'instance_id=$(curl -sf -H "X-aws-ec2-metadata-token: $token" "$imds/meta-data/instance-id")',
        'device="/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_${volume_id//-/}"',
        'until [ -e "$device" ]; do',
        '  aws ec2 attach-volume --region "$region" --volume-id "$volume_id" --instance-id "$instance_id"'
        " --device /dev/sdf"
        ' >/dev/null 2>&1 || echo "Waiting for $volume_id to be free"',
        "  sleep 10",
        "done",
        '[ -n "$(blkid -o value -s TYPE "$device")" ] || mkfs.xfs "$device"',
        f"mkdir -p {DATA_MOUNT}",
        'uuid=$(blkid -o value -s UUID "$device")',
        f'grep -q "$uuid" /etc/fstab || echo "UUID=$uuid {DATA_MOUNT} xfs defaults,nofail 0 2" >> /etc/fstab',
        f"mount {DATA_MOUNT}",
        "dnf install -y docker unzip",
        "mkdir -p /etc/systemd/system/docker.service.d",
        f"printf '[Unit]\\nRequiresMountsFor={DATA_MOUNT}\\n' > /etc/systemd/system/docker.service.d/data-volume.conf",
        "systemctl daemon-reload",
        "systemctl enable --now docker",
        "mkdir -p /usr/local/lib/docker/cli-plugins",
        "curl -sfL -o /usr/local/lib/docker/cli-plugins/docker-compose"
        f" https://github.com/docker/compose/releases/download/{COMPOSE_VERSION}/docker-compose-linux-x86_64",
        f'echo "{COMPOSE_SHA256}  /usr/local/lib/docker/cli-plugins/docker-compose" | sha256sum -c -',
        "chmod 755 /usr/local/lib/docker/cli-plugins/docker-compose",
    )
    return user_data


def _deploy_commands(region: str) -> list[str]:
    """The SSM document's script: wait for first boot, fetch the bundle `cdk deploy` uploaded, run deploy.sh."""
    return [
        "set -euo pipefail",
        "cloud-init status --wait > /dev/null || echo 'Warning: first boot (cloud-init) reported an error; see /var/log/cloud-init-output.log' >&2",
        f"export AWS_REGION={region} AWS_DEFAULT_REGION={region}",
        f"bundle=$(aws ssm get-parameter --name /{PREFIX}/host/bundle --query Parameter.Value --output text)",
        "rm -rf /opt/langfuse.new /tmp/langfuse-bundle.zip",
        'aws s3 cp --only-show-errors "$bundle" /tmp/langfuse-bundle.zip',
        "unzip -q /tmp/langfuse-bundle.zip -d /opt/langfuse.new",
        "rm -rf /opt/langfuse /tmp/langfuse-bundle.zip",
        "mv /opt/langfuse.new /opt/langfuse",
        "bash /opt/langfuse/deploy.sh",
    ]


def _patching(scope: Construct, instance: ec2.Instance, topic: sns.ITopic) -> None:
    """Weekly security patching through SSM Patch Manager, then a check that every service is healthy again."""
    ssm.CfnPatchBaseline(
        scope,
        "PatchBaseline",
        name=f"{PREFIX}-security",
        description="Security updates for the Langfuse host",
        operating_system="AMAZON_LINUX_2023",
        patch_groups=[PREFIX],
        approval_rules=ssm.CfnPatchBaseline.RuleGroupProperty(
            patch_rules=[
                ssm.CfnPatchBaseline.RuleProperty(
                    approve_after_days=0,
                    compliance_level="HIGH",
                    patch_filter_group=ssm.CfnPatchBaseline.PatchFilterGroupProperty(
                        patch_filters=[
                            ssm.CfnPatchBaseline.PatchFilterProperty(key="CLASSIFICATION", values=["Security"])
                        ]
                    ),
                )
            ]
        ),
    )
    window = ssm.CfnMaintenanceWindow(
        scope,
        "PatchWindow",
        name=f"{PREFIX}-patching",
        description="Weekly security patching of the Langfuse host (docs/runbooks/langfuse-host.md)",
        schedule=PATCH_SCHEDULE,
        schedule_timezone=TIME_ZONE,
        duration=3,
        cutoff=1,
        allow_unassociated_targets=False,
    )
    target = ssm.CfnMaintenanceWindowTarget(
        scope,
        "PatchWindowTarget",
        window_id=window.ref,
        resource_type="INSTANCE",
        targets=[ssm.CfnMaintenanceWindowTarget.TargetsProperty(key="InstanceIds", values=[instance.instance_id])],
    )

    def task(construct_id: str, priority: int, document: str, parameters: dict[str, list[str]]) -> None:
        ssm.CfnMaintenanceWindowTask(
            scope,
            construct_id,
            window_id=window.ref,
            priority=priority,
            task_type="RUN_COMMAND",
            task_arn=document,
            targets=[ssm.CfnMaintenanceWindowTask.TargetProperty(key="WindowTargetIds", values=[target.ref])],
            max_concurrency="1",
            max_errors="1",
            cutoff_behavior="CONTINUE_TASK",
            task_invocation_parameters=ssm.CfnMaintenanceWindowTask.TaskInvocationParametersProperty(
                maintenance_window_run_command_parameters=ssm.CfnMaintenanceWindowTask.MaintenanceWindowRunCommandParametersProperty(
                    parameters=parameters
                )
            ),
        )

    task("PatchTask", 1, "AWS-RunPatchBaseline", {"Operation": ["Install"], "RebootOption": ["RebootIfNeeded"]})
    task("HealthTask", 2, "AWS-RunShellScript", {"commands": [ENSURE_HEALTHY_COMMAND], "executionTimeout": ["1200"]})

    events.Rule(
        scope,
        "PatchWindowFailedRule",
        description="Email when the Langfuse patching window fails or times out",
        event_pattern=events.EventPattern(
            source=["aws.ssm"],
            detail_type=["Maintenance Window Execution State-change Notification"],
            detail={"window-id": [window.ref], "status": ["FAILED", "TIMED_OUT"]},
        ),
        targets=[
            events_targets.SnsTopic(
                topic,
                message=events.RuleTargetInput.from_text(
                    f"The patching window {PREFIX}-patching ended {events.EventField.from_path('$.detail.status')}"
                    f" (execution {events.EventField.from_path('$.detail.window-execution-id')})."
                    " See docs/runbooks/langfuse-host.md."
                ),
            )
        ],
    )
```

Note on `origin`: with a domain set, CORS allows exactly `https://<domain>`; with none, the sslip.io name is the Elastic IP, a token, so CORS allows `https://*.sslip.io` (presigned URLs stay the credential), as Smart Tutor's StorageStack does.

- [ ] **Step 4: Write `platform/langfuse/langfuse_platform/app.py`**

```python
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
        alert_emails=context("langfuse:alert-emails") or [],
        data_snapshot_id=context("langfuse:data-snapshot-id") or None,
    )
```

and replace `platform/langfuse/app.py` with:

```python
"""CDK entry point for the shared Langfuse host (spec sdd/specs/2026-10-14-off-hours-and-langfuse-host-design.md §6)."""

import aws_cdk as cdk

from langfuse_platform.app import build_app

app = cdk.App()
build_app(app)
app.synth()
```

Create `platform/langfuse/deploy/.gitkeep` (empty) so the asset directory exists until Task 8.

- [ ] **Step 5: Run the tests**

Run: `cd platform/langfuse && uv run pytest -q`
Expected: all pass. If `test_stack_is_named_for_langfuse_and_mentions_no_app` fails on a CDK-generated string, find which value carries it and rename that value; don't weaken the test.

- [ ] **Step 6: Synthesize**

Run: `cd platform/langfuse && npx aws-cdk@latest synth --quiet`
Expected: exit 0, `Langfuse-Host` in `cdk.out`.

- [ ] **Step 7: Commit**

```bash
git add platform/langfuse
git commit -m "Add the Langfuse-Host stack" -m "One t3.xlarge in a VPC of its own with a 100 GiB data volume, daily snapshots, an S3 bucket reached with the instance role, generated secrets, an SSM deploy document, weekly patching, and the off-hours schedule; no alarms (ADR 0021, ADR 0022)." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 8: What the Langfuse VM runs

**Files:**
- Create: `platform/langfuse/deploy/compose.yaml`, `platform/langfuse/deploy/Caddyfile`, `platform/langfuse/deploy/deploy.sh`, `platform/langfuse/deploy/ensure-healthy.sh`
- Delete: `platform/langfuse/deploy/.gitkeep`
- Test: `platform/langfuse/tests/test_vm_files.py`

**Interfaces:**
- Consumes: SSM `/langfuse/host/{domain,bucket,allow-signup}` and secrets `langfuse/*` from Task 7; `/opt/langfuse/deploy.sh` and `/opt/langfuse/ensure-healthy.sh` paths that Task 7's document and patch task call.

- [ ] **Step 1: Write the failing test** `platform/langfuse/tests/test_vm_files.py`:

```python
"""What the Langfuse VM runs: Compose, Caddy, deploy.sh, ensure-healthy.sh (spec 2026-10-14 §6.4–6.5)."""

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

DEPLOY_DIR = Path(__file__).parents[1] / "deploy"
DEPLOY_SCRIPT = DEPLOY_DIR / "deploy.sh"
ENSURE_HEALTHY = DEPLOY_DIR / "ensure-healthy.sh"
SCRIPTS = [DEPLOY_SCRIPT, ENSURE_HEALTHY]
PINNED = re.compile(r"^[a-z0-9./-]+:\d+\.\d+(\.\d+)*(-alpine)?$")


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load((DEPLOY_DIR / "compose.yaml").read_text(encoding="utf-8"))
    return loaded


def test_services(compose: dict[str, Any]) -> None:
    assert set(compose["services"]) == {"langfuse-web", "langfuse-worker", "clickhouse", "postgres", "valkey", "caddy"}


def test_every_image_is_pinned_to_an_exact_version(compose: dict[str, Any]) -> None:
    for name, service in compose["services"].items():
        assert PINNED.match(service["image"]), (name, service["image"])
    assert compose["services"]["langfuse-web"]["image"] == "langfuse/langfuse:4.47.0"
    assert compose["services"]["langfuse-worker"]["image"] == "langfuse/langfuse-worker:4.47.0"


def test_every_service_comes_back_after_a_boot_with_a_memory_limit_and_a_health_check(compose: dict[str, Any]) -> None:
    for name, service in compose["services"].items():
        assert service["restart"] == "unless-stopped", name
        assert "mem_limit" in service, name
        assert "healthcheck" in service, name


def test_databases_shut_down_cleanly_when_the_instance_stops(compose: dict[str, Any]) -> None:
    for name in ("postgres", "clickhouse"):
        assert compose["services"][name]["stop_grace_period"] == "60s", name


def test_only_caddy_publishes_ports(compose: dict[str, Any]) -> None:
    published = {name for name, s in compose["services"].items() if s.get("ports")}
    assert published == {"caddy"}
    assert compose["services"]["caddy"]["ports"] == ["80:80", "443:443"]


def test_langfuse_settings(compose: dict[str, Any]) -> None:
    web = compose["services"]["langfuse-web"]["environment"]
    worker = compose["services"]["langfuse-worker"]["environment"]
    for env in (web, worker):
        assert env["CLICKHOUSE_CLUSTER_ENABLED"] == "false"
        assert env["TELEMETRY_ENABLED"] == "false"
        assert env["REDIS_HOST"] == "valkey"
        # No S3 keys: Langfuse falls back to the AWS credential chain, i.e. the instance role.
        assert not any(key.endswith(("_ACCESS_KEY_ID", "_SECRET_ACCESS_KEY")) for key in env)
    assert web["HOSTNAME"] == "0.0.0.0"  # Caddy reaches it by service name, not the container's hostname
    assert web["AUTH_DISABLE_SIGNUP"] == "${AUTH_DISABLE_SIGNUP:?}"
    assert web["NEXTAUTH_URL"] == "https://${LANGFUSE_DOMAIN:?}"


def test_data_lives_on_the_data_volume(compose: dict[str, Any]) -> None:
    for name in ("postgres", "clickhouse", "valkey", "caddy"):
        assert any(v.startswith("/data/") for v in compose["services"][name]["volumes"]), name
    assert "volumes" not in compose  # no named volumes on the root disk


def test_caddy_proxies_only_langfuse_web() -> None:
    caddyfile = (DEPLOY_DIR / "Caddyfile").read_text(encoding="utf-8")
    assert "{$LANGFUSE_DOMAIN}" in caddyfile
    assert re.findall(r"reverse_proxy (\S+)", caddyfile) == ["langfuse-web:3000"]


def test_deploy_script_keeps_secrets_out_of_output_and_files_root_only() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "set -x" not in script and "compose config" not in script
    assert "umask 077" in script
    assert "/etc/langfuse/langfuse.env" in script


def test_encryption_key_is_derived_from_its_seed_and_never_generated() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert 'encryption_key=$(hex64 encryption "$(secret encryption-seed)")' in script
    assert "openssl rand" not in script


def test_sign_up_opens_only_when_the_setting_is_exactly_true() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert 'if [[ $(param allow-signup) == true ]]; then auth_disable_signup=false; else auth_disable_signup=true; fi' in script


def test_deploy_gives_docker_time_to_stop_the_containers_when_the_instance_stops() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "/etc/systemd/system/docker.service.d/stop-timeout.conf" in script
    assert "TimeoutStopSec=120" in script


def test_deploy_waits_for_every_service_to_be_healthy() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "up -d --remove-orphans --wait --wait-timeout 900" in script


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_scripts_parse(script: Path) -> None:
    subprocess.run(["bash", "-n"], input=script.read_bytes(), check=True)


def test_files_the_vm_runs_keep_lf_line_endings() -> None:
    for path in DEPLOY_DIR.iterdir():
        assert b"\r\n" not in path.read_bytes(), path
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd platform/langfuse && uv run pytest tests/test_vm_files.py -q`
Expected: errors (no `compose.yaml`).

- [ ] **Step 3: Write `platform/langfuse/deploy/compose.yaml`**

```yaml
# Langfuse v4 on the Langfuse host (spec 2026-10-14 §6.4, ADR 0021): deploy.sh renders /etc/langfuse/langfuse.env and
# runs `docker compose up`. Every image is pinned; data is under /data (the data volume); only Caddy publishes ports.
# Based on Langfuse's own docker-compose.yml, with S3 instead of MinIO and Valkey instead of Redis.

x-logging: &logging
  driver: json-file
  options: {max-size: 10m, max-file: "5"}

x-langfuse-env: &langfuse-env
  NEXTAUTH_URL: https://${LANGFUSE_DOMAIN:?}
  DATABASE_URL: ${DATABASE_URL:?}
  SALT: ${SALT:?}
  ENCRYPTION_KEY: ${ENCRYPTION_KEY:?}
  TELEMETRY_ENABLED: "false"
  CLICKHOUSE_MIGRATION_URL: clickhouse://clickhouse:9000
  CLICKHOUSE_URL: http://clickhouse:8123
  CLICKHOUSE_USER: clickhouse
  CLICKHOUSE_PASSWORD: ${CLICKHOUSE_PASSWORD:?}
  CLICKHOUSE_CLUSTER_ENABLED: "false"
  REDIS_HOST: valkey
  REDIS_PORT: "6379"
  REDIS_AUTH: ${REDIS_AUTH:?}
  # No access keys: Langfuse falls back to the AWS credential chain, the instance role (IMDSv2, hop limit 2).
  LANGFUSE_S3_EVENT_UPLOAD_BUCKET: ${S3_BUCKET:?}
  LANGFUSE_S3_EVENT_UPLOAD_REGION: ${AWS_REGION:?}
  LANGFUSE_S3_EVENT_UPLOAD_PREFIX: events/
  LANGFUSE_S3_MEDIA_UPLOAD_BUCKET: ${S3_BUCKET:?}
  LANGFUSE_S3_MEDIA_UPLOAD_REGION: ${AWS_REGION:?}
  LANGFUSE_S3_MEDIA_UPLOAD_PREFIX: media/

x-langfuse-depends: &langfuse-depends
  postgres: {condition: service_healthy}
  clickhouse: {condition: service_healthy}
  valkey: {condition: service_healthy}

services:
  langfuse-web:
    image: langfuse/langfuse:4.47.0
    restart: unless-stopped
    logging: *logging
    mem_limit: 2g
    depends_on: *langfuse-depends
    environment:
      <<: *langfuse-env
      HOSTNAME: 0.0.0.0
      NEXTAUTH_SECRET: ${NEXTAUTH_SECRET:?}
      AUTH_DISABLE_SIGNUP: ${AUTH_DISABLE_SIGNUP:?}
      # Headless initialization: one organization, one project, its API keys, and the first admin (on first start).
      LANGFUSE_INIT_ORG_ID: platform
      LANGFUSE_INIT_ORG_NAME: Platform
      LANGFUSE_INIT_PROJECT_ID: sandbox
      LANGFUSE_INIT_PROJECT_NAME: Sandbox
      LANGFUSE_INIT_PROJECT_PUBLIC_KEY: ${INIT_PUBLIC_KEY:?}
      LANGFUSE_INIT_PROJECT_SECRET_KEY: ${INIT_SECRET_KEY:?}
      LANGFUSE_INIT_USER_EMAIL: ${ADMIN_EMAIL:?}
      LANGFUSE_INIT_USER_NAME: Admin
      LANGFUSE_INIT_USER_PASSWORD: ${ADMIN_PASSWORD:?}
    healthcheck:
      test: ["CMD", "node", "-e", "fetch('http://127.0.0.1:3000/api/public/health').then(r => process.exit(r.ok ? 0 : 1), () => process.exit(1))"]
      interval: 15s
      timeout: 10s
      retries: 20
      start_period: 60s

  langfuse-worker:
    image: langfuse/langfuse-worker:4.47.0
    restart: unless-stopped
    logging: *logging
    mem_limit: 2g
    depends_on: *langfuse-depends
    environment: *langfuse-env
    healthcheck:
      test: ["CMD", "node", "-e", "fetch('http://127.0.0.1:3030/api/health').then(r => process.exit(r.ok ? 0 : 1), () => process.exit(1))"]
      interval: 15s
      timeout: 10s
      retries: 20
      start_period: 60s

  clickhouse:
    image: clickhouse/clickhouse-server:25.12.11.4
    restart: unless-stopped
    logging: *logging
    mem_limit: 6g
    stop_grace_period: 60s  # a clean shutdown when the instance stops (off-hours, ADR 0022)
    user: "101:101"
    environment:
      CLICKHOUSE_DB: default
      CLICKHOUSE_USER: clickhouse
      CLICKHOUSE_PASSWORD: ${CLICKHOUSE_PASSWORD:?}
    volumes:
      - /data/clickhouse:/var/lib/clickhouse
      - /data/clickhouse-logs:/var/log/clickhouse-server
    healthcheck:
      test: ["CMD-SHELL", "wget --no-verbose --tries=1 --spider http://localhost:8123/ping || exit 1"]
      interval: 5s
      timeout: 5s
      retries: 20

  postgres:
    image: postgres:17.11-alpine
    restart: unless-stopped
    logging: *logging
    mem_limit: 1g
    stop_grace_period: 60s  # a clean shutdown when the instance stops (off-hours, ADR 0022)
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?}
      POSTGRES_DB: postgres
      TZ: UTC
      PGTZ: UTC
    volumes:
      - /data/postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 20

  valkey:
    image: valkey/valkey:8.1.10-alpine
    restart: unless-stopped
    logging: *logging
    mem_limit: 512m
    command: ["valkey-server", "--requirepass", "${REDIS_AUTH:?}", "--maxmemory", "384mb", "--maxmemory-policy", "noeviction"]
    volumes:
      - /data/valkey:/data
    healthcheck:
      test: ["CMD", "valkey-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 20

  caddy:
    image: caddy:2.11.4-alpine
    restart: unless-stopped
    logging: *logging
    mem_limit: 128m
    ports: ["80:80", "443:443"]
    depends_on:
      langfuse-web: {condition: service_healthy}
    environment:
      LANGFUSE_DOMAIN: ${LANGFUSE_DOMAIN:?}
    labels:
      # A bind-mounted file keeps its old contents after a redeploy; a changed digest recreates the container.
      langfuse.caddyfile-sha256: ${CADDYFILE_SHA256:?}
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - /data/caddy/data:/data  # certificates and the ACME account survive replacing the VM
      - /data/caddy/config:/config
    healthcheck:
      test: ["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1:2019/config/"]
      interval: 15s
      timeout: 5s
      retries: 5
```

- [ ] **Step 4: Write `platform/langfuse/deploy/Caddyfile`**

```
# Langfuse host edge (spec 2026-10-14 §6.4): HTTPS for LANGFUSE_DOMAIN with a Let's Encrypt certificate (HTTP
# redirects to it), proxied to Langfuse web. Its UI, public API, and OTLP endpoint (/api/public/otel) are all there.
{
	servers {
		# The security group opens TCP 80 and 443 only: no HTTP/3 over UDP.
		protocols h1 h2
	}
}

{$LANGFUSE_DOMAIN} {
	reverse_proxy langfuse-web:3000
}
```

- [ ] **Step 5: Write `platform/langfuse/deploy/deploy.sh`**

```bash
#!/usr/bin/env bash
# Deploys Langfuse on the Langfuse host (spec 2026-10-14 §6.5, ADR 0021). SSM Run Command runs it as root through the
# document langfuse-deploy (LangfuseHostStack), after unpacking the bundle to /opt/langfuse:
#   AWS_REGION=us-east-1 bash /opt/langfuse/deploy.sh
#
# 1. Renders settings (SSM /langfuse/host/*) and secrets (Secrets Manager langfuse/*) into a root-only env file.
# 2. Points a DuckDNS domain at this instance's Elastic IP.
# 3. Gives Docker two minutes to stop the containers when the instance stops (off-hours, ADR 0022).
# 4. Pulls the pinned images, starts every service, and waits until all are healthy. The same bundle again changes
#    nothing.
#
# It prints no secret: never add `set -x`, `docker compose config`, or an echo of the env file.
set -euo pipefail

region=${AWS_REGION:?}
here=$(cd "$(dirname "$0")" && pwd)
env_file=/etc/langfuse/langfuse.env
compose=(docker compose --project-directory "$here" -f "$here/compose.yaml" --env-file "$env_file")

param() { aws ssm get-parameter --name "/langfuse/host/$1" --query Parameter.Value --output text; }
secret() { aws secretsmanager get-secret-value --secret-id "langfuse/$1" --query SecretString --output text; }
field() { python3 -c 'import json, sys; print(json.loads(sys.stdin.read())[sys.argv[1]])' "$1"; }
# 64 hex characters from a label and a generated secret: Secrets Manager can't generate hex, and Langfuse's
# ENCRYPTION_KEY must be 64 hex characters. The same secret always gives the same key; never rotate encryption-seed.
hex64() { printf '%s:%s' "$1" "$2" | sha256sum | cut -d' ' -f1; }

# A new instance attaches the data volume at first boot, after the instance it replaced lets go of it.
for _ in $(seq 90); do mountpoint -q /data && break; sleep 10; done
mountpoint -q /data || { echo "/data is not mounted: the data volume isn't attached (see the instance's user data log)" >&2; exit 1; }
mkdir -p /data/postgres /data/clickhouse /data/clickhouse-logs /data/valkey /data/caddy/data /data/caddy/config
chown 101:101 /data/clickhouse /data/clickhouse-logs  # ClickHouse runs as 101:101

echo "Reading settings and secrets"
domain=$(param domain)
bucket=$(param bucket)
if [[ $(param allow-signup) == true ]]; then auth_disable_signup=false; else auth_disable_signup=true; fi
postgres_password=$(secret db/postgres)
# Built here, not written out in compose.yaml: a user:password@host URL in the repository looks like a leaked
# credential to secret scanners.
database_url=$(printf 'postgresql://%s@postgres:5432/postgres' "postgres:$postgres_password")
clickhouse_password=$(secret clickhouse)
redis_auth=$(secret valkey)
nextauth_secret=$(secret nextauth-secret)
salt=$(secret salt)
encryption_key=$(hex64 encryption "$(secret encryption-seed)")
project_seed=$(secret init-project-keys)
init_public_key="pk-lf-$(hex64 public "$project_seed" | cut -c1-32)"
init_secret_key="sk-lf-$(hex64 secret "$project_seed" | cut -c1-32)"
admin=$(secret admin)
admin_email=$(field email <<<"$admin")
admin_password=$(field password <<<"$admin")
caddyfile_sha256=$(sha256sum "$here/Caddyfile" | cut -d' ' -f1)

umask 077
mkdir -p "$(dirname "$env_file")"
rendered=$(mktemp "$env_file.XXXXXX")
cat > "$rendered" <<EOF
LANGFUSE_DOMAIN=$domain
AWS_REGION=$region
S3_BUCKET=$bucket
AUTH_DISABLE_SIGNUP=$auth_disable_signup
POSTGRES_PASSWORD=$postgres_password
DATABASE_URL=$database_url
CLICKHOUSE_PASSWORD=$clickhouse_password
REDIS_AUTH=$redis_auth
NEXTAUTH_SECRET=$nextauth_secret
SALT=$salt
ENCRYPTION_KEY=$encryption_key
INIT_PUBLIC_KEY=$init_public_key
INIT_SECRET_KEY=$init_secret_key
ADMIN_EMAIL=$admin_email
ADMIN_PASSWORD=$admin_password
CADDYFILE_SHA256=$caddyfile_sha256
EOF
mv "$rendered" "$env_file"

# A DuckDNS name follows the Elastic IP: without an `ip`, DuckDNS uses the address the request comes from. The operator
# creates the token's secret (docs/runbooks/langfuse-host.md); it reaches curl on stdin, never its command line. A
# failure only warns: the name most likely still points here.
if [[ $domain == *.duckdns.org ]]; then
  duckdns_url="https://www.duckdns.org/update?domains=${domain%.duckdns.org}&token="
  if duckdns_token=$(secret duckdns-token 2>/dev/null) &&
    duckdns_answer=$(curl -sS --max-time 20 -K - <<<"url = \"$duckdns_url$duckdns_token\"") &&
    [[ $duckdns_answer == OK ]]; then
    echo "Pointed $domain at this instance"
  else
    echo "Warning: could not update $domain on DuckDNS (is the secret langfuse/duckdns-token set?)" >&2
  fi
fi

# Off-hours (ADR 0022): EC2 stops the instance by shutting the OS down, and systemd stops Docker. Postgres and
# ClickHouse need up to 60 s (stop_grace_period) to shut down cleanly, so Docker gets longer than systemd's default.
mkdir -p /etc/systemd/system/docker.service.d
printf '[Service]\nTimeoutStopSec=120\n' > /etc/systemd/system/docker.service.d/stop-timeout.conf
systemctl daemon-reload

echo "Pulling the pinned images"
"${compose[@]}" pull --quiet
echo "Starting Langfuse"
"${compose[@]}" up -d --remove-orphans --wait --wait-timeout 900
"${compose[@]}" ps --format 'table {{.Service}}\t{{.Status}}'
echo "Langfuse is up at https://$domain"
```

- [ ] **Step 6: Write `platform/langfuse/deploy/ensure-healthy.sh`**

```bash
#!/usr/bin/env bash
# Brings Langfuse back after the weekly patching: the maintenance window langfuse-patching (LangfuseHostStack) runs it as
# root after AWS-RunPatchBaseline, which may have rebooted the VM. Operators can run it too:
#   sudo bash /opt/langfuse/ensure-healthy.sh
# It starts Docker and any service that isn't running, with the settings of the last deploy, and waits until every
# service is healthy. It fails if one isn't healthy within 15 minutes, which fails the window and emails
# langfuse-alerts. It doesn't pull: that is deploy.sh's job. Like deploy.sh, it prints no secret.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
env_file=/etc/langfuse/langfuse.env
compose=(docker compose --project-directory "$here" -f "$here/compose.yaml" --env-file "$env_file")

if [ ! -f "$env_file" ]; then
  echo "Nothing to check: Langfuse hasn't been deployed on this VM yet"
  exit 0
fi

systemctl is-active --quiet docker || systemctl start docker
"${compose[@]}" up -d --wait --wait-timeout 900
"${compose[@]}" ps --format 'table {{.Service}}\t{{.Status}}'
echo "Every service is healthy"
```

Then `git rm platform/langfuse/deploy/.gitkeep`.

- [ ] **Step 7: Run all Langfuse tests**

Run: `cd platform/langfuse && uv run pytest -q`
Expected: all pass, including `test_host_stack.py` (the asset now bundles the real files).

- [ ] **Step 8: Commit**

```bash
git add -A platform/langfuse
git commit -m "Run Langfuse v4 on the Langfuse host with Compose behind Caddy" -m "Pinned Langfuse 4.47.0 with ClickHouse, Postgres, and Valkey on the data volume, S3 through the instance role, sign-up off, and a deploy script that renders secrets into a root-only env file and derives a stable encryption key." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 9: ADR 0021, the Langfuse runbook, AGENTS.md, the structure spec, and PR 2

**Files:**
- Create: `sdd/adr/0021-langfuse-on-a-shared-host.md`, `docs/runbooks/langfuse-host.md`
- Modify: `sdd/adr/README.md`, `sdd/adr/0017-self-hosted-phoenix-for-runtime-tracing.md` (status line), `AGENTS.md`, `sdd/specs/2026-10-02-project-structure-design.md`, `sdd/prd.md`

- [ ] **Step 1: ADR 0021** `sdd/adr/0021-langfuse-on-a-shared-host.md`:

```markdown
# 0021. Langfuse for observability and evaluation, on a shared host in its own CDK project

- Status: accepted
- Date: 2026-10-14
- Supersedes: ADR 0017's choice of Phoenix for runtime tracing (Phoenix keeps running until the Langfuse migration
  lands), and its "evals stay on LangSmith"

## Context

The LangSmith workspace hit its free plan's monthly trace cap (ADR 0017), and on 2026-10-14 it blocked eval work too
(#302's candidates couldn't be queued). Phoenix replaced LangSmith only for runtime tracing: it has no annotation
queues, so reviewing generated eval data, datasets, and experiments stayed on LangSmith. The product owner decided that
one tool, Langfuse, manages the whole lifecycle: traces, ratings, annotation queues, datasets, experiments, and CI
evals. Langfuse's self-hosted edition is MIT-licensed and includes these.

Self-hosting needs Postgres, ClickHouse (at least 2 CPU and 8 GiB for production), Redis or Valkey, and S3. That
doesn't fit beside the app on the on-premise t3.large (ADR 0017 rejected Langfuse for this reason), and the product
owner wants other apps to use the same Langfuse later.

## Decision

- **Langfuse v4, self-hosted, on a host of its own:** a t3.xlarge (4 vCPU, 16 GiB) running web, worker, ClickHouse,
  Postgres, Valkey, and Caddy with Docker Compose; files in an S3 bucket through the instance role; a 100 GiB data
  volume with daily snapshots kept 7 days.
- **Its own CDK project, `platform/langfuse`**, with the stack `Langfuse-Host`. It never references Smart Tutor's
  stacks, parameters, or secrets, and Smart Tutor never references it: apps reach it over HTTPS with a per-project API
  key. The folder can move to a repository of its own.
- **Access:** sign-up is off; headless initialization creates the first admin from Secrets Manager, who invites others.
- **Hours:** the same off-hours schedule as the app host (ADR 0022). Neither host needs the other to start.
- **Not decided here (the Langfuse migration):** moving Smart Tutor's tracing and ratings from Phoenix and its evals
  from LangSmith; the 180-day trace retention (D25), since Langfuse lists data-retention policies among its Enterprise
  features when self-hosted; and where CI reaches Langfuse at night, when it is off.

## Alternatives rejected

- **Langfuse on the app host:** needs about 20 GiB with the app, so a 32 GiB host (r7i.xlarge, about $193 a month
  always on); it ties Langfuse to one app.
- **Langfuse Cloud:** no host to run, but learners' questions in traces would go to a third party, which needs a
  privacy decision first.
- **Keep Phoenix and LangSmith:** two tools, and LangSmith's free cap keeps blocking evals.

## Consequences

- A second host (about $55 a month at 11 hours a day, plus its volume and Elastic IP) and a second deploy to run by
  hand (`docs/runbooks/langfuse-host.md`).
- Traces, scores, and datasets live on that host; a lost volume loses up to a day (snapshots), and there is no
  database dump.
- Evals and CI that use Langfuse work only while it runs (07:00–18:00).
```

- [ ] **Step 2: ADR index and 0017.** In `sdd/adr/README.md`, add the 0021 row above the 0022 row:

```
| [0021](0021-langfuse-on-a-shared-host.md) | Langfuse manages observability and evaluation (traces, ratings, annotation queues, datasets, experiments), self-hosted on a shared t3.xlarge in its own CDK project `platform/langfuse` (supersedes 0017's choice of Phoenix and its "evals stay on LangSmith") |
```

In `sdd/adr/0017-self-hosted-phoenix-for-runtime-tracing.md`, change `- Status: accepted` to `- Status: accepted; its choice of tool is superseded by 0021 (Phoenix runs until the Langfuse migration lands)`.

- [ ] **Step 3: Runbook** `docs/runbooks/langfuse-host.md`:

````markdown
# Langfuse host (ADR 0021, ADR 0022)

A self-hosted Langfuse v4 on its own EC2 VM, shared by any app. Code: `platform/langfuse` (stack `Langfuse-Host`, Compose bundle in `deploy/`). It runs 07:00–18:00 Asia/Ho_Chi_Minh like the app host.

Commands are for **PowerShell 7** with AWS credentials for the account (`on-premise-deploy.md` §1) and:

```powershell
function Get-LangfuseOutput($Key) {
    aws cloudformation describe-stacks --stack-name Langfuse-Host `
        --query "Stacks[0].Outputs[?OutputKey=='$Key'].OutputValue" --output text
}
```

## 1. First deploy

1. Optional, a DuckDNS name: create one on duckdns.org (for example `<team>-langfuse`), set `langfuse:domain` in `platform/langfuse/cdk.json` to `<name>.duckdns.org`, and store the account's token (the same one as Smart Tutor's) after step 2: `aws secretsmanager create-secret --name langfuse/duckdns-token --secret-string <token>`. Without a domain, the URL is `https://<Elastic IP>.sslip.io`.
2. Deploy the stack:

   ```powershell
   Push-Location platform/langfuse
   uv sync
   npx aws-cdk@latest diff
   npx aws-cdk@latest deploy --require-approval broadening
   Pop-Location
   $InstanceId = Get-LangfuseOutput InstanceId; $Url = Get-LangfuseOutput PublicUrl
   ```

3. Wait until SSM lists the instance `Online` (2–3 minutes): `aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$InstanceId" --query "InstanceInformationList[0].PingStatus" --output text`.
4. Run the deploy document (section 3). The first start takes a few minutes while Langfuse migrates its databases.
5. Sign in at `$Url` as the admin: `aws secretsmanager get-secret-value --secret-id langfuse/admin --query SecretString --output text` (email and password; don't paste them anywhere else). Change the password in the UI if you like; the secret is only read for the first start.
6. Confirm the `langfuse-alerts` subscription email.

## 2. Add a person

Sign-up is off. In Langfuse, invite the person (organization **Platform** → Members). Then let them create their account:

```powershell
aws ssm put-parameter --name /langfuse/host/allow-signup --value true --overwrite
# Run the deploy document (section 3); the person signs up with the invited email.
aws ssm put-parameter --name /langfuse/host/allow-signup --value false --overwrite
# Run the deploy document again.
```

A `cdk deploy` also sets it back to `false`.

## 3. Deploy or upgrade

`cdk deploy` uploads `platform/langfuse/deploy/` as a bundle; the document copies it to the VM and runs `deploy.sh`:

```powershell
$Command = aws ssm send-command --document-name langfuse-deploy --instance-ids $InstanceId --query Command.CommandId --output text
aws ssm wait command-executed --command-id $Command --instance-id $InstanceId
aws ssm get-command-invocation --command-id $Command --instance-id $InstanceId --query "{Status: Status, Output: StandardOutputContent, Errors: StandardErrorContent}"
```

To upgrade Langfuse, change the two `langfuse/*:4.x.y` tags in `deploy/compose.yaml` (read Langfuse's release notes first; both must match), run the tests, `cdk deploy`, then run the document. Deploy before 17:30, or start the host first.

## 4. Hours, starting by hand

Same as the app host (`on-premise-monitoring.md`, Hours), with the group `langfuse-off-hours`: stopped at 18:00 and 00:00, started at 07:00. Start it at any hour with `aws ec2 start-instances --instance-ids $InstanceId`; Langfuse is back within a few minutes. The app host doesn't need it to run.

## 5. Patching and health

Weekly on Sunday 07:20 (`langfuse-patching`), then `ensure-healthy.sh`; a failure emails `langfuse-alerts`. To bring services back by hand:

```powershell
aws ssm send-command --document-name AWS-RunShellScript --instance-ids $InstanceId --parameters 'commands=["bash /opt/langfuse/ensure-healthy.sh"]'
```

No alarm watches Langfuse (ADR 0022): open `$Url` when in doubt.

## 6. Restore from a snapshot

Snapshots of the data volume are taken daily at 02:00 and kept 7 days (**EC2 → Snapshots**, tag `langfuse:snapshots`). To restore: set `langfuse:data-snapshot-id` in `cdk.json` to the snapshot id and `cdk deploy`. That creates a volume from the snapshot and replaces the instance, whose first boot attaches it; then run the deploy document. Keep the secrets: `encryption-seed` in particular must be the one the data was written with.

## 7. Tear down

`npx aws-cdk@latest destroy Langfuse-Host` (from `platform/langfuse`). The data volume leaves a final snapshot, and the bucket is kept (delete it by hand when sure). The secrets are scheduled for deletion with a recovery window, so a new stack can't reuse their names until they are restored or deleted for good.
````

- [ ] **Step 4: `AGENTS.md`**: in the repository map, after the `infra/` row add `| `platform/langfuse/` | Shared, self-hosted Langfuse: its own AWS CDK project (uv), stack `Langfuse-Host`, and the Compose bundle its VM runs (ADR 0021) |`. In Checks, after the `infra` line add `cd platform/langfuse && uv run pytest              # when platform/langfuse changed`. Update `sdd/adr/` (0001–0022) if it isn't already.

- [ ] **Step 5: Structure spec** `sdd/specs/2026-10-02-project-structure-design.md`: where the top-level folders are listed, add `platform/` with the line `platform/langfuse/ — shared, self-hosted Langfuse (own CDK project and Compose bundle; ADR 0021). Never imported by backend/, web/, or infra/.` in the same format as the neighboring entries.

- [ ] **Step 6: PRD (v2.63 → v2.64)** in `sdd/prd.md`: status line `Draft v2.63` → `Draft v2.64`; insert above the `| **Changes from v2.62** |` row:

```
| **Changes from v2.63** | Langfuse host (ADR 0021, §9.12): a shared, self-hosted Langfuse v4 runs on its own t3.xlarge from its own CDK project (`platform/langfuse`), with the same 07:00–18:00 hours. Nothing in Smart Tutor uses it yet: the Langfuse migration moves tracing, ratings, and evals to it. No product behavior changes. |
```

and in §9.12, after the on-premise mode bullet's sub-bullets, add a bullet: `- **Langfuse host (shared):** a separate CDK project (`platform/langfuse`, stack `Langfuse-Host`) runs self-hosted Langfuse on its own EC2 VM for any app (ADR 0021). Smart Tutor doesn't use it until the Langfuse migration.`

- [ ] **Step 7: Run all checks**

Run: `cd infra && uv run pytest -q`, `cd platform/langfuse && uv run pytest -q`, `helm lint deploy/helm/smart-tutor`
Expected: all pass.

- [ ] **Step 8: Commit, push, open PR 2**

```bash
git add sdd docs/runbooks/langfuse-host.md AGENTS.md
git commit -m "Document the shared Langfuse host (ADR 0021)" -m "Records the product owner's choice of Langfuse for observability and evaluation, why it gets its own host and CDK project, and how to deploy, open sign-up, start, patch, and restore it." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push -u origin langfuse-host
gh pr create --title "Add a shared, self-hosted Langfuse host" --body-file <body>
```

The PR body lists the spec, plan, ADR 0021, what the stack creates, the by-hand checks of Task 10 as an unchecked list, the cost (about $55 a month at 11 hours a day plus about $11 for the volume and Elastic IP), and ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

### Task 10: Deploy the Langfuse host and check by hand (operator, AWS)

- [ ] **Step 1:** Runbook §1 (first deploy) with `cdk diff` first.
- [ ] **Step 2:** The admin signs in at `$Url`; the organization **Platform** with the project **Sandbox** exists.
- [ ] **Step 3:** Send one trace with the Sandbox keys (derived by `deploy.sh`; read them in the UI under the project's API keys) using the Langfuse Python SDK from a laptop, and see it in the UI within a minute. An object appears under `events/` in the bucket (the instance-role check).
- [ ] **Step 4:** After 18:00 the instance is stopped; after 07:00 Langfuse answers within 5 minutes. Started by hand in the evening, it works, and the 00:00 stop stops it.
- [ ] **Step 5:** With the app host stopped, Langfuse works; with Langfuse stopped, the app host's chat works.
- [ ] **Step 6:** Record the results in PR 2; merge (squash) once CI is green and the person approves.
