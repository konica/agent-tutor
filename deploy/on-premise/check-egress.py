"""Proves the on-premise worker's egress block (#153). check-worker.sh runs it inside the worker after every deploy and
every patch window:

    docker compose exec -T worker python - <check-egress.py

The worker must not reach the internet, directly, by DNS, or through the proxy (CONNECT to another host or port, or
plain HTTP), while S3, SQS, SSM, Bedrock, Phoenix (while tracing), Langfuse (while exporting, through the proxy), and Postgres work. The AWS calls are read-only and use the instance profile, whose credentials come through the proxy too.
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


def _resolves(name: str) -> bool:
    try:
        socket.getaddrinfo(name, 443)
    except socket.gaierror:
        return False
    return True


def _proxy() -> http.client.HTTPConnection:
    proxy = urllib.parse.urlsplit(os.environ["HTTPS_PROXY"])
    return http.client.HTTPConnection(proxy.hostname, proxy.port or 3128, timeout=TIMEOUT)


def _tunnel_status(host: str, port: int = 443) -> int:
    """The proxy's answer to CONNECT host:port (200 when it opens the tunnel, 403 when it refuses)."""
    conn = _proxy()
    try:
        conn.request("CONNECT", f"{host}:{port}", headers={"Host": f"{host}:{port}"})
        return conn.getresponse().status
    finally:
        conn.close()


def _proxied_get_status(url: str) -> int:
    """The proxy's answer to a plain-HTTP GET of an absolute URL (403 when it refuses)."""
    conn = _proxy()
    try:
        conn.request("GET", url)
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
    # A name that exists: any answer means the worker has a DNS resolver outside the VM.
    if _resolves(ARBITRARY_HOST):
        problems.append(f"DNS resolved {ARBITRARY_HOST}")
    url = f"http://{ARBITRARY_HOST}/"
    status = _proxied_get_status(url)
    if status != 403:
        problems.append(f"the proxy answered {status} to GET {url}, not 403")
    tunnels = [(host, 443) for host in (ARBITRARY_HOST, ARBITRARY_IP, f"other-{os.getpid()}.s3.amazonaws.com")]
    tunnels.append((sqs_host, 80))  # an allowed host, but only on 443
    tunnels.append(("api.smith.langchain.com", 443))  # LangSmith left the allowlist (ADR 0017)
    for host, port in tunnels:
        status = _tunnel_status(host, port)
        if status != 403:
            problems.append(f"the proxy answered {status} to CONNECT {host}:{port}, not 403")
    return problems


def _aws_problems(region: str) -> list[str]:
    import boto3  # in the worker image; imported here so the tests run without it

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
        except Exception as error:  # every failure is reported, none is fatal here
            problems.append(f"{name}: {type(error).__name__}: {error}")
    return problems


def _tracing() -> bool:
    """The worker traces when it has a Phoenix URL and its key (deploy.sh leaves the key empty without the secret)."""
    return bool(os.environ.get("SMART_TUTOR_PHOENIX_URL")) and bool(os.environ.get("SMART_TUTOR_PHOENIX_API_KEY"))


def _langfuse() -> bool:
    """The worker exports to Langfuse when it has the URL and both keys (deploy.sh leaves the keys empty without them)."""
    return all(
        os.environ.get(name)
        for name in ("SMART_TUTOR_LANGFUSE_URL", "SMART_TUTOR_LANGFUSE_PUBLIC_KEY", "SMART_TUTOR_LANGFUSE_SECRET_KEY")
    )


def unreachable() -> list[str]:
    """Destinations the worker needs that don't answer."""
    region = os.environ["AWS_REGION"]
    problems = _aws_problems(region)
    # Bedrock: any HTTP answer proves the route; an invocation would cost money.
    try:
        urllib.request.urlopen(f"https://bedrock-runtime.{region}.amazonaws.com/", timeout=TIMEOUT)
    except urllib.error.HTTPError:
        pass
    except OSError as error:
        problems.append(f"Bedrock: {error}")
    # Phoenix (the ingest traces), on the worker's internal network: any HTTP answer proves the route.
    if _tracing():
        url = os.environ["SMART_TUTOR_PHOENIX_URL"].rstrip("/") + "/healthz"
        direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            direct.open(url, timeout=TIMEOUT)
        except urllib.error.HTTPError:
            pass
        except OSError as error:
            problems.append(f"Phoenix: {error}")
    # Langfuse, through the proxy (its host is on the allowlist): the tunnel opening proves the route. It is off
    # 18:00-07:00 (ADR 0022), when Squid answers 502/503; tracing is non-critical (ADR 0023), so that only gets a notice.
    if _langfuse():
        host = urllib.parse.urlsplit(os.environ["SMART_TUTOR_LANGFUSE_URL"]).hostname or ""
        status = _tunnel_status(host, 443)
        if status == 403:
            problems.append(f"Langfuse: the egress proxy refuses {host}")
        elif status != 200:
            print(
                f"Notice: Langfuse at {host} didn't answer through the proxy ({status}); it is off 18:00-07:00",
                file=sys.stdout,
            )
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
    phoenix = "Phoenix (tracing on), " if _tracing() else ""
    langfuse = "Langfuse (through the proxy), " if _langfuse() else ""
    print(f"The worker reaches S3, SQS, SSM, Bedrock, {phoenix}{langfuse}and Postgres, and nothing else")
    return 0


if __name__ == "__main__":
    sys.exit(main())
