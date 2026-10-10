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
        except Exception as error:  # every failure is reported, none is fatal here
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
