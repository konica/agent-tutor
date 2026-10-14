"""What the Langfuse VM runs: Compose, Caddy, deploy.sh (spec 2026-10-14 §6.4–6.5)."""

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

DEPLOY_DIR = Path(__file__).parents[1] / "deploy"
DEPLOY_SCRIPT = DEPLOY_DIR / "deploy.sh"
SCRIPTS = [DEPLOY_SCRIPT]
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
        # Real S3, not MinIO: virtual-hosted-style addressing.
        assert env["LANGFUSE_S3_EVENT_UPLOAD_FORCE_PATH_STYLE"] == "false"
        assert env["LANGFUSE_S3_MEDIA_UPLOAD_FORCE_PATH_STYLE"] == "false"
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
    assert "if [[ $(param allow-signup) == true ]]; then auth_disable_signup=false; else auth_disable_signup=true; fi" in script


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
