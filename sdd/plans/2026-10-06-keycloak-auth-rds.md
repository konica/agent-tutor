# Keycloak runs at /auth on RDS — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keycloak runs on EKS at `https://<id>.cloudfront.net/auth`, backed by RDS; an admin signs in to the admin console, creates a user, and that user signs in to Keycloak's account console.

**Architecture:** CDK adds an RDS PostgreSQL 17 instance in the private subnets (`DataStack`) and Secrets Manager entries for the database users, the Keycloak admin, and the confidential clients (`DataStack`, `ConfigStack`). `EdgeStack` adds a Keycloak target group, an ALB rule for `/auth/*`, and an uncached CloudFront behavior for `/auth/*`; the shared VPC origin adds `Forwarded: proto=https`, so Keycloak knows the browser used HTTPS even though the ALB hop is HTTP. In the cluster, External Secrets reads Secrets Manager through a `SecretStore`; a Helm pre-install/pre-upgrade hook Job creates the app and Keycloak roles and databases; the `keycloak` chart runs an optimized Keycloak image (`--optimized --import-realm`) with a production realm whose secrets and URLs are environment placeholders.

**Tech Stack:** aws-cdk-lib 2.272 (`aws_rds`, `aws_secretsmanager`, `aws_cloudfront`, `aws_elasticloadbalancingv2`), Keycloak 26.3, PostgreSQL 17 (RDS, pgvector), External Secrets `external-secrets.io/v1`, Helm 3/4, pytest + PyYAML.

**Spec:** GitHub issue #57 (parent #54, decisions approved 2026-10-04); PRD §9.3, §9.11, §9.12; ADR 0009; `docs/runbooks/pilot-environment-overview.md`; plan `sdd/plans/2026-10-05-public-web-cloudfront.md` (#56, the edge this extends).

**Spike (2026-10-06, local, already done):** an optimized Keycloak 26.3 image with `KC_HTTP_RELATIVE_PATH=/auth` behind a TLS proxy that forwards plain HTTP with `Host` rewritten and `X-Forwarded-Proto: http` (like CloudFront → internal ALB):
- Realm import resolves `${ENV}` placeholders (client secrets, redirect URIs) and leaves unknown ones such as `${role_offline-access}` unchanged.
- `KC_HOSTNAME=https://<host>/auth` alone gives the right issuer, and the admin REST API and account-console sign-in work, **but the session cookies are not `Secure`**. Adding a static `Forwarded: proto=https` header plus `KC_PROXY_HEADERS=forwarded` makes `KEYCLOAK_IDENTITY` and `KEYCLOAK_SESSION` `Secure`. CloudFront may add `Forwarded` as a custom origin header and overwrites any viewer-sent value.
- With a read-only root filesystem, `/opt/keycloak/data` must be writable (transaction logs); otherwise startup stalls about 30 s.
- `files/db-bootstrap.sql` (already drafted) runs as a non-superuser master with `CREATEDB CREATEROLE` (like the RDS master), twice in a row without errors; the app role cannot connect to the Keycloak database. Only `CREATE EXTENSION vector` needs `rds_superuser`, which the RDS master has.

## Global Constraints

- Names: RDS instance `smart-tutor-prod`; secrets `smart-tutor/rds/master` (CDK-generated master, user `postgres`), `smart-tutor/db/app` (role and database `smart_tutor`), `smart-tutor/db/keycloak` (role and database `keycloak`), `smart-tutor/keycloak/admin` (JSON `username` = `admin`, `password`), `smart-tutor/keycloak/api-client` and `smart-tutor/keycloak/mcp-client` (plain strings). External Secrets may read only `secret:smart-tutor/*` (ClusterStack, unchanged).
- DB secrets are JSON with `username`, `password`, `dbname`, `host`, `port`; passwords are generated, 32 characters, no punctuation.
- RDS: PostgreSQL 17, `db.t4g.micro`, 20 GiB gp3 (autoscaling to 100), encrypted, single-AZ, not public, private-with-egress subnets, backups 7 days, `DeletionPolicy: Snapshot`, no deletion protection (teardown must work). Ingress 5432 only from the EKS cluster security group. RDS PostgreSQL 17 forces TLS, so clients use `sslmode=require`.
- Edge: target group `smart-tutor-prod-keycloak` (IP, HTTP 8080, health check `/auth/realms/smart-tutor/.well-known/openid-configuration`); listener rule priority 10 for `/auth/*`; CloudFront behavior `/auth/*` with managed *CachingDisabled* (`4135ea2d-6df8-44a3-9df3-4b5a84be39ad`), managed *AllViewer* (`216adef6-5c7f-47e4-b989-5492eafa07d3`, also forwards `Authorization` when caching is off, and the viewer Host, so discovery's backchannel URLs are public), all methods, redirect to HTTPS. Origin custom header `Forwarded: proto=https`. Keycloak and web both listen on 8080, so the existing ALB → pod rule covers both.
- Keycloak: image `smart-tutor/keycloak` from `deploy/keycloak/Dockerfile` (base `quay.io/keycloak/keycloak:26.3`, as in `compose.yaml`); `start --optimized --import-realm`; `KC_HOSTNAME=<publicUrl>/auth`, `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true`, `KC_HTTP_ENABLED=true`, `KC_PROXY_HEADERS=forwarded`, `KC_DB_POOL_MAX_SIZE=20`; health on the management port 9000 under `/auth/health/*`.
- `global.publicUrl` (e.g. `https://d111.cloudfront.net`, the Edge output `CloudFrontUrl`) is set at deploy time with `--set`; it is never committed. With it empty, `KC_HOSTNAME` is not rendered and Keycloak refuses to start (loud, not a wrong issuer). `helm lint deploy/helm/smart-tutor` with default values must keep passing (CI runs exactly that).
- No secret value in Git, Helm values, rendered manifests, or CI logs: manifests only reference Kubernetes Secrets that External Secrets creates.
- Production realm: same realm roles, default role, clients, and protocol mappers as `local/keycloak/realm-smart-tutor.json`; **no users**, `registrationAllowed: false` (until #47 runs in production), no SMTP, `sslRequired: external`.
- Commits: imperative subject, body says why, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Checks: `cd infra && JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1 uv run pytest -q && uv run cdk synth -q`; `helm lint deploy/helm/smart-tutor`; `helm lint deploy/helm/smart-tutor -f deploy/helm/smart-tutor/values-prod.yaml --set global.publicUrl=https://d111.cloudfront.net`. On Windows Git Bash set `MSYS_NO_PATHCONV=1` for `docker run -v` paths.

## Review Focus

1. **A deploy without `global.publicUrl`.** Keycloak must not start with a wrong issuer. Pinned in Task 4 (`test_keycloak_without_public_url_has_no_hostname`).
2. **Secrets leaking into manifests or Git.** Pinned in Task 4 (`test_rendered_manifests_hold_no_secret_values`) and Task 3 (`test_production_realm_has_no_literal_secrets_or_users`).
3. **The second `helm upgrade`.** Hook resources must be recreated, not collide ("already exists"); the SQL must be rerunnable. Pinned in Task 3 (`test_db_bootstrap_runs_as_hooks_before_the_release`) and the spike (SQL run twice).
4. **Teardown with a database.** `cdk destroy` must not be blocked, and the data must survive as a snapshot. Pinned in Task 1 (`test_database_is_private_encrypted_and_kept_as_a_snapshot`).
5. **The admin console through CloudFront.** It sends `Authorization` and uses PUT/DELETE. Pinned in Task 2 (`test_cloudfront_sends_auth_to_keycloak_uncached_with_every_method`).

---

### Task 1: RDS and the Secrets Manager entries

**Files:**
- Modify: `infra/smart_tutor_infra/stacks/data.py`, `infra/smart_tutor_infra/stacks/config.py`, `infra/smart_tutor_infra/app_stacks.py`
- Test: `infra/tests/test_synth.py`, `infra/tests/test_config_stack.py`

**Interfaces:**
- Consumes: `NetworkStack.vpc`, `ClusterStack.cluster_security_group_id`.
- Produces: `DataStack(scope, id, *, vpc: ec2.IVpc, cluster_security_group_id: str, name_prefix: str, **kwargs)` with attribute `instance: rds.DatabaseInstance` and output `DatabaseEndpoint`; the secret names in Global Constraints.

- [ ] **Step 1: Write failing tests** — append to `infra/tests/test_synth.py`:

```python
def test_database_is_private_encrypted_and_kept_as_a_snapshot() -> None:
    t = template(make_app(), "Data")

    t.resource_count_is("AWS::RDS::DBInstance", 1)
    t.has_resource(
        "AWS::RDS::DBInstance",
        {
            "DeletionPolicy": "Snapshot",  # documents and threads are never deleted; teardown keeps a snapshot
            "Properties": Match.object_like(
                {
                    "DBInstanceIdentifier": "smart-tutor-prod",
                    "Engine": "postgres",
                    "EngineVersion": "17",
                    "DBInstanceClass": "db.t4g.micro",
                    "StorageEncrypted": True,
                    "PubliclyAccessible": False,
                    "MultiAZ": False,
                    "BackupRetentionPeriod": 7,
                    "DeletionProtection": False,  # cdk destroy must work
                }
            ),
        },
    )
    t.has_resource_properties("AWS::SecretsManager::Secret", {"Name": "smart-tutor/rds/master"})
    t.has_output("DatabaseEndpoint", {})


def test_database_accepts_postgres_only_from_eks_pods() -> None:
    t = template(make_app(), "Data")

    rendered = json.dumps(t.to_json())
    assert "0.0.0.0/0" not in rendered.replace('"CidrIp": "255.255.255.255/32"', "")
    groups = t.find_resources("AWS::EC2::SecurityGroup")
    ingress = [rule for g in groups.values() for rule in g["Properties"].get("SecurityGroupIngress", [])]
    assert len(ingress) == 1
    assert ingress[0]["FromPort"] == 5432 and ingress[0]["ToPort"] == 5432
    assert "SourceSecurityGroupId" in ingress[0]


def test_app_and_keycloak_get_their_own_generated_database_secrets() -> None:
    t = template(make_app(), "Data")

    for name, user in (("smart-tutor/db/app", "smart_tutor"), ("smart-tutor/db/keycloak", "keycloak")):
        secret = next(
            s for s in t.find_resources("AWS::SecretsManager::Secret").values() if s["Properties"]["Name"] == name
        )
        generate = secret["Properties"]["GenerateSecretString"]
        assert generate["GenerateStringKey"] == "password"
        assert generate["ExcludePunctuation"] is True
        assert generate["PasswordLength"] == 32
        template_text = json.dumps(generate["SecretStringTemplate"])
        assert f'\\"username\\":\\"{user}\\"' in template_text
        assert f'\\"dbname\\":\\"{user}\\"' in template_text
        assert "Endpoint.Address" in template_text  # host comes from the instance


def test_data_deploys_after_the_cluster_whose_pods_it_admits() -> None:
    stacks = {s.stack_name: s for s in build_app(make_app())}

    assert stacks["SmartTutor-prod-Cluster"] in stacks["SmartTutor-prod-Data"].dependencies
```

Append to `infra/tests/test_config_stack.py`:

```python
def test_keycloak_admin_and_client_secrets_are_generated_not_written() -> None:
    template = Template.from_stack(ConfigStack(cdk.App(), "Config"))

    secrets = template.find_resources("AWS::SecretsManager::Secret")
    by_name = {s["Properties"]["Name"]: s["Properties"] for s in secrets.values()}
    assert set(by_name) == {
        "smart-tutor/keycloak/admin",
        "smart-tutor/keycloak/api-client",
        "smart-tutor/keycloak/mcp-client",
    }
    assert all("SecretString" not in p and "GenerateSecretString" in p for p in by_name.values())
    admin = by_name["smart-tutor/keycloak/admin"]["GenerateSecretString"]
    assert admin["SecretStringTemplate"] == '{"username": "admin"}'
    assert admin["GenerateStringKey"] == "password"
```

- [ ] **Step 2: Run — expect the five new tests to FAIL.** `cd infra && uv run pytest -q`

- [ ] **Step 3: Implement `data.py`**

```python
"""RDS PostgreSQL 17 + pgvector in the private subnets; the database credentials in Secrets Manager (#57).

One instance holds two databases, `smart_tutor` (app) and `keycloak`, each owned by its own role. CloudFormation cannot
run SQL, so the Helm release creates the roles and databases in a hook Job (deploy/helm/smart-tutor/files/
db-bootstrap.sql) with the master secret. Only pods (the EKS cluster security group) reach the instance.
"""

from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_rds as rds
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

POSTGRES_PORT = 5432
# Construct id → (secret name, role and database name). The db-bootstrap Job and the charts read these secrets.
DATABASE_USERS = {
    "App": ("smart-tutor/db/app", "smart_tutor"),
    "Keycloak": ("smart-tutor/db/keycloak", "keycloak"),
}


class DataStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc,
        cluster_security_group_id: str,
        name_prefix: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        security_group = ec2.SecurityGroup(
            self,
            "DatabaseSecurityGroup",
            vpc=vpc,
            description="RDS: PostgreSQL from EKS pods only",
            allow_all_outbound=False,
        )
        security_group.add_ingress_rule(
            ec2.Peer.security_group_id(cluster_security_group_id), ec2.Port.tcp(POSTGRES_PORT), "EKS pods"
        )
        self.instance = rds.DatabaseInstance(
            self,
            "Database",
            instance_identifier=name_prefix,
            engine=rds.DatabaseInstanceEngine.postgres(version=rds.PostgresEngineVersion.VER_17),
            instance_type=ec2.InstanceType.of(ec2.InstanceClass.BURSTABLE4_GRAVITON, ec2.InstanceSize.MICRO),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[security_group],
            port=POSTGRES_PORT,
            credentials=rds.Credentials.from_generated_secret("postgres", secret_name="smart-tutor/rds/master"),
            allocated_storage=20,
            max_allocated_storage=100,
            storage_type=rds.StorageType.GP3,
            storage_encrypted=True,
            multi_az=False,
            publicly_accessible=False,
            backup_retention=cdk.Duration.days(7),
            # Teardown (pilot-deploy.md) must work while the pilot is idle; the snapshot keeps the data.
            deletion_protection=False,
            removal_policy=cdk.RemovalPolicy.SNAPSHOT,
        )
        for construct_name, (secret_name, user) in DATABASE_USERS.items():
            secretsmanager.Secret(
                self,
                f"{construct_name}DatabaseSecret",
                secret_name=secret_name,
                description=f"PostgreSQL role and database {user} on {name_prefix}",
                generate_secret_string=secretsmanager.SecretStringGenerator(
                    secret_string_template=self.to_json_string(
                        {
                            "username": user,
                            "dbname": user,
                            "host": self.instance.db_instance_endpoint_address,
                            "port": self.instance.db_instance_endpoint_port,
                        }
                    ),
                    generate_string_key="password",
                    exclude_punctuation=True,  # safe in a JDBC URL and a psql variable
                    password_length=32,
                ),
            )
        cdk.CfnOutput(self, "DatabaseEndpoint", value=self.instance.db_instance_endpoint_address)
```

If `EngineVersion` synthesizes as something other than `"17"`, adjust the test to the synthesized value only if it is still major version 17. If the JSON template string escapes differently, make the test assertion match the synthesized form (the requirement: the template holds `username`, `dbname`, and the instance's endpoint address).

- [ ] **Step 4: Implement the Keycloak secrets in `config.py`** (keep the SSM parameters; update the module docstring to "SSM parameters (per-file limits) and the Keycloak secrets in Secrets Manager (#57)")

```python
import json
...
from aws_cdk import aws_secretsmanager as secretsmanager
...
        # Keycloak (#57): the bootstrap admin, and the confidential clients' secrets that the realm import reads.
        secretsmanager.Secret(
            self,
            "KeycloakAdminSecret",
            secret_name="smart-tutor/keycloak/admin",
            description="Keycloak bootstrap admin (master realm)",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template=json.dumps({"username": "admin"}),
                generate_string_key="password",
                exclude_punctuation=True,
                password_length=32,
            ),
        )
        for construct_name, client_id in (("Api", "smart-tutor-api"), ("Mcp", "rag-mcp")):
            secretsmanager.Secret(
                self,
                f"Keycloak{construct_name}ClientSecret",
                secret_name=f"smart-tutor/keycloak/{construct_name.lower()}-client",
                description=f"Client secret of the confidential Keycloak client {client_id}",
                generate_secret_string=secretsmanager.SecretStringGenerator(
                    exclude_punctuation=True, password_length=40
                ),
            )
```

- [ ] **Step 5: Wire `app_stacks.py`** — create the data stack after the cluster and replace `DataStack(app, f"{prefix}-Data", env=env)` in `stacks` with it:

```python
    data = DataStack(
        app,
        f"{prefix}-Data",
        env=env,
        vpc=network.vpc,
        cluster_security_group_id=cluster.cluster_security_group_id,
        name_prefix=name,
    )
```

The cross-stack reference makes `Data` depend on `Cluster`; the stack count stays 9.

- [ ] **Step 6: Run — PASS**, and `uv run cdk synth -q` succeeds.

- [ ] **Step 7: Commit** — `Create the pilot database and the Keycloak secrets with CDK`

---

### Task 2: Edge — `/auth/*` to Keycloak

**Files:**
- Modify: `infra/smart_tutor_infra/stacks/edge.py`
- Test: `infra/tests/test_synth.py`

**Interfaces:**
- Produces: target group `smart-tutor-prod-keycloak` and output `KeycloakTargetGroupName` (used by the `keycloak` chart in Task 4); constant `POD_PORT = 8080` (replaces `WEB_PORT`).

- [ ] **Step 1: Write failing tests**

```python
def test_keycloak_target_group_takes_auth_paths_on_8080() -> None:
    t = template(make_app(), "Edge")

    t.has_resource_properties(
        "AWS::ElasticLoadBalancingV2::TargetGroup",
        {
            "Name": "smart-tutor-prod-keycloak",
            "TargetType": "ip",
            "Port": 8080,
            "Protocol": "HTTP",
            "HealthCheckPath": "/auth/realms/smart-tutor/.well-known/openid-configuration",
        },
    )
    t.has_resource_properties(
        "AWS::ElasticLoadBalancingV2::ListenerRule",
        {
            "Priority": 10,
            "Conditions": [{"Field": "path-pattern", "PathPatternConfig": {"Values": ["/auth/*"]}}],
        },
    )
    t.has_output("KeycloakTargetGroupName", {"Value": "smart-tutor-prod-keycloak"})


def test_cloudfront_sends_auth_to_keycloak_uncached_with_every_method() -> None:
    t = template(make_app(), "Edge")

    t.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {
                    "CacheBehaviors": [
                        Match.object_like(
                            {
                                "PathPattern": "/auth/*",
                                "ViewerProtocolPolicy": "redirect-to-https",
                                "AllowedMethods": ["GET", "HEAD", "OPTIONS", "PUT", "PATCH", "POST", "DELETE"],
                                "CachePolicyId": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",  # CachingDisabled
                                # AllViewer: cookies, query strings, Authorization, and the viewer Host reach Keycloak
                                "OriginRequestPolicyId": "216adef6-5c7f-47e4-b989-5492eafa07d3",
                            }
                        )
                    ],
                }
            )
        },
    )


def test_origin_tells_keycloak_the_viewer_used_https() -> None:
    t = template(make_app(), "Edge")

    t.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {
                    "Origins": [
                        Match.object_like(
                            {"OriginCustomHeaders": [{"HeaderName": "Forwarded", "HeaderValue": "proto=https"}]}
                        )
                    ]
                }
            )
        },
    )
```

- [ ] **Step 2: Run — FAIL.**

- [ ] **Step 3: Implement in `edge.py`**
  - Docstring first paragraph: "Path routing: `/` → web, `/auth/*` → Keycloak (#57); `/api/*` arrives with #58."
  - Rename `WEB_PORT` to `POD_PORT` with the comment `# web and Keycloak both listen here, so one ALB → pod rule covers both`; security-group descriptions become "web and Keycloak pods" / "Internal ALB to web and Keycloak pods".
  - Keep the listener in a variable and add the Keycloak target group and rule:

```python
        keycloak_target_group_name = f"{name_prefix}-keycloak"
        keycloak_targets = elbv2.ApplicationTargetGroup(
            self,
            "KeycloakTargets",
            target_group_name=keycloak_target_group_name,
            vpc=vpc,
            port=POD_PORT,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            # Healthy only once the production realm is imported, the first thing every sign-in needs.
            health_check=elbv2.HealthCheck(
                path="/auth/realms/smart-tutor/.well-known/openid-configuration", healthy_http_codes="200"
            ),
            deregistration_delay=cdk.Duration.seconds(30),
        )
        listener = load_balancer.add_listener(
            "Http", port=80, protocol=elbv2.ApplicationProtocol.HTTP, open=False, default_target_groups=[web_targets]
        )
        listener.add_target_groups(
            "Keycloak",
            priority=10,
            conditions=[elbv2.ListenerCondition.path_patterns(["/auth/*"])],
            target_groups=[keycloak_targets],
        )
```

  - Origin and behavior:

```python
        origin = origins.VpcOrigin.with_application_load_balancer(
            load_balancer,
            http_port=80,
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
            vpc_origin_name=name_prefix,
            # The ALB sets X-Forwarded-Proto: http, so Keycloak would mark its session cookies non-Secure. CloudFront
            # overwrites any viewer-sent Forwarded header, so Keycloak can trust this one (KC_PROXY_HEADERS=forwarded).
            custom_headers={"Forwarded": "proto=https"},
        )
        distribution = cloudfront.Distribution(
            self,
            "Distribution",
            comment=f"{name_prefix}: web, /auth (later /api)",
            ...  # default_behavior unchanged
            additional_behaviors={
                "/auth/*": cloudfront.BehaviorOptions(
                    origin=origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,  # login form POST, admin REST PUT/DELETE
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    # AllViewer forwards the viewer's Host: Keycloak builds the backchannel URLs in its discovery
                    # document (token_endpoint, jwks_uri) from the request Host, and the ALB routes by path only.
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
                ),
            },
        )
        ...
        cdk.CfnOutput(self, "KeycloakTargetGroupName", value=keycloak_target_group_name)
```

- [ ] **Step 4: Run — PASS** (all tests, including #56's Edge tests), and `uv run cdk synth -q`.

- [ ] **Step 5: Commit** — `Route /auth through CloudFront and the internal ALB to Keycloak`

---

### Task 3: Keycloak image, production realm, SecretStore, and database bootstrap

**Files:**
- Create: `deploy/keycloak/Dockerfile`, `deploy/helm/smart-tutor/templates/secret-store.yaml`, `deploy/helm/smart-tutor/templates/db-bootstrap.yaml`, `infra/tests/test_keycloak_realm.py`, `infra/tests/helm.py`, `infra/tests/test_helm_chart.py`
- Already drafted by the spike (review, keep): `deploy/helm/smart-tutor/charts/keycloak/files/realm-smart-tutor.json`, `deploy/helm/smart-tutor/files/db-bootstrap.sql`
- Modify: `deploy/helm/smart-tutor/values.yaml`, `deploy/helm/smart-tutor/values-prod.yaml`, `infra/pyproject.toml` (dev dependency `pyyaml>=6`), `infra/uv.lock`

**Interfaces:**
- Consumes: secret names (Task 1).
- Produces: umbrella values `global.publicUrl`, `global.secretStore`, `awsRegion`, `dbBootstrap.enabled`, `dbBootstrap.image`; `SecretStore` named by `global.secretStore`; test helper `render(*args: str) -> list[dict]` in `infra/tests/helm.py`.

- [ ] **Step 1: Dockerfile** `deploy/keycloak/Dockerfile`

```dockerfile
# Keycloak for the pilot (#57): build options baked in, so pods start with `start --optimized`.
#   docker build -t <registry>/smart-tutor/keycloak:<sha> deploy/keycloak
# Runtime options (hostname, database, secrets) come from the keycloak chart. Same version as compose.yaml.
FROM quay.io/keycloak/keycloak:26.3 AS builder
ENV KC_DB=postgres \
    KC_HEALTH_ENABLED=true \
    KC_HTTP_RELATIVE_PATH=/auth
RUN /opt/keycloak/bin/kc.sh build

FROM quay.io/keycloak/keycloak:26.3
COPY --from=builder /opt/keycloak/ /opt/keycloak/
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
```

Verify: `docker build -q -t smart-tutor-keycloak:check deploy/keycloak`.

- [ ] **Step 2: Failing realm test** `infra/tests/test_keycloak_realm.py`

```python
"""The production realm (keycloak chart) matches the local one in clients and roles, without test users (#57)."""

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[2]
LOCAL = json.loads((ROOT / "local/keycloak/realm-smart-tutor.json").read_text())
PROD_TEXT = (ROOT / "deploy/helm/smart-tutor/charts/keycloak/files/realm-smart-tutor.json").read_text()
PROD = json.loads(PROD_TEXT)


def clients(realm: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["clientId"]: c for c in realm["clients"]}


def test_production_realm_has_the_local_clients_roles_and_mappers() -> None:
    assert PROD["realm"] == LOCAL["realm"]
    assert PROD["roles"] == LOCAL["roles"]
    assert PROD["defaultRole"] == LOCAL["defaultRole"]
    assert clients(PROD).keys() == clients(LOCAL).keys()
    for client_id, local in clients(LOCAL).items():
        prod = clients(PROD)[client_id]
        for key in ("publicClient", "standardFlowEnabled", "directAccessGrantsEnabled", "protocolMappers"):
            assert prod.get(key) == local.get(key), (client_id, key)


def test_production_realm_has_no_literal_secrets_or_users() -> None:
    assert "users" not in PROD
    assert "smtpServer" not in PROD
    assert PROD["registrationAllowed"] is False  # until sign-up (#47) runs in production
    assert PROD["sslRequired"] == "external"
    secrets = {c["clientId"]: c.get("secret") for c in PROD["clients"] if not c["publicClient"]}
    assert secrets == {
        "smart-tutor-api": "${SMART_TUTOR_API_CLIENT_SECRET}",
        "rag-mcp": "${SMART_TUTOR_MCP_CLIENT_SECRET}",
    }


def test_production_urls_come_from_the_public_url_placeholder() -> None:
    web = clients(PROD)["smart-tutor-web"]
    assert web["redirectUris"] == ["${SMART_TUTOR_PUBLIC_URL}/*"]
    assert web["webOrigins"] == ["${SMART_TUTOR_PUBLIC_URL}"]
    assert web["attributes"]["post.logout.redirect.uris"] == "${SMART_TUTOR_PUBLIC_URL}/*"
    assert not re.search(r"localhost|cloudfront\.net", PROD_TEXT)
```

Run `cd infra && uv run pytest tests/test_keycloak_realm.py -q` — passes against the drafted realm (it was written in the spike); if one fails, fix the realm, not the test.

- [ ] **Step 3: Helm render helper and failing chart tests.** Add `pyyaml>=6` to `[dependency-groups] dev` in `infra/pyproject.toml`, run `uv lock && uv sync`.

`infra/tests/helm.py`:

```python
"""Renders the umbrella chart with `helm template` for chart tests; skips the test when helm is not installed."""

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

CHART = Path(__file__).parents[2] / "deploy/helm/smart-tutor"
PROD = ["-f", str(CHART / "values-prod.yaml")]
DEPLOY = ["--set", "global.publicUrl=https://d111.cloudfront.net", "--set", "global.imageRegistry=reg.example",
          "--set", "global.imageTag=abc123"]


def render(*args: str) -> list[dict[str, Any]]:
    if shutil.which("helm") is None:
        pytest.skip("helm is not installed")
    out = subprocess.run(
        ["helm", "template", "smart-tutor", str(CHART), "--namespace", "smart-tutor", *args],
        check=True, capture_output=True, text=True,
    ).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def find(docs: list[dict[str, Any]], kind: str, name: str) -> dict[str, Any]:
    return next(d for d in docs if d["kind"] == kind and d["metadata"]["name"] == name)
```

`infra/tests/test_helm_chart.py` (Task 4 appends the keycloak tests):

```python
from tests.helm import DEPLOY, PROD, find, render


def hook(doc: dict) -> tuple[str, int, str]:
    a = doc["metadata"]["annotations"]
    return a["helm.sh/hook"], int(a["helm.sh/hook-weight"]), a["helm.sh/hook-delete-policy"]


def test_secret_store_reads_secrets_manager_before_the_hooks_need_it() -> None:
    store = find(render(*PROD, *DEPLOY), "SecretStore", "aws-secrets-manager")

    assert store["spec"]["provider"]["aws"] == {"service": "SecretsManager", "region": "us-east-1"}
    assert hook(store) == ("pre-install,pre-upgrade", -20, "before-hook-creation")


def test_db_bootstrap_runs_as_hooks_before_the_release() -> None:
    docs = render(*PROD, *DEPLOY)
    secret = find(docs, "ExternalSecret", "db-bootstrap")
    script = find(docs, "ConfigMap", "db-bootstrap")
    job = find(docs, "Job", "db-bootstrap")

    # Recreated on every upgrade (before-hook-creation), so the second deploy doesn't fail with "already exists";
    # the master credentials leave the cluster once the Job has succeeded.
    assert hook(secret) == ("pre-install,pre-upgrade", -10, "before-hook-creation,hook-succeeded")
    assert hook(script) == ("pre-install,pre-upgrade", -10, "before-hook-creation,hook-succeeded")
    assert hook(job) == ("pre-install,pre-upgrade", 0, "before-hook-creation,hook-succeeded")
    keys = {d["remoteRef"]["key"] for d in secret["spec"]["data"]}
    assert keys == {"smart-tutor/rds/master", "smart-tutor/db/app", "smart-tutor/db/keycloak"}
    assert "CREATE DATABASE" in script["data"]["db-bootstrap.sql"]
    container = job["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == "postgres:17-alpine"
    assert {"name": "PGSSLMODE", "value": "require"} in container["env"]


def test_local_defaults_render_no_secret_store_or_bootstrap() -> None:
    docs = render()

    assert not [d for d in docs if d["kind"] in ("SecretStore", "ExternalSecret", "Job")]
```

Run — expect FAIL (templates missing).

- [ ] **Step 4: Umbrella values** — `deploy/helm/smart-tutor/values.yaml` `global` block and new keys:

```yaml
# Shared defaults for every environment. Overrides: values-prod.yaml.
global:
  imageRegistry: ""  # ECR registry, set per environment
  imageTag: latest
  # Address the browser uses, e.g. https://d111.cloudfront.net (SmartTutor-prod-Edge output CloudFrontUrl).
  # Set at deploy time with --set global.publicUrl=...; Keycloak won't start without it.
  publicUrl: ""
  # SecretStore that ExternalSecrets read from (AWS Secrets Manager); empty renders no SecretStore or ExternalSecrets.
  secretStore: ""

awsRegion: us-east-1

# Creates the app and Keycloak roles and databases on RDS before each install and upgrade (files/db-bootstrap.sql).
dbBootstrap:
  enabled: false
  image: postgres:17-alpine
```

`values-prod.yaml`: add at the top

```yaml
global:
  secretStore: aws-secrets-manager
dbBootstrap:
  enabled: true
```

(the `keycloak` block changes in Task 4).

- [ ] **Step 5: `templates/secret-store.yaml`**

```yaml
{{- if .Values.global.secretStore }}
# AWS Secrets Manager, read with the External Secrets controller's own identity (Pod Identity in ClusterStack,
# allowed only secret:smart-tutor/*). A hook, because the db-bootstrap hook needs it before the release's resources.
apiVersion: external-secrets.io/v1
kind: SecretStore
metadata:
  name: {{ .Values.global.secretStore }}
  annotations:
    helm.sh/hook: pre-install,pre-upgrade
    helm.sh/hook-weight: "-20"
    helm.sh/hook-delete-policy: before-hook-creation
spec:
  provider:
    aws:
      service: SecretsManager
      region: {{ .Values.awsRegion }}
{{- end }}
```

- [ ] **Step 6: `templates/db-bootstrap.yaml`**

```yaml
{{- if .Values.dbBootstrap.enabled }}
{{- $hook := dict "helm.sh/hook" "pre-install,pre-upgrade" "helm.sh/hook-delete-policy" "before-hook-creation,hook-succeeded" }}
# Creates the app and Keycloak roles and databases on RDS (files/db-bootstrap.sql) before anything that uses them
# starts. The master credentials exist in the cluster only while the hooks run: Helm deletes the ExternalSecret once
# the Job succeeds, and External Secrets deletes the Secret it owns.
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: db-bootstrap
  annotations:
    {{- toYaml (merge (dict "helm.sh/hook-weight" "-10") $hook) | nindent 4 }}
spec:
  refreshInterval: "0"
  secretStoreRef:
    name: {{ required "dbBootstrap needs global.secretStore" .Values.global.secretStore }}
    kind: SecretStore
  target:
    name: db-bootstrap
    creationPolicy: Owner
  data:
    {{- range $env, $ref := dict
        "PGHOST" (list "smart-tutor/rds/master" "host")
        "PGUSER" (list "smart-tutor/rds/master" "username")
        "PGPASSWORD" (list "smart-tutor/rds/master" "password")
        "APP_USER" (list "smart-tutor/db/app" "username")
        "APP_PASSWORD" (list "smart-tutor/db/app" "password")
        "APP_DB" (list "smart-tutor/db/app" "dbname")
        "KEYCLOAK_USER" (list "smart-tutor/db/keycloak" "username")
        "KEYCLOAK_PASSWORD" (list "smart-tutor/db/keycloak" "password")
        "KEYCLOAK_DB" (list "smart-tutor/db/keycloak" "dbname") }}
    - secretKey: {{ $env }}
      remoteRef:
        key: {{ index $ref 0 }}
        property: {{ index $ref 1 }}
    {{- end }}
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: db-bootstrap
  annotations:
    {{- toYaml (merge (dict "helm.sh/hook-weight" "-10") $hook) | nindent 4 }}
data:
  db-bootstrap.sql: |
    {{- .Files.Get "files/db-bootstrap.sql" | nindent 4 }}
---
apiVersion: batch/v1
kind: Job
metadata:
  name: db-bootstrap
  annotations:
    {{- toYaml (merge (dict "helm.sh/hook-weight" "0") $hook) | nindent 4 }}
spec:
  backoffLimit: 3
  activeDeadlineSeconds: 600
  template:
    spec:
      restartPolicy: Never
      securityContext:
        runAsNonRoot: true
        runAsUser: 70  # postgres in the alpine image
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: psql
          image: {{ .Values.dbBootstrap.image }}
          envFrom:
            - secretRef:
                name: db-bootstrap
          env:
            - name: PGDATABASE
              value: postgres
            - name: PGSSLMODE
              value: require  # RDS PostgreSQL 17 forces TLS
            - name: HOME
              value: /tmp
          command:
            - sh
            - -c
            - >-
              exec psql -v app_user="$APP_USER" -v app_password="$APP_PASSWORD" -v app_db="$APP_DB"
              -v keycloak_user="$KEYCLOAK_USER" -v keycloak_password="$KEYCLOAK_PASSWORD"
              -v keycloak_db="$KEYCLOAK_DB" -f /sql/db-bootstrap.sql
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: [ALL]
          volumeMounts:
            - name: sql
              mountPath: /sql
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: sql
          configMap:
            name: db-bootstrap
        - name: tmp
          emptyDir: {}
{{- end }}
```

Helm hook weights in annotations must be strings; if `merge`/`toYaml` reorders keys that's fine. Note: `range` over a `dict` iterates in key order — fine.

- [ ] **Step 7: Run — PASS**: `cd infra && uv run pytest -q`; `helm lint deploy/helm/smart-tutor`; `helm lint deploy/helm/smart-tutor -f deploy/helm/smart-tutor/values-prod.yaml --set global.publicUrl=https://d111.cloudfront.net`.

- [ ] **Step 8: Commit** — `Bootstrap the pilot databases and build Keycloak for production`

---

### Task 4: The `keycloak` chart

**Files:**
- Create: `deploy/helm/smart-tutor/charts/keycloak/templates/_helpers.tpl`, `realm-configmap.yaml`, `externalsecrets.yaml`, `deployment.yaml`, `service.yaml`, `targetgroupbinding.yaml` (delete `.gitkeep`)
- Modify: `deploy/helm/smart-tutor/charts/keycloak/Chart.yaml`, `charts/keycloak/values.yaml`, `deploy/helm/smart-tutor/values-prod.yaml`
- Test: `infra/tests/test_helm_chart.py`

**Interfaces:**
- Consumes: `global.publicUrl`, `global.secretStore`, `global.imageRegistry`, `global.imageTag` (Task 3); target group `smart-tutor-prod-keycloak` (Task 2); secret names (Task 1).
- Produces: Service `keycloak` (port 80 → 8080; #58's API introspects at `http://keycloak.smart-tutor.svc.cluster.local/auth/realms/smart-tutor`), Kubernetes Secrets `keycloak-db`, `keycloak-admin`, `keycloak-clients` (key `api-client-secret` is also what #58's API needs).

- [ ] **Step 1: Failing tests** — append to `infra/tests/test_helm_chart.py`:

```python
def keycloak_env(docs: list[dict]) -> dict[str, dict]:
    container = find(docs, "Deployment", "keycloak")["spec"]["template"]["spec"]["containers"][0]
    return {e["name"]: e for e in container["env"]}


def test_keycloak_runs_optimized_at_auth_on_the_public_address() -> None:
    docs = render(*PROD, *DEPLOY)
    deployment = find(docs, "Deployment", "keycloak")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    env = keycloak_env(docs)

    assert container["image"] == "reg.example/smart-tutor/keycloak:abc123"
    assert container["args"] == ["start", "--optimized", "--import-realm"]
    assert env["KC_HOSTNAME"]["value"] == "https://d111.cloudfront.net/auth"
    assert env["KC_PROXY_HEADERS"]["value"] == "forwarded"
    assert env["SMART_TUTOR_PUBLIC_URL"]["value"] == "https://d111.cloudfront.net"
    assert container["readinessProbe"]["httpGet"] == {"path": "/auth/health/ready", "port": "management"}
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    mounts = {m["mountPath"] for m in container["volumeMounts"]}
    assert {"/tmp", "/opt/keycloak/data", "/opt/keycloak/data/import"} <= mounts
    binding = find(docs, "TargetGroupBinding", "keycloak")
    assert binding["spec"]["targetGroupName"] == "smart-tutor-prod-keycloak"


def test_keycloak_without_public_url_has_no_hostname() -> None:
    docs = render(*PROD, "--set", "global.imageTag=abc123")

    assert "KC_HOSTNAME" not in keycloak_env(docs)  # Keycloak then refuses to start instead of using a wrong issuer


def test_rendered_manifests_hold_no_secret_values() -> None:
    docs = render(*PROD, *DEPLOY)
    env = keycloak_env(docs)

    for name in ("KC_DB_URL", "KC_DB_USERNAME", "KC_DB_PASSWORD", "KC_BOOTSTRAP_ADMIN_USERNAME",
                 "KC_BOOTSTRAP_ADMIN_PASSWORD", "SMART_TUTOR_API_CLIENT_SECRET", "SMART_TUTOR_MCP_CLIENT_SECRET"):
        assert "value" not in env[name] and "secretKeyRef" in env[name]["valueFrom"], name
    assert not [d for d in docs if d["kind"] == "Secret"]
    remote = {
        r["remoteRef"]["key"]
        for d in docs if d["kind"] == "ExternalSecret" and d["metadata"]["name"].startswith("keycloak")
        for r in d["spec"].get("data", [])
    } | {
        f["extract"]["key"]
        for d in docs if d["kind"] == "ExternalSecret" and d["metadata"]["name"].startswith("keycloak")
        for f in d["spec"].get("dataFrom", [])
    }
    assert remote == {
        "smart-tutor/db/keycloak",
        "smart-tutor/keycloak/admin",
        "smart-tutor/keycloak/api-client",
        "smart-tutor/keycloak/mcp-client",
    }


def test_keycloak_imports_the_production_realm() -> None:
    import json

    realm = json.loads(find(render(*PROD, *DEPLOY), "ConfigMap", "keycloak-realm")["data"]["realm-smart-tutor.json"])

    assert realm["realm"] == "smart-tutor" and "users" not in realm
```

Run — FAIL.

- [ ] **Step 2: `Chart.yaml` description** → `"Keycloak at /auth behind CloudFront, on the RDS database keycloak (#57)."`

- [ ] **Step 3: `values.yaml`**

```yaml
# Keycloak at /auth behind CloudFront (ADR 0009, ADR 0010) on the RDS database `keycloak`.
# Image: deploy/keycloak/Dockerfile. The production realm (files/realm-smart-tutor.json) is imported on first start.
replicaCount: 1
image:
  repository: smart-tutor/keycloak
  tag: ""  # defaults to global.imageTag
# ALB target group to register pods in (TargetGroupBinding). Empty renders no binding.
targetGroupName: ""
# Secrets Manager entries (CDK DataStack and ConfigStack), read through global.secretStore.
secrets:
  database: smart-tutor/db/keycloak
  admin: smart-tutor/keycloak/admin
  apiClient: smart-tutor/keycloak/api-client
  mcpClient: smart-tutor/keycloak/mcp-client
resources:
  requests:
    cpu: 250m
    memory: 1Gi
  limits:
    memory: 1536Mi
```

- [ ] **Step 4: templates**

`_helpers.tpl`:

```yaml
{{- define "keycloak.labels" -}}
app.kubernetes.io/name: keycloak
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "keycloak.image" -}}
{{- $tag := .Values.image.tag | default .Values.global.imageTag -}}
{{- if .Values.global.imageRegistry }}{{ .Values.global.imageRegistry }}/{{ end }}{{ .Values.image.repository }}:{{ $tag }}
{{- end }}
```

`realm-configmap.yaml`:

```yaml
# The production realm: placeholders such as ${SMART_TUTOR_PUBLIC_URL} resolve from the pod's environment on import.
# Keycloak imports it only when the realm doesn't exist yet; later realm changes go through the admin console.
apiVersion: v1
kind: ConfigMap
metadata:
  name: keycloak-realm
  labels:
    {{- include "keycloak.labels" . | nindent 4 }}
data:
  realm-smart-tutor.json: |
    {{- .Files.Get "files/realm-smart-tutor.json" | nindent 4 }}
```

`externalsecrets.yaml`:

```yaml
{{- if .Values.global.secretStore }}
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: keycloak-db
  labels:
    {{- include "keycloak.labels" . | nindent 4 }}
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: {{ .Values.global.secretStore }}
    kind: SecretStore
  target:
    name: keycloak-db
    template:
      data:
        url: {{ "jdbc:postgresql://{{ .host }}:{{ .port }}/{{ .dbname }}?sslmode=require" | quote }}
        username: {{ "{{ .username }}" | quote }}
        password: {{ "{{ .password }}" | quote }}
  dataFrom:
    - extract:
        key: {{ .Values.secrets.database }}
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: keycloak-admin
  labels:
    {{- include "keycloak.labels" . | nindent 4 }}
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: {{ .Values.global.secretStore }}
    kind: SecretStore
  target:
    name: keycloak-admin
  dataFrom:
    - extract:
        key: {{ .Values.secrets.admin }}
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: keycloak-clients
  labels:
    {{- include "keycloak.labels" . | nindent 4 }}
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: {{ .Values.global.secretStore }}
    kind: SecretStore
  target:
    name: keycloak-clients
  data:
    - secretKey: api-client-secret
      remoteRef:
        key: {{ .Values.secrets.apiClient }}
    - secretKey: mcp-client-secret
      remoteRef:
        key: {{ .Values.secrets.mcpClient }}
{{- end }}
```

`deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: keycloak
  labels:
    {{- include "keycloak.labels" . | nindent 4 }}
spec:
  replicas: {{ .Values.replicaCount }}
  strategy:
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0  # sign-in stays up during an upgrade; pods share caches through the database (JDBC_PING)
  selector:
    matchLabels:
      {{- include "keycloak.labels" . | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "keycloak.labels" . | nindent 8 }}
      annotations:
        checksum/realm: {{ .Files.Get "files/realm-smart-tutor.json" | sha256sum }}
    spec:
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: keycloak
          image: {{ include "keycloak.image" . }}
          args: [start, --optimized, --import-realm]
          ports:
            - name: http
              containerPort: 8080
            - name: management
              containerPort: 9000
          env:
            {{- with .Values.global.publicUrl }}
            # Without it Keycloak refuses to start, rather than issue tokens for a wrong address.
            - name: KC_HOSTNAME
              value: {{ printf "%s/auth" (trimSuffix "/" .) | quote }}
            {{- end }}
            - name: KC_HOSTNAME_BACKCHANNEL_DYNAMIC
              value: "true"  # the API introspects in-cluster (ADR 0007)
            - name: KC_HTTP_ENABLED
              value: "true"  # TLS ends at CloudFront (ADR 0009)
            # CloudFront adds `Forwarded: proto=https` (EdgeStack), so session cookies are Secure behind the HTTP ALB.
            - name: KC_PROXY_HEADERS
              value: forwarded
            - name: KC_DB_POOL_MAX_SIZE
              value: "20"  # db.t4g.micro allows about 100 connections in total
            - name: KC_DB_URL
              valueFrom: {secretKeyRef: {name: keycloak-db, key: url}}
            - name: KC_DB_USERNAME
              valueFrom: {secretKeyRef: {name: keycloak-db, key: username}}
            - name: KC_DB_PASSWORD
              valueFrom: {secretKeyRef: {name: keycloak-db, key: password}}
            - name: KC_BOOTSTRAP_ADMIN_USERNAME
              valueFrom: {secretKeyRef: {name: keycloak-admin, key: username}}
            - name: KC_BOOTSTRAP_ADMIN_PASSWORD
              valueFrom: {secretKeyRef: {name: keycloak-admin, key: password}}
            # Read by the realm import (files/realm-smart-tutor.json).
            - name: SMART_TUTOR_PUBLIC_URL
              value: {{ trimSuffix "/" .Values.global.publicUrl | quote }}
            - name: SMART_TUTOR_API_CLIENT_SECRET
              valueFrom: {secretKeyRef: {name: keycloak-clients, key: api-client-secret}}
            - name: SMART_TUTOR_MCP_CLIENT_SECRET
              valueFrom: {secretKeyRef: {name: keycloak-clients, key: mcp-client-secret}}
          startupProbe:
            httpGet:
              path: /auth/health/started
              port: management
            periodSeconds: 5
            failureThreshold: 60  # first start creates the schema and imports the realm
          readinessProbe:
            httpGet:
              path: /auth/health/ready
              port: management
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /auth/health/live
              port: management
            periodSeconds: 20
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: [ALL]
          resources:
            {{- toYaml .Values.resources | nindent 12 }}
          volumeMounts:
            - name: tmp
              mountPath: /tmp
            - name: data
              mountPath: /opt/keycloak/data  # transaction logs; read-only stalls startup
            - name: realm
              mountPath: /opt/keycloak/data/import
              readOnly: true
      volumes:
        - name: tmp
          emptyDir: {}
        - name: data
          emptyDir: {}
        - name: realm
          configMap:
            name: keycloak-realm
```

`service.yaml` and `targetgroupbinding.yaml`: the web chart's files with `web` → `keycloak` (`keycloak.labels`; Service port 80 → `targetPort: http`; binding comment "registers the Keycloak pods' IPs in the CDK-made target group (EdgeStack)").

- [ ] **Step 5: `values-prod.yaml`** — replace the keycloak block:

```yaml
keycloak:
  enabled: true
  targetGroupName: smart-tutor-prod-keycloak  # SmartTutor-prod-Edge output KeycloakTargetGroupName
```

and update the header comment: the deploy also sets `global.publicUrl` (`--set global.publicUrl=<Edge output CloudFrontUrl>`).

- [ ] **Step 6: Run — PASS**: `cd infra && uv run pytest -q`; both `helm lint` commands from Global Constraints.

- [ ] **Step 7: Run the rendered pod locally** (mirrors the spike with the chart's exact settings): `docker build -t smart-tutor-keycloak:check deploy/keycloak`; start `pgvector/pgvector:pg17` on a docker network, run `db-bootstrap.sql` as a `CREATEDB CREATEROLE` role, run the image read-only (`--read-only --tmpfs /tmp --tmpfs /opt/keycloak/data`, realm mounted at `/opt/keycloak/data/import`) with the env the chart renders; check `curl http://<kc>:9000/auth/health/started`, `/ready`, and `/live` return 200 and the logs show `Realm 'smart-tutor' imported`. Remove the containers afterwards.

- [ ] **Step 8: Commit** — `Run Keycloak on EKS at /auth with the production realm`

---

### Task 5: ADR, runbook, overview, spec

**Files:**
- Create: `sdd/adr/0010-keycloak-behind-cloudfront.md`
- Modify: `sdd/adr/README.md`, `AGENTS.md` (ADR range 0001–0010), `docs/runbooks/pilot-deploy.md`, `docs/runbooks/pilot-aws-prerequisites.md`, `docs/runbooks/pilot-environment-overview.md`, `sdd/specs/2026-10-02-project-structure-design.md`

- [ ] **Step 1: ADR 0010** "Keycloak behind CloudFront: pinned hostname, a trusted `Forwarded` header, and databases made by a Helm hook" (accepted, 2026-10-06). Context: Keycloak sits behind CloudFront → internal ALB over HTTP (ADR 0009); the ALB overwrites `X-Forwarded-Proto` with `http`; CloudFormation can't run SQL. Decision: `KC_HOSTNAME` = the full public URL with `/auth`; CloudFront adds `Forwarded: proto=https` to origin requests and Keycloak reads only that (`proxy-headers=forwarded`), because CloudFront overwrites a viewer-sent value; an optimized image (`deploy/keycloak/Dockerfile`); one RDS instance with two databases and two roles created idempotently by a pre-install/pre-upgrade hook Job with the master secret, which leaves the cluster after the Job succeeds; the realm is imported once from a file with environment placeholders. Alternatives rejected: `xforwarded` (ALB sets `http`, cookies not `Secure`); no proxy headers (works, but session cookies not `Secure`: found in the spike); a Lambda custom resource for SQL (bundling a driver, VPC Lambda); Keycloak as the master user (no isolation from app data); stock image with `start` (re-augments on every start). Consequences: a new distribution address or custom domain needs `--set global.publicUrl` plus the redirect URIs changed in the admin console (the import doesn't overwrite an existing realm); a password rotation in Secrets Manager reaches the database on the next `helm upgrade`; client IPs in Keycloak events are the ALB's.

- [ ] **Step 2: `pilot-deploy.md`** — retitle "Pilot deploy (#56, #57)"; intro says it now also brings up Keycloak at `/auth` on RDS. Changes:
  - §2: deploy takes about 35 min (RDS adds about 10).
  - New §5 "Build and push the images": the web build plus `docker build -t "$Registry/smart-tutor/keycloak:$Tag" deploy/keycloak` and its push.
  - §6 install: add `--set global.publicUrl=$Url`; the first install runs the `db-bootstrap` hook (creates roles and databases); Keycloak's first start takes about 2 min (schema and realm import).
  - §7 check: `kubectl -n smart-tutor get pods,externalsecrets,targetgroupbindings` (ExternalSecrets `SecretSynced`); target health for `smart-tutor-prod-keycloak`; `curl.exe -s "$Url/auth/realms/smart-tutor/.well-known/openid-configuration"` shows `"issuer":"<Url>/auth/realms/smart-tutor"`; the database is private: `aws rds describe-db-instances --db-instance-identifier smart-tutor-prod --query "DBInstances[0].PubliclyAccessible"` → `False`.
  - New section "Manage client accounts" (moved here from the prerequisites table, expanded): get the admin password `aws secretsmanager get-secret-value --secret-id smart-tutor/keycloak/admin --query SecretString --output text` (don't paste it anywhere); sign in at `$Url/auth/admin` as `admin`; Keycloak shows a banner for the temporary admin: optionally create a permanent admin user in realm **master** with role `admin` and then delete the bootstrap one. Create: realm **smart-tutor** → Users → Add user → email, first and last name, **Email verified** on → Create → Credentials → Set password, **Temporary** on (at least 12 characters, not the email). Demo (#57): open `$Url/auth/realms/smart-tutor/account` in a private window and sign in as the new user; Keycloak asks for a new password, then shows the account console. Remove access: Users → user → **Enabled** off (sessions end; PRD has no account deletion). Self-registration stays off until #47 runs in production.
  - Teardown: before `cdk destroy`, note that `SmartTutor-prod-Data` keeps a final snapshot (`aws rds describe-db-snapshots --db-instance-identifier smart-tutor-prod`); delete old snapshots you don't need, they cost storage. A fresh deploy starts with an empty database; restoring a snapshot is a manual step outside this runbook. Secrets in CDK stacks are deleted at once (CloudFormation force-deletes), so a redeploy with the same names works. Remove the "From #57 on…" sentence.
  - Costs: RDS `db.t4g.micro` with 20 GiB is about $15 a month.
- [ ] **Step 3: `pilot-aws-prerequisites.md`** — the #57 row becomes: "Run the deploy update and create the client's account, following [Manage client accounts](pilot-deploy.md#manage-client-accounts). Do the #57 demo there."
- [ ] **Step 4: `pilot-environment-overview.md`** — #57 row "How" adds `deploy/keycloak/Dockerfile`, the `db-bootstrap` hook, and ADR 0010; the runtime diagram gets the `db-bootstrap` hook Job (`MIG`-style node `BOOT["db-bootstrap<br/>Helm hook Job"]` with `BOOT -->|"roles + databases"| RDS` and `SM --> ESO --> BOOT`); the `/auth/*` row says the issuer is `https://<id>.cloudfront.net/auth/realms/smart-tutor`, CloudFront adds `Forwarded: proto=https`.
- [ ] **Step 5: Spec §8** — infra comment: `data (RDS + database secrets)`, `config (SSM, Keycloak secrets)`; deploy tree adds `├── keycloak/Dockerfile  # optimized Keycloak image (#57)` under `deploy/` and `│   ├── templates/  # SecretStore and the db-bootstrap hook (files/db-bootstrap.sql)` under the umbrella chart.
- [ ] **Step 6: ADR index row** `| [0010](0010-keycloak-behind-cloudfront.md) | Keycloak behind CloudFront: pinned hostname, a trusted Forwarded header, databases made by a Helm hook |`; `AGENTS.md` "`sdd/adr/` (0001–0010)".
- [ ] **Step 7: Commit** — `Record the Keycloak edge decision and extend the pilot runbook`

---

## Final checks

```bash
cd infra && uv run pytest -q && uv run cdk synth -q
helm lint deploy/helm/smart-tutor
helm lint deploy/helm/smart-tutor -f deploy/helm/smart-tutor/values-prod.yaml --set global.publicUrl=https://d111.cloudfront.net
docker build -q -t smart-tutor-keycloak:check deploy/keycloak
```

A real `cdk deploy`, the add-on and app install, and the demo against CloudFront are human steps (pilot-deploy.md; #55 runbook "Human steps in the later slices").
