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
        _allow(
            {
                "Fn::Join": [
                    "",
                    [
                        "arn:aws:ecr:",
                        {"Ref": "AWS::Region"},
                        ":",
                        {"Ref": "AWS::AccountId"},
                        ":repository/smart-tutor/*",
                    ],
                ]
            }
        ),
    ),
    "on-premise pulls a native-cloud image": (
        ON_PREMISE,
        "SmartTutor-OnPremise-prod-Host",
        _parameter(f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/smart-tutor/api:0123abc"),
    ),
    "an on-premise glob too wide for its SSM path": (
        ON_PREMISE,
        "SmartTutor-OnPremise-prod-Host",
        _allow("arn:aws:ssm:us-east-1:*:parameter/smart-tutor*"),
    ),
    "on-premise imports a native-cloud export": (
        ON_PREMISE,
        "SmartTutor-OnPremise-prod-Storage",
        _parameter(
            {"Fn::ImportValue": "SmartTutor-prod-Edge:ExportsOutputFnGetAttDistribution830FAC52DomainNameBEB09E30"}
        ),
    ),
    "native-cloud reads on-premise's secrets": (
        NATIVE_CLOUD,
        "SmartTutor-prod-Cluster",
        _allow("arn:aws:secretsmanager:us-east-1:*:secret:smart-tutor-on-premise/*"),
    ),
    "native-cloud names on-premise's queue": (
        NATIVE_CLOUD,
        "SmartTutor-prod-Config",
        _parameter("smart-tutor-on-premise-ingest"),
    ),
    "native-cloud acts on on-premise's deploy role": (
        NATIVE_CLOUD,
        "SmartTutor-prod-GitHubDeploy",
        _allow("arn:aws:iam::*:role/smart-tutor-on-premise-github-deploy"),
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
