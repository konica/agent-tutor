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
