import subprocess
from typing import Any

import pytest

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
    docs = render(*PROD, "--set", "global.imageTag=abc123", "--set", "api.enabled=false",
                  "--set", "agent.enabled=false", "--set", "mcp-server.enabled=false")  # these refuse to render

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


def env_of(container: dict[str, Any]) -> dict[str, Any]:
    return {e["name"]: e.get("value", e.get("valueFrom")) for e in container["env"]}


def test_api_runs_behind_cloudfront_with_the_production_issuer() -> None:
    docs = render(*PROD, *DEPLOY)
    deploy = find(docs, "Deployment", "api")
    pod = deploy["spec"]["template"]["spec"]
    (container,) = pod["containers"]
    env = env_of(container)

    assert container["image"] == "reg.example/smart-tutor/api:abc123"
    assert pod["serviceAccountName"] == "api"
    assert deploy["spec"]["replicas"] == 2
    assert env["SMART_TUTOR_ROOT_PATH"] == "/api"
    assert env["SMART_TUTOR_KEYCLOAK_ISSUER"] == "https://d111.cloudfront.net/auth/realms/smart-tutor"
    assert env["SMART_TUTOR_KEYCLOAK_INTERNAL_URL"] == "http://keycloak/auth/realms/smart-tutor"
    assert env["SMART_TUTOR_KEYCLOAK_CLIENT_ID"] == "smart-tutor-api"
    assert env["SMART_TUTOR_CORS_ORIGINS"] == "[]"
    assert env["SMART_TUTOR_KEYCLOAK_CLIENT_SECRET"] == {"secretKeyRef": {"name": "api-keycloak", "key": "client-secret"}}
    assert env["SMART_TUTOR_DATABASE_URL"] == {"secretKeyRef": {"name": "api-db", "key": "url"}}
    # Probes don't depend on Keycloak, so the API stays up (and answers 401) while Keycloak restarts.
    for probe in ("readinessProbe", "livenessProbe"):
        assert container[probe]["httpGet"]["path"] == "/healthz"
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert find(docs, "TargetGroupBinding", "api")["spec"]["targetGroupName"] == "smart-tutor-prod-api"
    assert find(docs, "ServiceAccount", "api")


def test_api_reads_its_secrets_from_secrets_manager() -> None:
    docs = render(*PROD, *DEPLOY)

    db = find(docs, "ExternalSecret", "api-db")["spec"]
    assert db["dataFrom"] == [{"extract": {"key": "smart-tutor/db/app"}}]
    assert db["target"]["template"]["data"]["url"] == (
        "postgresql+psycopg://{{ .username }}:{{ .password }}@{{ .host }}:{{ .port }}/{{ .dbname }}?sslmode=require"
    )
    client = find(docs, "ExternalSecret", "api-keycloak")["spec"]
    assert client["data"] == [{"secretKey": "client-secret", "remoteRef": {"key": "smart-tutor/keycloak/api-client"}}]


def test_api_refuses_to_render_for_aws_without_public_url() -> None:
    with pytest.raises(subprocess.CalledProcessError) as e:
        render(*PROD, "--set", "global.imageTag=abc123")
    assert "global.publicUrl" in e.value.stderr


def test_migrate_runs_as_a_hook_after_db_bootstrap() -> None:
    docs = render(*PROD, *DEPLOY)
    job = find(docs, "Job", "migrate")
    secret = find(docs, "ExternalSecret", "migrate-db")
    bootstrap = find(docs, "Job", "db-bootstrap")

    def weight(d: dict[str, Any]) -> int:
        return int(d["metadata"]["annotations"]["helm.sh/hook-weight"])

    for d in (job, secret):
        assert d["metadata"]["annotations"]["helm.sh/hook"] == "pre-install,pre-upgrade"
        assert d["metadata"]["annotations"]["helm.sh/hook-delete-policy"] == "before-hook-creation,hook-succeeded"
    assert weight(bootstrap) < weight(secret) < weight(job)
    (container,) = job["spec"]["template"]["spec"]["containers"]
    assert container["image"] == "reg.example/smart-tutor/api:abc123"
    assert container["command"] == ["python", "-m", "smart_tutor.apps.jobs.migrate"]
    assert env_of(container)["SMART_TUTOR_DATABASE_URL"] == {"secretKeyRef": {"name": "migrate-db", "key": "url"}}
    assert secret["spec"]["dataFrom"] == [{"extract": {"key": "smart-tutor/db/app"}}]


def test_production_keeps_the_worker_off_until_task_4() -> None:
    names = {(d["kind"], d["metadata"]["name"]) for d in render(*PROD, *DEPLOY)}
    for service in ("worker",):
        assert not any(name.startswith(service) for _, name in names), service


def test_agent_runs_with_the_production_issuer_and_reaches_mcp() -> None:
    docs = render(*PROD, *DEPLOY)
    deploy = find(docs, "Deployment", "agent")
    pod = deploy["spec"]["template"]["spec"]
    (c,) = pod["containers"]
    env = env_of(c)
    assert c["image"] == "reg.example/smart-tutor/agent:abc123"
    assert pod["serviceAccountName"] == "agent"
    assert deploy["spec"]["replicas"] == 2
    assert env["SMART_TUTOR_KEYCLOAK_ISSUER"] == "https://d111.cloudfront.net/auth/realms/smart-tutor"
    assert env["SMART_TUTOR_KEYCLOAK_INTERNAL_URL"] == "http://keycloak/auth/realms/smart-tutor"
    assert env["SMART_TUTOR_KEYCLOAK_CLIENT_ID"] == "smart-tutor-api"
    assert env["SMART_TUTOR_KEYCLOAK_CLIENT_SECRET"] == {"secretKeyRef": {"name": "agent-keycloak", "key": "client-secret"}}
    assert env["SMART_TUTOR_DATABASE_URL"] == {"secretKeyRef": {"name": "agent-db", "key": "url"}}
    assert env["SMART_TUTOR_MCP_URL"] == "http://mcp-server/mcp"
    assert c["readinessProbe"]["httpGet"]["path"] == "/healthz"
    assert c["securityContext"]["readOnlyRootFilesystem"] is True


def test_mcp_server_introspects_as_rag_mcp() -> None:
    docs = render(*PROD, *DEPLOY)
    pod = find(docs, "Deployment", "mcp-server")["spec"]["template"]["spec"]
    (c,) = pod["containers"]
    env = env_of(c)
    assert c["image"] == "reg.example/smart-tutor/mcp:abc123"
    assert pod["serviceAccountName"] == "mcp-server"
    assert env["SMART_TUTOR_KEYCLOAK_CLIENT_ID"] == "rag-mcp"
    assert env["SMART_TUTOR_KEYCLOAK_AUDIENCE"] == "rag-mcp"
    assert env["SMART_TUTOR_KEYCLOAK_CLIENT_SECRET"] == {"secretKeyRef": {"name": "mcp-keycloak", "key": "client-secret"}}
    assert env["SMART_TUTOR_MCP_PORT"] == "8000"
    assert env["SMART_TUTOR_MCP_URL"] == "http://mcp-server/mcp"
    assert c["readinessProbe"]["tcpSocket"]["port"] == 8000
    secret = find(docs, "ExternalSecret", "mcp-keycloak")["spec"]
    assert secret["data"] == [{"secretKey": "client-secret", "remoteRef": {"key": "smart-tutor/keycloak/mcp-client"}}]


def test_api_agent_and_mcp_find_each_other() -> None:
    docs = render(*PROD, *DEPLOY)
    api_env = env_of(find(docs, "Deployment", "api")["spec"]["template"]["spec"]["containers"][0])
    assert api_env["SMART_TUTOR_AGENT_URL"] == "http://agent"
    agent_svc = find(docs, "Service", "agent")["spec"]["ports"][0]
    mcp_svc = find(docs, "Service", "mcp-server")["spec"]["ports"][0]
    assert (agent_svc["port"], agent_svc["targetPort"]) == (80, "http")
    assert (mcp_svc["port"], mcp_svc["targetPort"]) == (80, "http")
    agent_port = find(docs, "Deployment", "agent")["spec"]["template"]["spec"]["containers"][0]["ports"][0]
    mcp_port = find(docs, "Deployment", "mcp-server")["spec"]["template"]["spec"]["containers"][0]["ports"][0]
    assert (agent_port["name"], agent_port["containerPort"]) == ("http", 8080)
    assert (mcp_port["name"], mcp_port["containerPort"]) == ("http", 8000)
    for name in ("agent", "mcp-server"):
        assert find(docs, "ServiceAccount", name)
