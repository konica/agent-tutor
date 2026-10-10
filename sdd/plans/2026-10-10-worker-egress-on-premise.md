# Limit the On-Premise Worker's Egress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On the on-premise VM, the ingestion worker can reach only S3 (the documents bucket), SQS, SSM, Bedrock, and Postgres; a deploy-time check proves it after every deploy (#153).

**Architecture:** The worker moves to a Compose network with `internal: true`, which has no route out of the VM and no external DNS. Two services join it: Postgres, reached directly, and an allowlisting Squid forward proxy, `egress-proxy`, which also sits on the default network. The worker's boto3 clients use the proxy through `HTTP_PROXY`/`HTTPS_PROXY`. Squid allows `CONNECT` on port 443 to five exact host names, and plain HTTP only to the instance metadata service, which is where botocore gets the instance profile's credentials. It denies everything else. Host firewall rules were rejected because SQS, SSM, and Bedrock have no fixed IP ranges that exclude other AWS customers. After `up --wait`, `deploy.sh` runs `check-egress.py` inside the worker. The check proves the block (direct connections fail, and the proxy refuses other hosts) and the allowed paths (real S3, SQS, and SSM calls; Bedrock and Postgres reachable). A leak stops the worker.

**Tech Stack:** Docker Compose, Squid 6 (`ubuntu/squid:6.6-24.04_edge`), bash, stdlib Python with boto3 for the check script (it runs in the worker image), pytest (`infra/tests`).

**Spec:** GitHub issue #153 (parent #145); PRD `sdd/prd.md` v2.31 §9.10 (risk rows "Malicious PDFs against the parser" and "No worker egress allowlist on-premise"), §9.12; ADR 0012.

## Global Constraints

- From inside the worker container, connections to an arbitrary internet host fail, while S3, SQS, SSM, Bedrock, and Postgres work.
- The rest of the services keep their current network access: no service other than `worker` changes networks, except that `postgres` also joins the worker network (it stays on `default`).
- Native-cloud is untouched (no change under `deploy/helm/`, `infra/smart_tutor_infra/stacks/cluster.py`).
- An automated check at deploy time proves the block; a leak stops the worker before the deploy fails (like the isolation check).
- The PRD risk table no longer lists the gap; PRD version bumps to v2.32 with a "Changes from v2.31" row.
- Files the VM runs keep LF line endings; nothing prints a secret.
- Checks: `cd infra && uv run pytest` (backend is unchanged).

## Allowed destinations (exact)

| From the worker | How | Why |
|---|---|---|
| `postgres:5432` | direct, on the internal network | the app database |
| `${DOCUMENTS_BUCKET}.s3.amazonaws.com:443`, `${DOCUMENTS_BUCKET}.s3.${AWS_REGION}.amazonaws.com:443` | proxy `CONNECT` | the bucket, virtual-hosted (botocore uses the first in us-east-1). Not bare `s3.*`: path-style requests could name another account's bucket |
| `sqs.${AWS_REGION}.amazonaws.com:443`, `ssm.${AWS_REGION}.amazonaws.com:443`, `bedrock-runtime.${AWS_REGION}.amazonaws.com:443` | proxy `CONNECT` | the queue, settings, models |
| `http://169.254.169.254` (port 80) | proxy, plain HTTP | IMDSv2: the instance profile's credentials. Squid deletes `X-Forwarded-For` (IMDS rejects a token request that carries it) |

Squid matches with `dstdomain -n`, so an IP-literal request never matches through a reverse lookup, and a denied request triggers no DNS query.

## Review Focus

1. The proxy allows a host by suffix or reverse DNS, for example `CONNECT other-bucket.s3.amazonaws.com`, bare `s3.amazonaws.com`, or an IP literal. Expected: 403. Task 1's test pins exact names and `-n`, and the controller's live run checks the 403s.
2. The worker reaches an allowed AWS host directly, bypassing the proxy. Expected: the connection fails (no route). Task 2's script checks a direct connection to the SQS host.
3. The check script itself crashes, for example on a missing env var or a boto3 import error. Expected: fail closed. The deploy fails and stops the worker, because the outcome is treated like a leak. Task 2's test covers the exit code.
4. AWS is briefly unreachable during a deploy. Expected: the deploy fails with a "cannot reach" message, and the worker is NOT stopped (it retries on its own). Task 2's test covers exit code 2 and the deploy.sh branch.
5. A change to the bucket or region must reach the proxy. Expected: Compose recreates the proxy, because its config is an interpolated environment variable. This was verified in the prototype, and Task 1's test checks that the config interpolates `${DOCUMENTS_BUCKET}` and `${AWS_REGION}`.

---

### Task 1: Worker on an internal network behind an allowlisting proxy (compose.yaml)

**Files:**
- Modify: `deploy/on-premise/compose.yaml` (header comment; top-level `networks`; `postgres.networks`; new `egress-proxy` service; `worker.networks`, proxy env, `depends_on`)
- Test: `infra/tests/test_host.py` (compose section)

**Interfaces:**
- Produces: Compose network `worker` (`internal: true`); service `egress-proxy` listening on `egress-proxy:3128`; worker env `HTTP_PROXY`/`HTTPS_PROXY` = `http://egress-proxy:3128`. Task 2's check script reads `HTTPS_PROXY`, `AWS_REGION`, `SMART_TUTOR_DOCUMENTS_BUCKET`, `SMART_TUTOR_INGEST_QUEUE_URL`, `SMART_TUTOR_MAX_PAGES_PARAM` from the worker's environment.

- [ ] **Step 1: Write the failing tests** (append to the compose section of `infra/tests/test_host.py`; update `LONG_RUNNING` to include `"egress-proxy"`, and add `"egress-proxy"` where `test_compose_runs_the_production_services_and_no_local_emulators` enumerates services through `LONG_RUNNING`):

```python
def _squid_conf(compose: dict[str, Any]) -> list[str]:
    conf = compose["services"]["egress-proxy"]["environment"]["SQUID_CONF"]
    return [line.strip() for line in conf.splitlines() if line.strip() and not line.strip().startswith("#")]


def test_worker_reaches_only_postgres_and_the_egress_proxy(compose: dict[str, Any]) -> None:
    assert compose["networks"]["worker"] == {"internal": True}  # no route out of the VM, no external DNS
    assert compose["services"]["worker"]["networks"] == ["worker"]
    on_worker_network = {n for n, s in compose["services"].items() if "worker" in s.get("networks", [])}
    assert on_worker_network == {"worker", "postgres", "egress-proxy"}
    # Every other service keeps the default network only.
    assert compose["services"]["postgres"]["networks"] == ["default", "worker"]
    assert compose["services"]["egress-proxy"]["networks"] == ["default", "worker"]
    for name, service in compose["services"].items():
        if name not in on_worker_network:
            assert "networks" not in service, name
    env = compose["services"]["worker"]["environment"]
    assert env["HTTPS_PROXY"] == env["HTTP_PROXY"] == "http://egress-proxy:3128"
    assert compose["services"]["worker"]["depends_on"]["egress-proxy"] == {"condition": "service_healthy"}


def test_egress_proxy_allows_only_the_workers_aws_endpoints_and_imds(compose: dict[str, Any]) -> None:
    lines = _squid_conf(compose)
    acls = {line.split()[1]: line.split()[2:] for line in lines if line.startswith("acl ")}
    assert acls["aws"] == [
        "dstdomain",
        "-n",  # no reverse lookup: an IP literal never matches a name
        "${DOCUMENTS_BUCKET}.s3.amazonaws.com",
        "${DOCUMENTS_BUCKET}.s3.${AWS_REGION}.amazonaws.com",
        "sqs.${AWS_REGION}.amazonaws.com",
        "ssm.${AWS_REGION}.amazonaws.com",
        "bedrock-runtime.${AWS_REGION}.amazonaws.com",
    ]
    assert acls["imds"] == ["dstdomain", "-n", "169.254.169.254"]
    assert acls["tls"] == ["port", "443"] and acls["http"] == ["port", "80"]
    rules = [line for line in lines if line.startswith("http_access ")]
    assert rules == [
        "http_access allow CONNECT aws tls",
        "http_access allow !CONNECT imds http",
        "http_access deny all",
    ]
    assert "forwarded_for delete" in lines  # IMDSv2 refuses a token request with X-Forwarded-For
    assert "via off" in lines
    assert "cache deny all" in lines


def test_egress_proxy_runs_unprivileged_on_a_read_only_root(compose: dict[str, Any]) -> None:
    proxy = compose["services"]["egress-proxy"]
    assert proxy["image"] == "ubuntu/squid:6.6-24.04_edge"
    assert proxy["user"] == "proxy"
    assert proxy["read_only"] is True
    assert proxy["cap_drop"] == ["ALL"]
    assert proxy["security_opt"] == ["no-new-privileges:true"]
    assert "ports" not in proxy
    # The config is an environment variable, so a new bucket or region recreates the container.
    assert "SQUID_CONF" in " ".join(proxy["entrypoint"])
```

Also extend `test_only_caddy_publishes_ports_80_and_443` needs no change (proxy publishes nothing).

- [ ] **Step 2: Run to verify they fail**

Run: `cd infra && uv run pytest tests/test_host.py -k "egress or reaches_only or production_services" -q`
Expected: FAIL (`KeyError: 'egress-proxy'` / `'networks'`).

- [ ] **Step 3: Implement in `deploy/on-premise/compose.yaml`**

Top-level, after `x-logging`:

```yaml
networks:
  # The worker parses untrusted PDFs (PRD §9.10). On this network it reaches Postgres and the egress proxy only:
  # an internal network has no route out of the VM and no external DNS.
  worker:
    internal: true
```

`postgres` gains `networks: [default, worker]`.

New service (before `worker`):

```yaml
  # The worker's only way out (#153): CONNECT to its AWS endpoints, plain HTTP to the instance metadata service (the
  # instance profile's credentials); everything else gets 403. The config is an environment variable rather than a
  # file so a changed bucket or region recreates the container (Compose can't inject a config into a read-only one).
  egress-proxy:
    image: ubuntu/squid:6.6-24.04_edge
    restart: unless-stopped
    logging: *logging
    entrypoint: [bash, -c, 'printf "%s" "$$SQUID_CONF" > /tmp/squid.conf && exec squid -N -f /tmp/squid.conf']
    environment:
      SQUID_CONF: |
        http_port 3128
        # Exact names, no reverse lookups (-n): not bare s3.*, whose path-style requests could name any bucket.
        acl aws dstdomain -n ${DOCUMENTS_BUCKET:?}.s3.amazonaws.com ${DOCUMENTS_BUCKET:?}.s3.${AWS_REGION:?}.amazonaws.com sqs.${AWS_REGION:?}.amazonaws.com ssm.${AWS_REGION:?}.amazonaws.com bedrock-runtime.${AWS_REGION:?}.amazonaws.com
        acl imds dstdomain -n 169.254.169.254
        acl tls port 443
        acl http port 80
        acl CONNECT method CONNECT
        http_access allow CONNECT aws tls
        http_access allow !CONNECT imds http
        http_access deny all
        # IMDSv2 refuses a token request that carries X-Forwarded-For.
        forwarded_for delete
        via off
        httpd_suppress_version_string on
        cache deny all
        connect_timeout 10 seconds
        pinger_enable off
        acl healthcheck src 127.0.0.1/32 ::1
        access_log stdio:/dev/stdout !healthcheck
        cache_log stdio:/dev/stderr
        pid_filename none
        logfile_rotate 0
        shutdown_lifetime 1 seconds
    user: proxy
    read_only: true
    tmpfs: [/tmp:size=1m]
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    mem_limit: 128m
    networks: [default, worker]
    healthcheck:
      # A request Squid refuses (403) without a DNS lookup: it answers, and the healthcheck ACL keeps it out of the log.
      test:
        - CMD
        - bash
        - -c
        - "exec 3<>/dev/tcp/127.0.0.1/3128 && printf 'GET http://healthcheck/ HTTP/1.0\\r\\n\\r\\n' >&3 && grep -q '^HTTP/1.1 ' <&3"
      interval: 15s
      timeout: 5s
      retries: 5
```

Note: the test's `acls["aws"]` list uses `${DOCUMENTS_BUCKET}`; write the expected values to match exactly what you put in compose.yaml (use `${DOCUMENTS_BUCKET:?}` / `${AWS_REGION:?}` in both, like the rest of the file).

`worker` gains:

```yaml
      # Its only way out (egress-proxy); botocore also fetches the instance profile's credentials through it.
      HTTP_PROXY: http://egress-proxy:3128
      HTTPS_PROXY: http://egress-proxy:3128
      AWS_METADATA_SERVICE_TIMEOUT: "2"  # one more hop to IMDS than the default 1 s assumes
      AWS_METADATA_SERVICE_NUM_ATTEMPTS: "3"
```

and `networks: [worker]`, and under `depends_on`: `egress-proxy: {condition: service_healthy}`.

Update the header comment's last sentence: the worker "…reaches only Postgres and, through the egress proxy, its AWS endpoints (#153); deploy.sh checks the running worker's isolation and egress after every deploy."

- [ ] **Step 4: Run the tests**

Run: `cd infra && uv run pytest tests/test_host.py -q`
Expected: PASS (all, including LF-line-ending and existing compose tests).

- [ ] **Step 5: Commit**

```bash
git add deploy/on-premise/compose.yaml infra/tests/test_host.py
git commit -m "Put the on-premise worker behind an allowlisting egress proxy (#153)"
```
(body: why: the worker parses untrusted PDFs; internal network + Squid allowlist; firewall rules rejected because AWS service IPs are shared.)

### Task 2: Deploy-time egress check

**Files:**
- Create: `deploy/on-premise/check-egress.py`
- Modify: `deploy/on-premise/deploy.sh` (after the isolation check, before the agent/MCP check)
- Test: `infra/tests/test_check_egress.py` (new), `infra/tests/test_host.py` (deploy.sh structure, LF endings list)

**Interfaces:**
- Consumes: worker env from Task 1 (`HTTPS_PROXY`, `AWS_REGION`, `SMART_TUTOR_DOCUMENTS_BUCKET`, `SMART_TUTOR_INGEST_QUEUE_URL`, `SMART_TUTOR_MAX_PAGES_PARAM`).
- Produces: `check-egress.py` exit codes: `0` = blocked and allowed paths both as expected; `2` = the block holds but a needed destination is unreachable; anything else (`1` = a leak, or the script crashed) = treat as a leak. Module functions (for tests): `leaks() -> list[str]`, `unreachable() -> list[str]`, `main() -> int`.

- [ ] **Step 1: Write the failing tests** in `infra/tests/test_check_egress.py`:

```python
"""deploy/on-premise/check-egress.py: the deploy-time proof of the worker's egress block (#153)."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).parents[2] / "deploy/on-premise/check-egress.py"


@pytest.fixture
def check() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_egress", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_passes_when_blocked_and_the_needed_destinations_answer(check: ModuleType, monkeypatch) -> None:
    monkeypatch.setattr(check, "leaks", lambda: [])
    monkeypatch.setattr(check, "unreachable", lambda: [])
    assert check.main() == 0


def test_a_leak_exits_1_even_when_aws_is_unreachable(check: ModuleType, monkeypatch, capsys) -> None:
    monkeypatch.setattr(check, "leaks", lambda: ["direct 1.1.1.1:443 connected"])
    monkeypatch.setattr(check, "unreachable", lambda: ["sqs: timed out"])
    assert check.main() == 1
    err = capsys.readouterr().err
    assert "direct 1.1.1.1:443 connected" in err and "sqs: timed out" in err


def test_an_unreachable_destination_exits_2(check: ModuleType, monkeypatch, capsys) -> None:
    monkeypatch.setattr(check, "leaks", lambda: [])
    monkeypatch.setattr(check, "unreachable", lambda: ["postgres:5432: refused"])
    assert check.main() == 2
    assert "postgres:5432: refused" in capsys.readouterr().err


def test_leaks_reports_a_direct_connection_and_a_proxy_that_lets_any_host_through(
    check: ModuleType, monkeypatch
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://egress-proxy:3128")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(check, "_connects", lambda host, port: host == "1.1.1.1")
    monkeypatch.setattr(check, "_tunnel_status", lambda host: 200)
    problems = check.leaks()
    assert any("1.1.1.1" in p for p in problems)
    assert any("example.com" in p and "200" in p for p in problems)
    assert not any("sqs.us-east-1.amazonaws.com" in p for p in problems)


def test_leaks_is_empty_when_every_probe_is_refused(check: ModuleType, monkeypatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://egress-proxy:3128")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(check, "_connects", lambda host, port: False)
    monkeypatch.setattr(check, "_tunnel_status", lambda host: 403)
    assert check.leaks() == []


def test_a_crash_is_not_exit_code_2(check: ModuleType, monkeypatch) -> None:
    # deploy.sh keeps the worker running only on 2; a crash must look like a leak (fail closed).
    def boom() -> list[str]:
        raise KeyError("SMART_TUTOR_INGEST_QUEUE_URL")

    monkeypatch.setattr(check, "leaks", lambda: [])
    monkeypatch.setattr(check, "unreachable", boom)
    with pytest.raises(KeyError):
        check.main()  # an uncaught exception exits Python with status 1
```

In `infra/tests/test_host.py`, extend `test_deploy_script_asserts_the_running_workers_isolation_and_the_inner_services`, or add a new test after it:

```python
def test_deploy_script_proves_the_workers_egress_block_and_stops_a_leaking_worker() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    check = script[script.index("up -d --wait --wait-timeout") :]
    assert 'exec -T worker python - <"$here/check-egress.py"' in check
    egress = check[check.index("Checking the worker's egress") :]
    # Exit 2 (AWS or Postgres unreachable) fails the deploy; anything else stops the worker first.
    assert egress.index("2)") < egress.index('docker stop "$worker"') < egress.index("exit 1")
```

and add `ON_PREMISE_DIR / "check-egress.py"` to the list in `test_files_the_vm_runs_keep_lf_line_endings`.

- [ ] **Step 2: Run to verify they fail**

Run: `cd infra && uv run pytest tests/test_check_egress.py tests/test_host.py -k "egress or line_endings" -q`
Expected: FAIL (script missing).

- [ ] **Step 3: Write `deploy/on-premise/check-egress.py`**

```python
"""Proves the on-premise worker's egress block (#153). deploy.sh runs it inside the worker after every deploy:

    docker compose exec -T worker python - <check-egress.py

The worker must not reach the internet, directly or through the proxy, while S3, SQS, SSM, Bedrock, and Postgres
work. The AWS calls are read-only and use the instance profile, whose credentials come through the proxy too.
Exit 0: as expected. Exit 2: blocked, but a needed destination is unreachable. Exit 1, or a crash: treat as a leak.
"""

import http.client
import os
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

ARBITRARY_HOST = "example.com"
ARBITRARY_IP = "1.1.1.1"
TIMEOUT = 10


def _connects(host: str, port: int) -> bool:
    try:
        socket.create_connection((host, port), timeout=TIMEOUT).close()
    except OSError:
        return False
    return True


def _tunnel_status(host: str) -> int:
    """The proxy's answer to CONNECT host:443 (200 when it opens the tunnel, 403 when it refuses)."""
    proxy = urllib.parse.urlsplit(os.environ["HTTPS_PROXY"])
    conn = http.client.HTTPConnection(proxy.hostname, proxy.port or 3128, timeout=TIMEOUT)
    try:
        conn.request("CONNECT", f"{host}:443", headers={"Host": f"{host}:443"})
        return conn.getresponse().status
    finally:
        conn.close()


def leaks() -> list[str]:
    """Ways out that must be closed."""
    sqs_host = f"sqs.{os.environ['AWS_REGION']}.amazonaws.com"
    problems = [
        f"direct {host}:443 connected"
        for host in (ARBITRARY_HOST, ARBITRARY_IP, sqs_host)  # even an allowed host only through the proxy
        if _connects(host, 443)
    ]
    for host in (ARBITRARY_HOST, ARBITRARY_IP, f"other-{os.getpid()}.s3.amazonaws.com"):
        status = _tunnel_status(host)
        if status != 403:
            problems.append(f"the proxy answered {status} to CONNECT {host}:443, not 403")
    return problems


def unreachable() -> list[str]:
    """Destinations the worker needs that don't answer."""
    import boto3  # in the worker image; imported here so the tests run without it

    region = os.environ["AWS_REGION"]
    calls = {
        "S3": lambda: boto3.client("s3", region_name=region).head_bucket(
            Bucket=os.environ["SMART_TUTOR_DOCUMENTS_BUCKET"]
        ),
        "SQS": lambda: boto3.client("sqs", region_name=region).get_queue_attributes(
            QueueUrl=os.environ["SMART_TUTOR_INGEST_QUEUE_URL"], AttributeNames=["QueueArn"]
        ),
        "SSM": lambda: boto3.client("ssm", region_name=region).get_parameter(
            Name=os.environ["SMART_TUTOR_MAX_PAGES_PARAM"]
        ),
    }
    problems = []
    for name, call in calls.items():
        try:
            call()
        except Exception as error:  # noqa: BLE001 - every failure is reported, none is fatal here
            problems.append(f"{name}: {type(error).__name__}: {error}")
    # Bedrock: any HTTP answer proves the route; an invocation would cost money.
    try:
        urllib.request.urlopen(f"https://bedrock-runtime.{region}.amazonaws.com/", timeout=TIMEOUT)
    except urllib.error.HTTPError:
        pass
    except OSError as error:
        problems.append(f"Bedrock: {error}")
    if not _connects("postgres", 5432):
        problems.append("Postgres: postgres:5432 refused or timed out")
    return problems


def main() -> int:
    leaked, missing = leaks(), unreachable()
    for problem in leaked:
        print(f"The worker can reach what it must not: {problem}", file=sys.stderr)
    for problem in missing:
        print(f"The worker cannot reach what it needs: {problem}", file=sys.stderr)
    if leaked:
        return 1
    if missing:
        return 2
    print("The worker reaches S3, SQS, SSM, Bedrock, and Postgres, and nothing else")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Notes for the implementer: `urllib.request.urlopen` honours `HTTPS_PROXY` from the environment; an `HTTPError` (e.g. 404/403 from AWS) is a successful round trip. On a proxy refusal urllib raises `OSError` ("Tunnel connection failed: 403"), which is reported. `_tunnel_status` must not raise on a refusal — a 403 is a normal response to `CONNECT`.

- [ ] **Step 4: Call it from `deploy/on-premise/deploy.sh`**, right after the isolation check's `fi` and before `# The agent and MCP server have no public route`:

```bash
# The worker reaches only Postgres and, through egress-proxy, its AWS endpoints (#153). Prove it from inside: a leak
# stops the worker like a failed isolation check; an unreachable AWS endpoint or database only fails the deploy.
echo "Checking the worker's egress"
status=0
"${compose[@]}" exec -T worker python - <"$here/check-egress.py" || status=$?
case $status in
  0) ;;
  2) echo "The worker cannot reach a destination it needs (see above)" >&2; exit 1 ;;
  *)
    docker stop "$worker" >/dev/null
    echo "Stopped the worker: its egress is not limited (see above)" >&2
    exit 1
    ;;
esac
```

Update the header comment of deploy.sh step 3 to mention it ("…checks the running worker's isolation and egress…"), if the header lists the checks.

- [ ] **Step 5: Run the tests**

Run: `cd infra && uv run pytest -q`
Expected: PASS (including `test_scripts_parse` for deploy.sh).

- [ ] **Step 6: Commit**

```bash
git add deploy/on-premise/check-egress.py deploy/on-premise/deploy.sh infra/tests/test_check_egress.py infra/tests/test_host.py
git commit -m "Prove the worker's egress block on every on-premise deploy (#153)"
```

### Task 3: Record it — PRD, ADR, runbook

**Files:**
- Modify: `sdd/prd.md` (status line v2.31 → v2.32; new "Changes from v2.31" row at the top of the change table; the ingestion-worker component row (~line 336); risk table: rewrite "Malicious PDFs against the parser" row, delete the "No worker egress allowlist on-premise (known gap)" row)
- Create: `sdd/adr/0014-on-premise-worker-egress-proxy.md`; Modify: `sdd/adr/README.md` (index row)
- Modify: `docs/runbooks/on-premise-deploy.md` ("What runs where" row "AWS from the containers"; deploy step 4; "Worker isolation" paragraph; troubleshooting rows)

- [ ] **Step 1: PRD.** Status line `Draft v2.32`. Change row: "**Changes from v2.31** | On-premise worker egress (#153): the worker is on a Compose network with no route out of the VM. It reaches Postgres directly, and through an allowlisting proxy (`egress-proxy`, Squid) only the documents bucket, SQS, SSM, and Bedrock runtime in its region, plus the instance metadata service for its credentials. Every deploy proves this from inside the worker and stops a worker that can reach anything else (§9.10). The known gap is closed. No product behavior changes. |". Component row: replace "egress limited by NetworkPolicy in native-cloud (on-premise allowlist pending, §9.10)" with "egress limited to AWS endpoints and PostgreSQL (native-cloud: NetworkPolicy; on-premise: an internal network and an allowlisting proxy, §9.10)". Risk row "Malicious PDFs": "Worker isolation: non-root, read-only root filesystem, no capabilities, resource limits, per-file timeout. Egress only to AWS endpoints and PostgreSQL: native-cloud by NetworkPolicy; on-premise by an internal Compose network whose only way out is a proxy that allows the documents bucket, SQS, SSM, Bedrock runtime, and the instance metadata service by exact name (ADR 0014). The deploy checks both and stops a worker that fails either." Delete the known-gap row.
- [ ] **Step 2: ADR 0014** (format of `sdd/adr/README.md`; Status: accepted; Date: 2026-10-10). Context: ADR 0012 left the egress allowlist as a gap; the worker needs S3, SQS, SSM, Bedrock, IMDS, Postgres; the VPC has no NAT and only an S3 gateway endpoint, so AWS services are reached at public, shared IPs. Decision: internal Compose network + Squid allowlist by exact host name; config as an interpolated env var; deploy-time `check-egress.py`. Alternatives rejected: host firewall (iptables `DOCKER-USER`) by IP — AWS's published ranges for SQS/SSM/Bedrock include every customer's EC2 addresses, so an IP allowlist doesn't block exfiltration; interface VPC endpoints for SQS/SSM/Bedrock — would make IP rules meaningful, but ~$7/month each plus private DNS changes for the whole VM; a custom proxy — more code to trust than Squid. Consequences: one more container (~20 MB RAM); a new AWS endpoint for the worker means editing the allowlist (the deploy check fails the deploy until then); the allowed AWS hosts could still be used against another account's resources that permit anonymous access — the bucket is pinned by name, SQS/SSM/Bedrock calls are signed with our role; native-cloud unchanged. README index row: `| [0014](0014-on-premise-worker-egress-proxy.md) | On-premise worker egress: an internal Compose network whose only way out is an allowlisting Squid proxy (closes 0012's gap) |`.
- [ ] **Step 3: Runbook** `docs/runbooks/on-premise-deploy.md`. Title: add #153 → `# On-premise deploy (#148, #149, #153)`. "AWS from the containers" row: add "The worker reaches them only through `egress-proxy` (an allowlist; ADR 0014)". Deploy step 4: add "and proves the worker's egress block from inside it (`check-egress.py`): a direct connection or a proxied one to another host must fail, and S3, SQS, SSM, Bedrock, and Postgres must answer". Replace "The worker can still reach the internet: the egress allowlist is #153." with a **Worker egress.** paragraph: how to run the check by hand (`dc exec -T worker python - < /opt/smart-tutor/on-premise/check-egress.py`), the proxy's log (`dc logs --tail 50 egress-proxy`, `TCP_DENIED/403` lines are refused requests), and that a new AWS endpoint for the worker is added to the `acl aws` line in compose.yaml. Troubleshooting rows: "`Stopped the worker: its egress is not limited`" → compose.yaml lost the worker's `networks: [worker]`, or the proxy's rules allow more; restore and redeploy. "`The worker cannot reach a destination it needs`" → `dc logs egress-proxy` shows `TCP_DENIED` for the host the worker needs (a new endpoint: add it to `acl aws`) or AWS errors; the worker keeps running. And update the existing "A document stays processing" row to mention `dc logs egress-proxy`.
- [ ] **Step 4: Check** `cd infra && uv run pytest -q` (PRD/runbook are not tested; make sure nothing else references the removed risk row: `grep -rn "egress allowlist" sdd docs CONTEXT.md` returns only ADR 0012 and ADR 0014).
- [ ] **Step 5: Commit**: "Record the on-premise worker's egress allowlist (#153)" — body: PRD v2.32, ADR 0014, runbook.
