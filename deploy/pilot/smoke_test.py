#!/usr/bin/env python3
"""Smoke-test the pilot's public address after a deploy (#59): the web app shell, the API, and Keycloak's issuer.

Usage: python3 deploy/pilot/smoke_test.py https://<id>.cloudfront.net [--deadline-seconds 600] [--interval-seconds 15]

Retries until every check passes or the deadline passes, because new targets and a new distribution answer 502/503 for
a few minutes. Exit 0 when all checks pass, 1 otherwise. Standard library only; never sends a token.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass

REQUEST_TIMEOUT = 10
REALM_PATH = "/auth/realms/smart-tutor"


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes


def fetch(url: str) -> Response:
    request = urllib.request.Request(
        url, headers={"User-Agent": "smart-tutor-smoke-test"}
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as r:
            return Response(
                r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
            )
    except urllib.error.HTTPError as e:
        return Response(e.code, {k.lower(): v for k, v in e.headers.items()}, e.read())


def check_web(base: str) -> str | None:
    r = fetch(f"{base}/")
    if r.status != 200 or b'<div id="root">' not in r.body:
        return f"/ gave {r.status}, expected 200 with the app shell"
    return None


def check_health(base: str) -> str | None:
    r = fetch(f"{base}/api/healthz")
    return None if r.status == 200 else f"/api/healthz gave {r.status}, expected 200"


def check_api_rejects_anonymous(base: str) -> str | None:
    r = fetch(f"{base}/api/me")
    challenge = r.headers.get("www-authenticate", "")
    if r.status != 401 or not challenge.startswith("Bearer"):
        return f"/api/me without a token gave {r.status} (WWW-Authenticate {challenge!r}), expected 401 Bearer"
    return None


def check_issuer(base: str) -> str | None:
    expected = f"{base}{REALM_PATH}"
    r = fetch(f"{base}{REALM_PATH}/.well-known/openid-configuration")
    if r.status != 200:
        return f"openid-configuration gave {r.status}, expected 200"
    try:
        issuer = json.loads(r.body).get("issuer")
    except ValueError:
        return "openid-configuration is not JSON"
    return (
        None if issuer == expected else f"issuer is {issuer!r}, expected {expected!r}"
    )


CHECKS = (check_web, check_health, check_api_rejects_anonymous, check_issuer)


def run_checks(url: str) -> list[str]:
    base = url.rstrip("/")
    failures = []
    for check in CHECKS:
        try:
            failure = check(base)
        except (urllib.error.URLError, OSError) as e:
            failure = f"{check.__name__}: {e}"
        if failure:
            failures.append(failure)
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url")
    parser.add_argument("--deadline-seconds", type=float, default=600)
    parser.add_argument("--interval-seconds", type=float, default=15)
    args = parser.parse_args(argv)

    deadline = time.monotonic() + args.deadline_seconds
    attempt = 0
    while True:
        attempt += 1
        failures = run_checks(args.url)
        if not failures:
            print(f"smoke test passed on attempt {attempt}: {args.url}")
            return 0
        if time.monotonic() + args.interval_seconds > deadline:
            print(f"smoke test FAILED after {attempt} attempts against {args.url}:")
            for failure in failures:
                print(f"  - {failure}")
            return 1
        print(
            f"attempt {attempt}: {len(failures)} check(s) failing, retrying in {args.interval_seconds:g}s"
        )
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    sys.exit(main())
