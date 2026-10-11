# Teardown keeps the other mode running — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An operator can tear down either deployment mode completely while the other keeps running, and an infra test keeps the modes from reaching each other's resources (#207).

**Architecture:** #206 already gave each mode its own registry, made native-cloud's teardown delete its `Registry`, and inverted the shared-registry test. This plan adds what is left: (1) a generic isolation test that synthesizes both modes and fails on any cross-mode name, import, or IAM grant except the GitHub OIDC provider; (2) the native-cloud teardown script prints why it keeps each stack and is pinned by a test to native-cloud names only; (3) a repository variable `ON_PREMISE_AUTO_DEPLOY` so merges stop deploying on-premise while it is torn down (it mirrors `NATIVE_CLOUD_AUTO_DEPLOY`; without it every merge after a full teardown fails, or redeploys stacks mid-teardown); (4) a full-mode teardown section in the on-premise runbook.

**Tech Stack:** AWS CDK v2 (Python), pytest, PowerShell 7 runbook script, GitHub Actions YAML, Markdown runbooks.

**Spec:** GitHub issue #207 (parent #145); PRD §9.11–§9.12; ADR 0012; ADR 0016 (`sdd/adr/0016-deployment-modes-share-no-stack.md`).

## Global Constraints

- Native-cloud names: stacks `SmartTutor-prod-*`, data prefix `smart-tutor` (`smart-tutor/<service>`, `/smart-tutor/...`, `smart-tutor-documents-<account>`). On-premise: stacks `SmartTutor-OnPremise-prod-*`, data prefix `smart-tutor-on-premise`. Source: `infra/smart_tutor_infra/names.py`.
- The only resource the modes share is the account's GitHub OIDC provider (plus `CDKToolkit`, which no mode's templates own). ADR 0016.
- The native-cloud teardown deletes nothing whose name starts with `SmartTutor-OnPremise-` or `smart-tutor-on-premise`.
- The on-premise full-mode teardown section never names a native-cloud stack (no `SmartTutor-prod-` in it).
- A product-behavior change updates `sdd/prd.md` and bumps its version (v2.40 → v2.41), and `AGENTS.md`'s PRD row follows.
- Checks: `cd infra && uv run pytest` passes. Windows: run with `JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1`; a full synth of both modes takes about 2 minutes.
- Commit subjects in the imperative mood; the body says why; end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- A VM filesystem path such as `/opt/smart-tutor/on-premise/deploy.sh` in on-premise's SSM document must not count as a reference to native-cloud's `smart-tutor/` secrets or repositories (Task 1 matches those namespaces in ARN form; the clean-run test pins it).
- Native-cloud's `smart-tutor-*` names are prefixes of on-premise's strings only with a `-on-premise` between; the name boundary in Task 1 must not flag `smart-tutor-on-premise-ingest` as `smart-tutor-ingest` (pinned by the clean-run tests).
- An IAM `Resource: "*"` (actions without resource-level permissions) must not count as a cross-mode grant (Task 1 skips it; clean-run tests pin it).
- `-DeleteBudget` moves the Budgets stack from KEEP to DELETE; the keep list must not still print it (Task 2 test).
- `ON_PREMISE_AUTO_DEPLOY` unset must keep today's behavior (on-premise deploys on every push); only the exact value `false` turns it off (Task 3 test pins the condition string).

---

## File Structure

- Create `infra/tests/test_mode_isolation.py` — the cross-mode isolation guard (Task 1).
- Modify `docs/runbooks/pilot-teardown.ps1`, `docs/runbooks/pilot-teardown.md`, `infra/tests/test_workflows.py` — keep reasons, native-only names (Task 2).
- Modify `.github/workflows/deploy.yml`, `infra/tests/test_workflows.py`, `sdd/prd.md`, `AGENTS.md`, `docs/runbooks/on-premise-deploy.md` §3, `docs/architecture/solution-architecture.md`, `README.md` — `ON_PREMISE_AUTO_DEPLOY` (Task 3).
- Modify `docs/runbooks/on-premise-deploy.md` §8, `infra/tests/test_workflows.py` — full-mode teardown (Task 4).

---

### Task 1: Cross-mode isolation guard

**Files:**
- Create: `infra/tests/test_mode_isolation.py`

**Interfaces:**
- Consumes: `build_app` (`smart_tutor_infra.app_stacks`), `mode_names`, `NATIVE_CLOUD`, `ON_PREMISE` (`smart_tutor_infra.names`), `make_app` (`tests.test_synth`).
- Produces: nothing later tasks use.

- [ ] **Step 1: Create the test module** with exactly this content (it was prototyped against today's stacks: 9 tests pass):

```python
"""Neither deployment mode's stacks create, import, or grant access to the other mode's resources (#207, ADR 0016).

Both modes are synthesized. What a mode owns is its namespace from ModeNames (stack prefix, bucket, queues, SSM path,
secret prefix, ECR repository prefix, deploy role) plus what its templates create: stack names, exports, and the fixed
names of its named resources. A stack of one mode fails the check if any string in its template (user data included)
names something the other mode owns, if it imports one of the other mode's exports, or if one of its IAM statements
allows a resource ARN or wildcard that matches one of the other mode's resources.

The one exception is the account's GitHub OIDC provider. AWS allows one provider per URL in an account, so native-cloud's
GitHubDeploy creates it and on-premise's imports it by ARN. Native-cloud's teardown keeps GitHubDeploy for that reason
(docs/runbooks/pilot-teardown.md), and on-premise's teardown leaves the provider alone.
"""

import copy
import functools
import re
from collections.abc import Iterator
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

import pytest
from aws_cdk.assertions import Template

from smart_tutor_infra.app_stacks import build_app
from smart_tutor_infra.names import NATIVE_CLOUD, ON_PREMISE, mode_names
from tests.test_synth import make_app

ACCOUNT, REGION = "123456789012", "us-east-1"
PSEUDO = {"AWS::AccountId": ACCOUNT, "AWS::Region": REGION, "AWS::Partition": "aws", "AWS::URLSuffix": "amazonaws.com"}
TOKEN = "\x00"  # stands in for a value known only at deploy time; it matches no name
OIDC_PROVIDER = f"arn:aws:iam::{ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"

# Named resource types: the property that holds the fixed name, and the ARNs IAM would grant on it.
NAMED: dict[str, tuple[tuple[str, ...], list[str]]] = {
    "AWS::S3::Bucket": (("BucketName",), ["arn:aws:s3:::{name}", "arn:aws:s3:::{name}/key"]),
    "AWS::SQS::Queue": (("QueueName",), [f"arn:aws:sqs:{REGION}:{ACCOUNT}:{{name}}"]),
    "AWS::SNS::Topic": (("TopicName",), [f"arn:aws:sns:{REGION}:{ACCOUNT}:{{name}}"]),
    "AWS::ECR::Repository": (("RepositoryName",), [f"arn:aws:ecr:{REGION}:{ACCOUNT}:repository/{{name}}"]),
    "AWS::SSM::Parameter": (("Name",), [f"arn:aws:ssm:{REGION}:{ACCOUNT}:parameter{{name}}"]),
    "AWS::SSM::Document": (("Name",), [f"arn:aws:ssm:{REGION}:{ACCOUNT}:document/{{name}}"]),
    # Secrets Manager appends six random characters to a secret's ARN.
    "AWS::SecretsManager::Secret": (("Name",), [f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:{{name}}-AbCdEf"]),
    "AWS::IAM::Role": (("RoleName",), [f"arn:aws:iam::{ACCOUNT}:role/{{name}}"]),
    "AWS::IAM::OIDCProvider": (("Url",), [f"arn:aws:iam::{ACCOUNT}:oidc-provider/{{name}}"]),
    "AWS::EKS::Cluster": (("Name",), [f"arn:aws:eks:{REGION}:{ACCOUNT}:cluster/{{name}}"]),
    "AWS::RDS::DBInstance": (("DBInstanceIdentifier",), [f"arn:aws:rds:{REGION}:{ACCOUNT}:db:{{name}}"]),
    "AWS::Budgets::Budget": (("Budget", "BudgetName"), [f"arn:aws:budgets::{ACCOUNT}:budget/{{name}}"]),
    "AWS::Logs::LogGroup": (("LogGroupName",), [f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:{{name}}"]),
}


def render(value: Any) -> str:
    """A template value as the string it deploys as; deploy-time values become TOKEN."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and len(value) == 1:
        ((key, arg),) = value.items()
        if key == "Ref" and arg in PSEUDO:
            return PSEUDO[arg]
        if key == "Fn::Join":
            separator, parts = arg
            return render(separator).join(render(part) for part in parts)
        if key == "Fn::Sub":
            text = arg if isinstance(arg, str) else arg[0]
            return re.sub(r"\$\{([^}]+)\}", lambda m: PSEUDO.get(m.group(1), TOKEN), text)
        if key == "Fn::Base64":
            return render(arg)
    return TOKEN


def strings(node: Any) -> Iterator[str]:
    """Every string value in a template, with joins and substitutions rendered whole."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, list):
        for item in node:
            yield from strings(item)
    elif isinstance(node, dict):
        if len(node) == 1 and next(iter(node)) in ("Fn::Join", "Fn::Sub", "Fn::Base64"):
            yield render(node)
        for item in node.values():
            yield from strings(item)


def imports(node: Any) -> Iterator[str]:
    if isinstance(node, list):
        for item in node:
            yield from imports(item)
    elif isinstance(node, dict):
        if "Fn::ImportValue" in node:
            yield render(node["Fn::ImportValue"])
        for item in node.values():
            yield from imports(item)


def allowed_resources(node: Any) -> Iterator[str]:
    """The Resource of every Allow statement: identity policies, inline role policies, and resource policies."""
    if isinstance(node, list):
        for item in node:
            yield from allowed_resources(item)
    elif isinstance(node, dict):
        if node.get("Effect") == "Allow" and "Resource" in node:
            resources = node["Resource"]
            for resource in resources if isinstance(resources, list) else [resources]:
                yield render(resource)
        for item in node.values():
            yield from allowed_resources(item)


@functools.cache
def _synth(mode: str) -> dict[str, dict[str, Any]]:
    return {s.stack_name: Template.from_stack(s).to_json() for s in build_app(make_app(**{"smart-tutor:mode": mode}))}


def synth(mode: str) -> dict[str, dict[str, Any]]:
    """The mode's templates by stack name; a copy, so a test can change it."""
    return copy.deepcopy(_synth(mode))


@dataclass(frozen=True)
class Owned:
    names: frozenset[str]  # matched in any string of the other mode's templates
    arns: frozenset[str]  # matched against the other mode's IAM resources
    exports: frozenset[str]


def owned(mode: str) -> Owned:
    n = mode_names(mode)
    # The namespace: what the mode may create later, or creates by hand (the DuckDNS secret), is still its own.
    # Secrets and repositories share the prefix `smart-tutor/` with paths on the VM (/opt/smart-tutor/...), so their
    # namespace is matched in ARN form; the names the templates create are matched as they are.
    names = {
        f"{n.stack_prefix}-",
        f"{n.ssm_path}/",
        f"secret:{n.secret_prefix}/",
        f"repository/{n.repository_prefix}/",
        n.deploy_role,
        n.documents_bucket(ACCOUNT),
        n.ingest_queue,
        n.ingest_dlq,
        n.deploy_document,
    }
    arns = {
        f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{n.stack_prefix}-Any/guid",
        f"arn:aws:ssm:{REGION}:{ACCOUNT}:parameter{n.ssm_path}/any",
        f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:{n.secret_prefix}/any-AbCdEf",
        f"arn:aws:ecr:{REGION}:{ACCOUNT}:repository/{n.repository('any')}",
        f"arn:aws:iam::{ACCOUNT}:role/{n.deploy_role}",
        f"arn:aws:s3:::{n.documents_bucket(ACCOUNT)}",
        f"arn:aws:s3:::{n.documents_bucket(ACCOUNT)}/key",
        f"arn:aws:sqs:{REGION}:{ACCOUNT}:{n.ingest_queue}",
        f"arn:aws:sqs:{REGION}:{ACCOUNT}:{n.ingest_dlq}",
        f"arn:aws:ssm:{REGION}:{ACCOUNT}:document/{n.deploy_document}",
    }
    exports: set[str] = set()
    for stack, template in _synth(mode).items():
        names.add(stack)
        arns.add(f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{stack}/guid")
        for output in template.get("Outputs", {}).values():
            if "Export" in output:
                exports.add(render(output["Export"]["Name"]))
        for resource in template.get("Resources", {}).values():
            if resource["Type"] == "AWS::EC2::Instance":
                # No fixed name, but a grant on the other mode's instances is still a grant.
                arns.add(f"arn:aws:ec2:{REGION}:{ACCOUNT}:instance/i-0123456789abcdef0")
                continue
            if resource["Type"] not in NAMED:
                continue
            path, arn_formats = NAMED[resource["Type"]]
            value: Any = resource.get("Properties", {})
            for key in path:
                value = value.get(key) if isinstance(value, dict) else None
            name = render(value) if value is not None else TOKEN
            if TOKEN in name:
                continue  # CDK generates the name at deploy time; no other stack can know it
            if resource["Type"] == "AWS::IAM::OIDCProvider":
                # Its URL also starts the trust conditions' keys (token.actions.githubusercontent.com:sub), so the
                # provider is named by its ARN.
                arn = arn_formats[0].format(name=name.removeprefix("https://"))
                names.add(arn)
                arns.add(arn)
                continue
            names.add(name)
            arns.update(f.format(name=name) for f in arn_formats)
    names.update(exports)
    return Owned(frozenset(names), frozenset(arns), frozenset(exports))


def _name_pattern(names: frozenset[str]) -> re.Pattern[str]:
    # A name must not be part of a longer name: native-cloud's `smart-tutor-ingest` is not in on-premise's
    # `smart-tutor-on-premise-ingest`. A prefix that ends in `-` or `/` is open on the right.
    parts = [re.escape(n) + ("" if n[-1] in "-/" else "(?![A-Za-z0-9-])") for n in sorted(names, key=len, reverse=True)]
    return re.compile(r"(?<![A-Za-z0-9-])(" + "|".join(parts) + ")")


def violations(templates: dict[str, dict[str, Any]], other: Owned) -> list[str]:
    """Each way the templates reach the other mode's resources, as `<stack> <how>`."""
    pattern = _name_pattern(other.names)
    found = set()
    for stack, template in templates.items():
        for text in strings(template):
            found.update(f"{stack} names {m.group(1)!r}" for m in pattern.finditer(text))
        found.update(f"{stack} imports {name!r}" for name in imports(template) if name in other.exports)
        for resource in allowed_resources(template):
            if resource == "*":
                continue  # only actions without resource-level permissions use it (ecr:GetAuthorizationToken, ...)
            found.update(f"{stack} allows {resource!r}" for arn in other.arns if fnmatchcase(arn, resource))
    return sorted(found)


def test_native_cloud_reaches_nothing_of_on_premise() -> None:
    assert violations(synth(NATIVE_CLOUD), owned(ON_PREMISE)) == []


def test_on_premise_reaches_only_the_github_oidc_provider_of_native_cloud() -> None:
    # The allowed exception (module docstring): on-premise's deploy role trusts the provider native-cloud created.
    assert violations(synth(ON_PREMISE), owned(NATIVE_CLOUD)) == [
        f"SmartTutor-OnPremise-prod-GitHubDeploy names {OIDC_PROVIDER!r}"
    ]


def _allow(resource: Any) -> dict[str, Any]:
    statement = {"Effect": "Allow", "Action": "*", "Resource": resource}
    return {"Type": "AWS::IAM::ManagedPolicy", "Properties": {"PolicyDocument": {"Statement": [statement]}}}


def _parameter(value: Any) -> dict[str, Any]:
    return {"Type": "AWS::SSM::Parameter", "Properties": {"Type": "String", "Value": value}}


SHARED_REFERENCES = {
    "on-premise pushes to native-cloud's repositories": (
        ON_PREMISE,
        "SmartTutor-OnPremise-prod-GitHubDeploy",
        _allow({"Fn::Join": ["", ["arn:aws:ecr:", {"Ref": "AWS::Region"}, ":", {"Ref": "AWS::AccountId"},
                                  ":repository/smart-tutor/*"]]}),
    ),
    "on-premise pulls a native-cloud image": (
        ON_PREMISE,
        "SmartTutor-OnPremise-prod-Host",
        _parameter(f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/smart-tutor/api:0123abc"),
    ),
    "an on-premise glob too wide for its SSM path": (
        ON_PREMISE, "SmartTutor-OnPremise-prod-Host", _allow("arn:aws:ssm:us-east-1:*:parameter/smart-tutor*")
    ),
    "on-premise imports a native-cloud export": (
        ON_PREMISE,
        "SmartTutor-OnPremise-prod-Storage",
        _parameter({"Fn::ImportValue": "SmartTutor-prod-Edge:ExportsOutputFnGetAttDistribution830FAC52DomainNameBEB09E30"}),
    ),
    "native-cloud reads on-premise's secrets": (
        NATIVE_CLOUD, "SmartTutor-prod-Cluster", _allow("arn:aws:secretsmanager:us-east-1:*:secret:smart-tutor-on-premise/*")
    ),
    "native-cloud names on-premise's queue": (
        NATIVE_CLOUD, "SmartTutor-prod-Config", _parameter("smart-tutor-on-premise-ingest")
    ),
    "native-cloud acts on on-premise's deploy role": (
        NATIVE_CLOUD, "SmartTutor-prod-GitHubDeploy", _allow("arn:aws:iam::*:role/smart-tutor-on-premise-github-deploy")
    ),
}


@pytest.mark.parametrize(("mode", "stack", "resource"), SHARED_REFERENCES.values(), ids=SHARED_REFERENCES.keys())
def test_a_shared_reference_fails_the_check(mode: str, stack: str, resource: dict[str, Any]) -> None:
    other = owned(NATIVE_CLOUD if mode == ON_PREMISE else ON_PREMISE)
    templates = synth(mode)
    before = set(violations(templates, other))
    templates[stack]["Resources"]["SharedReference"] = resource

    added = set(violations(templates, other)) - before

    assert added and all(v.startswith(f"{stack} ") for v in added), added
```

- [ ] **Step 2: Run it**

Run: `cd infra && JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1 uv run pytest tests/test_mode_isolation.py -q`
Expected: 9 passed (2 clean-run tests, 7 shared-reference cases).

- [ ] **Step 2b: Format** like the rest of `infra/`: `uvx ruff format --line-length 120 tests/test_mode_isolation.py` and `uvx ruff check --line-length 120 tests/test_mode_isolation.py` (fix anything it reports; rerun Step 2).

- [ ] **Step 3: See it fail against a deliberately shared reference in real code**

In `infra/smart_tutor_infra/stacks/github_deploy.py`, temporarily change the `EcrPushAppImages` resource from `repository/{names.repository_prefix}/*` to `repository/smart-tutor/*`. Run:
`uv run pytest tests/test_mode_isolation.py -q -k on_premise_reaches_only`
Expected: FAIL, the list includes `"SmartTutor-OnPremise-prod-GitHubDeploy allows 'arn:aws:ecr:us-east-1:123456789012:repository/smart-tutor/*'"`. Revert the change with `git checkout -- infra/smart_tutor_infra/stacks/github_deploy.py` and confirm `git status` shows only the new test file. Record the failure line for the PR description.

- [ ] **Step 4: Commit**

```bash
git add infra/tests/test_mode_isolation.py
git commit -m "Fail CI when one deployment mode reaches the other's resources (#207)" -m "Synthesizes both modes and fails if a stack names, imports, or grants access to the other mode's stacks, exports, repositories, bucket, queues, SSM paths, secrets, or deploy role. The account's GitHub OIDC provider is the one allowed exception (ADR 0016). Parametrized shared references prove the check bites." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Native-cloud teardown says why it keeps each stack and touches only native-cloud names

**Files:**
- Modify: `docs/runbooks/pilot-teardown.ps1` (header `.DESCRIPTION`, `$KeepStacks` near line 51, the KEEP print near line 168, the final `Done.` line)
- Modify: `docs/runbooks/pilot-teardown.md` (§2 table and the paragraph after it, §4)
- Test: `infra/tests/test_workflows.py` (append after `test_runbooks_no_longer_call_ecr_shared_and_explain_old_rollbacks`)

**Interfaces:** none.

- [ ] **Step 1: Write the failing tests** (append to `infra/tests/test_workflows.py`; `re`, `RUNBOOKS`, `mode_names`, `ON_PREMISE` are already imported):

```python
def test_native_cloud_teardown_touches_only_native_cloud_names_and_says_why_it_keeps_stacks() -> None:
    script = (RUNBOOKS / "pilot-teardown.ps1").read_text(encoding="utf-8")
    on_premise = mode_names(ON_PREMISE)
    # The names the script deletes: stacks, secrets, log groups, and the cluster (whose id also names the snapshots).
    names = script.split("$ClusterName =")[1].split("# The script runs in your PowerShell session")[0]
    literals = re.findall(r'"([^"]*)"', names)
    assert "/aws/eks/smart-tutor-prod" in literals and "smart-tutor/rds/master" in literals
    for literal in literals:
        assert not re.search(rf"(^|/)({on_premise.stack_prefix}|{on_premise.data_prefix})", literal), literal
    assert "starts_with(StackName,'SmartTutor-prod-')" in script
    assert '$Bucket = "smart-tutor-documents-$AccountId"' in script
    # Each kept stack comes with the reason the dry run prints; GitHubDeploy is kept for the OIDC provider (ADR 0016).
    keep = script.split("$KeepStacks = [ordered]@{")[1].split("}")[0]
    assert re.search(r'"SmartTutor-prod-GitHubDeploy"\s*=\s*"[^"]*GitHub OIDC provider[^"]*on-premise', keep)
    assert re.search(r'"CDKToolkit"\s*=\s*"[^"]+"', keep)
    assert "SmartTutor-prod-Budgets" not in keep  # kept only without -DeleteBudget
    assert re.search(r'if \(-not \$DeleteBudget\) \{ \$KeepStacks\["SmartTutor-prod-Budgets"\] = "[^"]+" \}', script)
    assert "$KeepStacks.GetEnumerator()" in script


def test_native_cloud_teardown_runbook_leaves_on_premise_alone() -> None:
    text = (RUNBOOKS / "pilot-teardown.md").read_text(encoding="utf-8")
    assert "account's only budget" not in text  # on-premise has a budget of its own
    assert "`SmartTutor-OnPremise-`" in text and "on-premise-deploy.md" in text
    assert "with the reason" in text  # the dry run explains each kept stack
    leftovers = text.split("## 7.")[1].split("## 8.")[0]
    assert "ECR" not in leftovers and "image" not in leftovers.lower()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd infra && uv run pytest tests/test_workflows.py -q -k "touches_only_native_cloud or leaves_on_premise_alone"`
Expected: FAIL (`$KeepStacks = [ordered]@{` not found; `account's only budget` still in the runbook).

- [ ] **Step 3: Change the script**

In `docs/runbooks/pilot-teardown.ps1`:

a) In `.DESCRIPTION`, replace the "Kept on purpose" sentence with:

```
    Kept on purpose, and the dry run says why: SmartTutor-prod-GitHubDeploy (it owns the account's GitHub OIDC provider,
    which on-premise's deploy role imports: the one resource the modes share, ADR 0016), CDKToolkit, and
    SmartTutor-prod-Budgets (free) unless -DeleteBudget. It deletes nothing of on-premise (SmartTutor-OnPremise-*,
    smart-tutor-on-premise*), which keeps running. Safe to run again after a partial failure: it skips what is gone.
```

b) Replace

```powershell
$KeepStacks = @("SmartTutor-prod-GitHubDeploy", "CDKToolkit") +
    @(if (-not $DeleteBudget) { "SmartTutor-prod-Budgets" })
```

with

```powershell
# Kept on purpose, with the reason the run prints. GitHubDeploy is the accepted exception to "the modes share no
# stack" (ADR 0016). Every name this script deletes is native-cloud's; none starts with SmartTutor-OnPremise- or
# smart-tutor-on-premise (#207).
$KeepStacks = [ordered]@{
    "SmartTutor-prod-GitHubDeploy" = "owns the account's GitHub OIDC provider, which on-premise's deploy role imports (ADR 0016)"
    "CDKToolkit"                   = "the account's CDK bootstrap, which both modes deploy with"
}
if (-not $DeleteBudget) { $KeepStacks["SmartTutor-prod-Budgets"] = "the budget smart-tutor-prod-monthly is free; -DeleteBudget deletes it" }
```

c) Replace `Write-Host "Will KEEP:   $($KeepStacks -join ', ')" -ForegroundColor Green` with

```powershell
    Write-Host "Will KEEP:" -ForegroundColor Green
    foreach ($Keep in $KeepStacks.GetEnumerator()) { Write-Host ("  {0,-34} {1}" -f $Keep.Key, $Keep.Value) -ForegroundColor Green }
```

d) In the final line, replace `"Done. Kept: $($KeepStacks -join ', ')."` with `"Done. Kept: $($KeepStacks.Keys -join ', ')."`.

If `pwsh` is available, parse-check the script without running it:
`pwsh -NoProfile -Command "$null = [System.Management.Automation.Language.Parser]::ParseFile('docs/runbooks/pilot-teardown.ps1', [ref]$null, [ref]$e); $e"` — expected: no output.

- [ ] **Step 4: Change the runbook** `docs/runbooks/pilot-teardown.md`:

a) In the §2 table, replace the three Kept rows with:

```
| Kept | `Budgets` | The budget `smart-tutor-prod-monthly` is free. `-DeleteBudget` deletes it. |
| Kept | `GitHubDeploy` | It owns the account's GitHub OIDC provider, which on-premise's deploy role imports: the one resource the two modes share (ADR 0016). IAM only, free. |
| Kept | `CDKToolkit` and the GitHub environment `native-cloud` | The bootstrap is the account's, and both modes deploy with it; the environment lets the pilot be redeployed. |
```

b) Directly after the table, add:

```
On-premise keeps running. The script deletes only native-cloud's names: the stacks `SmartTutor-prod-*`, the secrets `smart-tutor/...`, the log groups of `smart-tutor-prod`, the snapshots of the `smart-tutor-prod` database, and the bucket `smart-tutor-documents-<account>`. Nothing it deletes starts with `SmartTutor-OnPremise-` or `smart-tutor-on-premise`. To tear down on-premise instead, see [`on-premise-deploy.md`](on-premise-deploy.md) §8.
```

c) In §4, replace "It prints the stacks it would delete and keep," with "It prints the stacks it would delete, each stack it keeps with the reason,".

- [ ] **Step 5: Run the tests**

Run: `cd infra && uv run pytest tests/test_workflows.py -q`
Expected: all pass (including `test_runbooks_no_longer_call_ecr_shared_and_explain_old_rollbacks`).

- [ ] **Step 6: Commit**

```bash
git add docs/runbooks/pilot-teardown.ps1 docs/runbooks/pilot-teardown.md infra/tests/test_workflows.py
git commit -m "Say why native-cloud's teardown keeps each stack (#207)" -m "The dry run now prints the reason next to each kept stack: GitHubDeploy owns the GitHub OIDC provider on-premise imports, the one shared resource (ADR 0016). A test pins every name the script deletes to native-cloud's, and the runbook drops 'the account's only budget', which stopped being true when on-premise got its own." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `ON_PREMISE_AUTO_DEPLOY` stops merges from deploying on-premise

**Files:**
- Modify: `.github/workflows/deploy.yml` (header comment lines 1-5; `if:` of `images-on-premise` and `on-premise`)
- Modify: `infra/tests/test_workflows.py` (`ON_PREMISE_IF`, line 167; one new test)
- Modify: `sdd/prd.md` (status line 5, new "Changes from v2.40" row above line 6, §9.11 table row "Deployed", §9.12 Delivery bullet "On-premise")
- Modify: `AGENTS.md` (PRD row `(v2.40)` → `(v2.41)`)
- Modify: `docs/runbooks/on-premise-deploy.md` (intro line 3; §3 "What runs")
- Modify: `docs/architecture/solution-architecture.md` (row "2. Merge to `main`", line ~279)

**Interfaces:** Produces the variable name `ON_PREMISE_AUTO_DEPLOY` (value `false` turns pushes off; unset or anything else keeps them on), which Task 4's runbook section uses.

- [ ] **Step 1: Write the failing test.** In `infra/tests/test_workflows.py` change

```python
ON_PREMISE_IF = "github.event_name == 'push' || inputs.mode == 'on-premise'"
```

to

```python
# On-premise deploys on every push unless the variable is exactly `false` (while it is torn down, #207).
ON_PREMISE_IF = (
    "(github.event_name == 'push' && vars.ON_PREMISE_AUTO_DEPLOY != 'false') || inputs.mode == 'on-premise'"
)
```

and append:

```python
def test_the_on_premise_auto_deploy_switch_is_documented() -> None:
    for path in (RUNBOOKS / "on-premise-deploy.md", WORKFLOWS.parents[1] / "sdd/prd.md"):
        assert "ON_PREMISE_AUTO_DEPLOY" in path.read_text(encoding="utf-8"), path.name
    assert "ON_PREMISE_AUTO_DEPLOY" in (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8").split("name: deploy")[0]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd infra && uv run pytest tests/test_workflows.py -q -k "own_role_before_it_deploys or auto_deploy_switch"`
Expected: FAIL (the `if` differs; the variable is not documented).

- [ ] **Step 3: Change `deploy.yml`.** Both `images-on-premise` and `on-premise` get:

```yaml
    if: (github.event_name == 'push' && vars.ON_PREMISE_AUTO_DEPLOY != 'false') || inputs.mode == 'on-premise'
```

Replace the header's second line `# and its deploy. On-premise deploys on every push (PRD §9.12, ADR 0012, #150).` with:

```yaml
# and its deploy. On-premise deploys on every push (PRD §9.12, ADR 0012, #150) unless the repository variable
# ON_PREMISE_AUTO_DEPLOY is `false`, which an operator sets while on-premise is torn down (#207).
```

- [ ] **Step 4: Update the docs.**

a) `sdd/prd.md`: status line `Draft v2.40` → `Draft v2.41`. Insert above the `**Changes from v2.39**` row:

```
| **Changes from v2.40** | Tearing down one deployment mode leaves the other running (#207, ADR 0016). On-premise deploys on every merge unless the repository variable `ON_PREMISE_AUTO_DEPLOY` is `false`, which an operator sets while on-premise is torn down, so merges neither redeploy it nor fail. The on-premise runbook tears down the whole mode; native-cloud's teardown deletes its Registry and keeps only `GitHubDeploy` (the account's GitHub OIDC provider) and the bootstrap. An infra test fails if either mode's stacks create, import, or grant access to the other's resources. |
```

In the §9.11 deployment-modes table, the "Deployed" row's on-premise cell `On every merge to \`main\`` → `On every merge to \`main\`, unless \`ON_PREMISE_AUTO_DEPLOY=false\` (while it is torn down)`. In §9.12 Delivery, `- **On-premise**, on every merge to \`main\`:` → `- **On-premise**, on every merge to \`main\` unless \`ON_PREMISE_AUTO_DEPLOY=false\`:`.

b) `AGENTS.md`: `` `sdd/prd.md` (v2.40) `` → `` `sdd/prd.md` (v2.41) ``.

c) `docs/runbooks/on-premise-deploy.md` line 3: `Every merge to \`main\` deploys on-premise automatically (section 3).` → `Every merge to \`main\` deploys on-premise automatically, unless \`ON_PREMISE_AUTO_DEPLOY\` is \`false\` (section 3).` At the end of §3's **What runs.** paragraph, add:

```
**Stop deploys on merge** by setting the repository variable `ON_PREMISE_AUTO_DEPLOY` to `false`, for example while on-premise is torn down (section 8): `gh variable set ON_PREMISE_AUTO_DEPLOY --body false --repo konica/agent-tutor`. Unset or any other value deploys on every merge; `gh variable delete ON_PREMISE_AUTO_DEPLOY --repo konica/agent-tutor` turns it back on. A run by hand (`gh workflow run deploy.yml -f mode=on-premise`) deploys either way.
```

d) `docs/architecture/solution-architecture.md`, row "2. Merge to `main`": `builds the images, deploys on-premise, and calls` → `builds the images, deploys on-premise (unless \`ON_PREMISE_AUTO_DEPLOY\` is \`false\`), and calls`.

- [ ] **Step 5: Run the tests**

Run: `cd infra && uv run pytest tests/test_workflows.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/deploy.yml infra/tests/test_workflows.py sdd/prd.md AGENTS.md docs/runbooks/on-premise-deploy.md docs/architecture/solution-architecture.md
git commit -m "Let an operator stop merges from deploying on-premise (#207)" -m "Once on-premise is torn down, every merge would redeploy its deploy role and registry mid-teardown, or fail once the role is gone. ON_PREMISE_AUTO_DEPLOY=false skips the on-premise jobs on push, like NATIVE_CLOUD_AUTO_DEPLOY for native-cloud; unset keeps today's deploy on every merge. PRD v2.41." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: On-premise runbook tears down the whole mode

**Files:**
- Modify: `docs/runbooks/on-premise-deploy.md` §8 (currently lines ~266-274)
- Test: `infra/tests/test_workflows.py` (append)

**Interfaces:** Consumes `ON_PREMISE_AUTO_DEPLOY` from Task 3.

- [ ] **Step 1: Write the failing test** (append to `infra/tests/test_workflows.py`):

```python
def test_on_premise_runbook_tears_down_the_whole_mode_without_naming_native_cloud() -> None:
    text = (RUNBOOKS / "on-premise-deploy.md").read_text(encoding="utf-8")
    section = text.split("### Tear down the whole mode")[1].split("\n## ")[0]
    assert "SmartTutor-prod-" not in section
    assert 'destroy "SmartTutor-OnPremise-prod-*" -c smart-tutor:mode=on-premise' in section
    assert "gh variable set ON_PREMISE_AUTO_DEPLOY --body false" in section
    for stack in ("Host", "Registry", "Config", "Storage", "Budgets", "GitHubDeploy"):
        assert f"| Deleted | `{stack}`" in section, stack
    for kept in ("smart-tutor-on-premise-documents-", "final data-volume snapshot", "smart-tutor-on-premise/duckdns/token",
                 "GitHub OIDC provider"):
        assert kept in section, kept
    assert "native-cloud keeps running" in text.split("## 8. Tear down")[1].split("###")[0]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd infra && uv run pytest tests/test_workflows.py -q -k whole_mode`
Expected: FAIL (`### Tear down the whole mode` not found → IndexError).

- [ ] **Step 3: Rewrite §8.** Replace everything from `## 8. Tear down` up to (not including) `## 9. DuckDNS name (#154)` with the text below. Keep the existing Host paragraph word for word under `### Tear down the Host`. Before writing the "Redeploy later" sentence about passwords, confirm in `deploy/on-premise/deploy.sh` that a deploy sets the PostgreSQL roles' passwords from the secrets; if it doesn't, drop that clause.

````markdown
## 8. Tear down

Tear down the Host alone to stop paying for the VM and keep the rest, or the whole mode. Either way native-cloud keeps running: the modes share no stack (ADR 0016), and with `-c smart-tutor:mode=on-premise` the CDK app contains only `SmartTutor-OnPremise-prod-*` stacks.

### Tear down the Host

```powershell
Push-Location infra
npx aws-cdk@latest destroy SmartTutor-OnPremise-prod-Host -c smart-tutor:mode=on-premise
Pop-Location
```

<the existing paragraph "This deletes the VM, the Elastic IP, and the VPC. ... points the name at the new Elastic IP.", unchanged>

### Tear down the whole mode

Deletes every on-premise stack, in this order:

1. **Stop deploys on merge** (section 3). Otherwise the next merge's image build deploys the deploy role and the registry again, or fails once the role is gone. Wait until no deploy run is in progress:

   ```powershell
   gh variable set ON_PREMISE_AUTO_DEPLOY --body false --repo konica/agent-tutor
   gh run list --workflow deploy.yml --limit 5
   ```

2. **Note the data volume id.** Its snapshots outlive the stack:

   ```powershell
   aws cloudformation describe-stacks --stack-name SmartTutor-OnPremise-prod-Host `
       --query "Stacks[0].Outputs[?OutputKey=='DataVolumeId'].OutputValue" --output text
   ```

3. **Destroy the stacks** (about 10 min; it asks you to confirm):

   ```powershell
   Push-Location infra
   npx aws-cdk@latest destroy "SmartTutor-OnPremise-prod-*" -c smart-tutor:mode=on-premise
   Pop-Location
   ```

| | What | Notes |
|---|---|---|
| Deleted | `Host`: the VM, the Elastic IP, the VPC, the data volume (after a final snapshot), the snapshot policy, the alarms and alert topic, the uptime check, the patching window, the deploy document, and the database and test-learner secrets | |
| Deleted | `Registry`: the repositories `smart-tutor-on-premise/*` and their images | The next build recreates them, empty. |
| Deleted | `Config`: the SSM parameters under `/smart-tutor-on-premise/` and the Keycloak secrets | |
| Deleted | `Storage`: the queues `smart-tutor-on-premise-ingest` and `smart-tutor-on-premise-ingest-dlq` | The bucket stays (below). |
| Deleted | `Budgets`: the budget `smart-tutor-on-premise-prod-monthly` | |
| Deleted | `GitHubDeploy`: the role `smart-tutor-on-premise-github-deploy` | The role only imports the GitHub OIDC provider, so the provider stays. |
| Kept | The documents bucket `smart-tutor-on-premise-documents-<account>` | Learner PDFs, and the nightly dumps under `backups/`, which still expire after 30 days. The stack retains it. |
| Kept | The final data-volume snapshot and the daily snapshots (up to 7) | The database, Keycloak's users, and Caddy's certificates. Data Lifecycle Manager leaves its snapshots behind when its policy is deleted. |
| Kept | The secret `smart-tutor-on-premise/duckdns/token` | Created by hand, not by a stack (section 9). |
| Kept | The account's GitHub OIDC provider and the CDK bootstrap (`CDKToolkit`) | Native-cloud created the provider and still uses it; both modes deploy with the bootstrap. |
| Kept | The GitHub environment `on-premise` and its variables | So on-premise can be redeployed. |

What is left costs a few dollars a month: snapshots about $0.05 per GB-month (incremental, at most the 50 GB volume) and the bucket about $0.023 per GB-month. Each is the only copy of learner data, so delete it by hand only when the data must go:

```powershell
$VolumeId = "<the DataVolumeId from step 2>"
aws ec2 describe-snapshots --owner-ids self --filters "Name=volume-id,Values=$VolumeId" --query "Snapshots[].SnapshotId" --output text
aws ec2 delete-snapshot --snapshot-id <snapshot id>   # once per snapshot
aws secretsmanager delete-secret --secret-id smart-tutor-on-premise/duckdns/token --force-delete-without-recovery
```

The bucket is versioned: in the S3 console, **Empty** it (all versions), then **Delete** it. `aws s3 rm --recursive` would leave the old versions behind.

**Redeploy later.** Deploy the stacks from a laptop (section 2), because GitHub can't create the role it signs in with. Deal with the kept bucket first: its name is fixed, so creating `Storage` fails with "already exists" until you bring the bucket into the stack with `cdk import` or delete it. To keep the data, set `smart-tutor:on-premise-data-snapshot-id` to the final snapshot before deploying (`on-premise-backups.md`, "Restore from a snapshot"); the first deploy resets the database roles' passwords to the new secrets. Then turn deploys on merge back on (`gh variable delete ON_PREMISE_AUTO_DEPLOY --repo konica/agent-tutor`), and merge or deploy a tag by hand (section 4).
````

- [ ] **Step 4: Run the tests**

Run: `cd infra && uv run pytest tests/test_workflows.py -q`
Expected: all pass, including `test_runbooks_no_longer_call_ecr_shared_and_explain_old_rollbacks` (the new text must not say "shared ECR" or `/smart-tutor/<service>:`).

- [ ] **Step 5: Commit**

```bash
git add docs/runbooks/on-premise-deploy.md infra/tests/test_workflows.py
git commit -m "Describe tearing down the whole on-premise mode (#207)" -m "The runbook only tore down the Host. It now also removes every on-premise stack in one destroy, after stopping deploys on merge, and lists what goes and what stays: the documents bucket, the data-volume snapshots, the DuckDNS secret, and the shared OIDC provider and bootstrap. Native-cloud keeps running because the on-premise app has no native-cloud stack." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Final check

Run: `cd infra && JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1 uv run pytest -q`
Expected: all pass. Then whole-branch review and a PR that closes #207.
