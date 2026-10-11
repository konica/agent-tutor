#!/usr/bin/env python3
"""Smoke-test the pilot's public address after a deploy (#59): the web app shell, the API, and Keycloak's issuer.

Usage:
  python3 deploy/pilot/smoke_test.py <url> [--deadline-seconds 600] [--interval-seconds 15]
  SMOKE_TEST_USERNAME=... SMOKE_TEST_PASSWORD=... python3 deploy/pilot/smoke_test.py <url> --end-to-end
  LANGSMITH_API_KEY=... SMOKE_TEST_USERNAME=... SMOKE_TEST_PASSWORD=... python3 deploy/pilot/smoke_test.py <url> --end-to-end --trace-project smart-tutor-on-premise

<url> is the public address, e.g. https://<id>.cloudfront.net or the on-premise https://<host>.

Retries until every check passes or the deadline passes, because new targets and a new distribution answer 502/503 for
a few minutes. Without --end-to-end it never sends a token.

--end-to-end then walks a learner's path (#149): sign in through Keycloak's login form (PKCE, client smart-tutor-web),
upload a one-page PDF holding a per-run passphrase, wait until it is ready (choosing its subjects), ask for the
passphrase, and require a cited answer from that document. It deletes the document afterwards, also on failure;
the thread is kept, as every thread is. The same deadline covers the whole run. Use a dedicated test learner: the
document's subject may add one subject, "Smoke testing", to the shared catalog. Credentials come from the
environment and are never printed.

--trace-project then reads the ask's run id from the conversation's turns and waits for its trace in that LangSmith
project (#229): named `ask`, with the run metadata of PRD §10.4, and holding neither the access token nor the
username. LANGSMITH_ENDPOINT defaults to https://api.smith.langchain.com. The key is never printed.

Exit 0 when everything passes, 1 otherwise. Standard library only.
"""

import argparse
import base64
import hashlib
import html
import http.client
import http.cookiejar
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

REQUEST_TIMEOUT = 10
REALM_PATH = "/auth/realms/smart-tutor"
CLIENT_ID = "smart-tutor-web"
QUESTION = "What is the Smart Tutor smoke test passphrase?"
NEW_SUBJECT = "Smoke testing"  # one fixed name, so the shared catalog gains at most one subject from smoke tests
ANSWER_TIMEOUT = 120  # the agent may think for a while before its first event
TRACE_METADATA = (
    "deployment",
    "chat_model",
    "embedding_model",
    "thread_id",
    "learner_hash",
    "limited",
    "decline",
    "chunks",
)
QUERY_SELECT = [
    "id",
    "name",
    "run_type",
    "inputs",
    "outputs",
    "extra",
    "events",
    "error",
    "tags",
    "parent_run_id",
    "trace_id",
]
DEFAULT_LANGSMITH_ENDPOINT = "https://api.smith.langchain.com"


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
        document = json.loads(r.body)
    except ValueError:
        return "openid-configuration is not JSON"
    if not isinstance(document, dict):
        return "openid-configuration is not a JSON object"
    issuer = document.get("issuer")
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
        except (http.client.HTTPException, OSError) as e:
            failure = f"{check.__name__}: {e}"
        if failure:
            failures.append(failure)
    return failures


# --- End-to-end: sign in, upload, document ready, ask, cited answer (#149) ------------------------------------------


class SmokeTestError(Exception):
    """One step of the end-to-end run failed; the message says which and why (never a secret)."""


def _escape(line: str) -> str:
    return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[str]) -> bytes:
    """A PDF with one page per string, one Helvetica text line per newline (ported from backend/tests/fakes/pdfs.py)."""
    count = len(pages)
    font_id = 3 + 2 * count
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(count))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode())
    for i, text in enumerate(pages):
        content_id = 4 + 2 * i
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode()
        )
        if text:
            lines = " T* ".join(f"({_escape(line)}) Tj" for line in text.split("\n"))
            stream = f"BT /F1 12 Tf 72 720 Td 14 TL {lines} ET".encode("latin-1")
        else:
            stream = b""
        objects.append(
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def smoke_test_text(run_id: str) -> str:
    """The test PDF's one page: the passphrase plus enough text that the worker doesn't take it for a scan."""
    return "\n".join(
        [
            f"The Smart Tutor smoke test passphrase is {run_id}.",
            "This document was uploaded by the pilot smoke test after a deploy.",
            "It checks that a learner can upload a PDF, that the worker reads and indexes it,",
            "and that the tutor answers a question about it with a citation of this page.",
            "The smoke test deletes this document when it finishes.",
        ]
    )


def _multipart(
    fields: dict[str, str], file_name: str, content: bytes
) -> tuple[bytes, str]:
    """A multipart/form-data body for an S3 presigned POST: every field, then the file part last."""
    boundary = f"smoke-test-{secrets.token_hex(16)}"
    body = bytearray()
    for name, value in fields.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        body += value.encode() + b"\r\n"
    body += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file_name}"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode()
    body += content + f"\r\n--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def urljoin(base: str, url: str) -> str:
    """`url` resolved against the public address (a presigned URL or form action may be relative)."""
    return urllib.parse.urljoin(f"{base}/", url)


class _StopAtApp(urllib.request.HTTPRedirectHandler):
    """Follows Keycloak's redirects but stops at the app's redirect URI, whose Location carries the code."""

    def __init__(self, redirect_uri: str) -> None:
        self.redirect_uri = redirect_uri

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if newurl.split("?", 1)[0].split("#", 1)[0] == self.redirect_uri:
            return None  # urllib then raises HTTPError(302), which _Session.request returns as the response
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _json(r: Response, step: str) -> object:
    try:
        return json.loads(r.body)
    except ValueError:
        raise SmokeTestError(f"{step}: the answer is not JSON") from None


class _Session:
    """One learner's session: one cookie jar, a bearer token once signed in, and the run's deadline."""

    def __init__(self, base: str, deadline: float, interval: float) -> None:
        self.base = base
        self.redirect_uri = f"{base}/"
        self.deadline = deadline
        self.interval = interval
        self.token: str | None = None
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
            _StopAtApp(self.redirect_uri),
        )

    def timeout(self, limit: float = REQUEST_TIMEOUT) -> float:
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise SmokeTestError("the deadline passed")
        return min(limit, left)

    def open(
        self,
        method: str,
        url: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        bearer: bool = False,
        timeout: float = REQUEST_TIMEOUT,
    ) -> http.client.HTTPResponse | urllib.error.HTTPError:
        all_headers = {"User-Agent": "smart-tutor-smoke-test", **(headers or {})}
        if bearer:
            all_headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            urljoin(self.base, url), data=data, headers=all_headers, method=method
        )
        try:
            return self.opener.open(request, timeout=self.timeout(timeout))
        except urllib.error.HTTPError as e:
            return e

    def request(self, method: str, url: str, **kwargs: object) -> Response:
        with self.open(method, url, **kwargs) as r:  # type: ignore[arg-type]
            return Response(
                r.status or 0, {k.lower(): v for k, v in r.headers.items()}, r.read()
            )

    def api(self, method: str, path: str, body: object | None = None) -> Response:
        data = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"} if data is not None else {}
        return self.request(method, path, data=data, headers=headers, bearer=True)

    def wait(self, what: str) -> None:
        if time.monotonic() + self.interval > self.deadline:
            raise SmokeTestError(f"the deadline passed while waiting for {what}")
        time.sleep(self.interval)


def sign_in(s: _Session, username: str, password: str) -> None:
    """Keycloak's authorization-code flow with PKCE S256, through the login form (direct access grants are off)."""
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    state = secrets.token_urlsafe(16)
    oidc = f"{REALM_PATH}/protocol/openid-connect"
    query = urllib.parse.urlencode(
        {
            "client_id": CLIENT_ID,
            "redirect_uri": s.redirect_uri,
            "response_type": "code",
            "scope": "openid",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    page = s.request("GET", f"{oidc}/auth?{query}")
    if page.status != 200:
        raise SmokeTestError(
            f"sign-in: the login page gave {page.status}, expected 200"
        )
    action = _login_form_action(page.body.decode("utf-8", "replace"))
    form = urllib.parse.urlencode(
        {"username": username, "password": password, "credentialId": ""}
    ).encode()
    r = s.request(
        "POST",
        action,
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if r.status not in (301, 302, 303, 307, 308):
        raise SmokeTestError(
            f"sign-in: the login form gave {r.status}, expected a redirect to the app "
            "(wrong SMOKE_TEST_USERNAME or SMOKE_TEST_PASSWORD, or a required action on the account?)"
        )
    location = urljoin(s.base, r.headers.get("location", ""))
    target, _, raw_query = location.partition("?")
    params = urllib.parse.parse_qs(raw_query)
    if target != s.redirect_uri:
        raise SmokeTestError(
            f"sign-in: redirected to {target!r}, expected {s.redirect_uri!r}"
        )
    if "error" in params:
        raise SmokeTestError(f"sign-in: Keycloak refused: {params['error'][0]}")
    if params.get("state") != [state] or not params.get("code"):
        raise SmokeTestError(
            "sign-in: the redirect to the app lacks the state or the code"
        )
    token_form = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": params["code"][0],
            "redirect_uri": s.redirect_uri,
            "code_verifier": verifier,
        }
    ).encode()
    r = s.request(
        "POST",
        f"{oidc}/token",
        data=token_form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if r.status != 200:
        raise SmokeTestError(
            f"sign-in: the token endpoint gave {r.status}, expected 200"
        )
    tokens = _json(r, "sign-in")
    token = tokens.get("access_token") if isinstance(tokens, dict) else None
    if not isinstance(token, str) or not token:
        raise SmokeTestError("sign-in: the token endpoint returned no access token")
    s.token = token


def _login_form_action(page: str) -> str:
    for tag in re.findall(r"<form\b[^>]*>", page, flags=re.IGNORECASE):
        if re.search(r'\bid="kc-form-login"', tag):
            action = re.search(r'\baction="([^"]*)"', tag)
            if action:
                return html.unescape(action.group(1))
    raise SmokeTestError("sign-in: the login page has no kc-form-login form")


@dataclass
class _Run:
    """What the run created, so cleanup knows what to delete."""

    run_id: str
    document_id: str | None = None
    thread_id: str | None = None


def upload(s: _Session, run: _Run) -> str:
    """Start the upload, POST the PDF to the presigned URL; the upload id."""
    file_name = f"smoke-test-{run.run_id}.pdf"
    r = s.api("POST", "/api/uploads", {"file_name": file_name})
    if r.status != 201:
        raise SmokeTestError(f"upload: POST /api/uploads gave {r.status}, expected 201")
    started = _json(r, "upload")
    if not isinstance(started, dict):
        raise SmokeTestError("upload: POST /api/uploads did not return an object")
    # Created for this run, so ours to delete; never a document the upload status may point to as a duplicate.
    run.document_id = str(started["document_id"])
    body, content_type = _multipart(
        {str(k): str(v) for k, v in dict(started["fields"]).items()},
        file_name,
        make_pdf([smoke_test_text(run.run_id)]),
    )
    r = s.request(
        "POST", str(started["url"]), data=body, headers={"Content-Type": content_type}
    )
    if r.status not in (200, 201, 204):
        raise SmokeTestError(f"upload: the storage POST gave {r.status}, expected 204")
    return str(started["upload_id"])


def wait_until_ready(s: _Session, run: _Run, upload_id: str) -> None:
    """Wait for the upload to be stored and the document processed, then choose its subjects."""
    while True:
        r = s.api("GET", f"/api/uploads/{upload_id}")
        if r.status != 200:
            raise SmokeTestError(f"upload status gave {r.status}, expected 200")
        status = _json(r, "upload status")
        if isinstance(status, dict) and status.get("outcome") == "duplicate":
            raise SmokeTestError(
                "upload: the server took the smoke-test PDF for a duplicate of an existing document"
            )
        if isinstance(status, dict) and status.get("document_id"):
            break
        s.wait("the upload to be stored")
    document_id = run.document_id
    while True:
        r = s.api("GET", "/api/documents")
        if r.status != 200:
            raise SmokeTestError(f"GET /api/documents gave {r.status}, expected 200")
        documents = _json(r, "documents")
        listed = documents if isinstance(documents, list) else []
        mine = [
            d
            for d in listed
            if isinstance(d, dict) and d.get("document_id") == document_id
        ]
        if not mine:
            raise SmokeTestError("the uploaded document is not in the library")
        state = mine[0].get("state")
        if state == "failed":
            raise SmokeTestError(
                f"the document failed to process: {mine[0].get('failure_reason')}"
            )
        if state in ("awaiting_subjects", "ready"):
            break
        s.wait("the document to be processed")
    if state == "ready":
        return
    r = s.api("GET", f"/api/documents/{document_id}/subject-suggestions")
    if r.status != 200:
        raise SmokeTestError(f"subject suggestions gave {r.status}, expected 200")
    offered = _json(r, "subject suggestions")
    suggestions = offered.get("suggestions", []) if isinstance(offered, dict) else []
    known = [
        x["subject_id"]
        for x in suggestions
        if isinstance(x, dict) and x.get("subject_id")
    ]
    choice = (
        {"subject_ids": known[:1], "new_names": []}
        if known
        else {"subject_ids": [], "new_names": [NEW_SUBJECT]}
    )
    r = s.api("PUT", f"/api/documents/{document_id}/subjects", choice)
    if r.status != 200:
        raise SmokeTestError(f"choosing subjects gave {r.status}, expected 200")
    chosen = _json(r, "choosing subjects")
    if not isinstance(chosen, dict) or chosen.get("state") != "ready":
        got = chosen.get("state") if isinstance(chosen, dict) else None
        raise SmokeTestError(
            f"after choosing subjects the document is {got!r}, expected 'ready'"
        )


def _sse_events(lines: Iterator[bytes]) -> Iterator[tuple[str, object]]:
    """(event, data) for each server-sent event."""
    event, data = "message", list[str]()
    for raw in lines:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line:
            if data:
                try:
                    parsed = json.loads("\n".join(data))
                except ValueError:
                    raise SmokeTestError(
                        f"ask: the {event!r} event's data is not JSON"
                    ) from None
                yield event, parsed
            event, data = "message", []
        elif line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data.append(line[len("data:") :].lstrip())


def ask(s: _Session, run: _Run) -> None:
    """Ask for the passphrase; require a thread, a citation of our document, and done."""
    body = json.dumps({"question": QUESTION}).encode()
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    with s.open(
        "POST",
        "/api/threads",
        data=body,
        headers=headers,
        bearer=True,
        timeout=ANSWER_TIMEOUT,
    ) as r:
        if r.status == 409:
            raise SmokeTestError(
                "ask: the API says the learner has no ready documents (409)"
            )
        if r.status != 200:
            raise SmokeTestError(
                f"ask: POST /api/threads gave {r.status}, expected 200"
            )
        seen: set[str] = set()
        cited: set[str] = set()
        for event, data in _sse_events(iter(r.readline, b"")):
            seen.add(event)
            if event == "thread" and isinstance(data, dict):
                run.thread_id = str(data.get("thread_id"))
            if event == "error":
                detail = data if isinstance(data, dict) else {}
                raise SmokeTestError(
                    f"ask: the answer ended with an error: {detail.get('code')}: {detail.get('message')}"
                )
            if event == "citations" and isinstance(data, dict):
                cited |= {
                    str(c.get("document_id"))
                    for c in data.get("citations", [])
                    if isinstance(c, dict)
                }
            if event == "done":
                break
    for required in ("thread", "citations", "done"):
        if required not in seen:
            raise SmokeTestError(f"ask: the answer had no {required!r} event")
    if run.document_id not in cited:
        raise SmokeTestError(
            "ask: the answer has no citation of the smoke-test document"
        )


def _langsmith(
    s: _Session,
    method: str,
    endpoint: str,
    path: str,
    api_key: str,
    body: object | None = None,
) -> Response:
    """A LangSmith REST call: the API key only, never the learner's bearer token."""
    return s.request(
        method,
        endpoint.rstrip("/") + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
    )


def check_trace(
    s: _Session,
    run: _Run,
    project: str,
    endpoint: str,
    api_key: str,
    username: str,
) -> str:
    """Wait for the ask's trace in the LangSmith project; require its name, metadata, and no leaked secrets."""
    r = s.api("GET", f"/api/threads/{run.thread_id}/turns")
    if r.status != 200:
        raise SmokeTestError(
            f"trace: GET the thread's turns gave {r.status}, expected 200"
        )
    turns = _json(r, "trace")
    last = turns[-1] if isinstance(turns, list) and turns else None
    run_id = last.get("run_id") if isinstance(last, dict) else None
    if not isinstance(run_id, str) or not run_id:
        raise SmokeTestError("trace: the turn has no run id")

    def refused(r: Response) -> bool:
        return r.status in (401, 403)

    quoted = urllib.parse.quote(project, safe="")
    r = _langsmith(s, "GET", endpoint, f"/sessions?name={quoted}", api_key)
    if refused(r):
        raise SmokeTestError("trace: LangSmith refused the API key")
    if r.status != 200:
        raise SmokeTestError(f"trace: LangSmith projects gave {r.status}, expected 200")
    sessions = _json(r, "trace")
    project_id = next(
        (
            x.get("id")
            for x in (sessions if isinstance(sessions, list) else [])
            if isinstance(x, dict) and x.get("name") == project
        ),
        None,
    )
    if not project_id:
        raise SmokeTestError(f"trace: no LangSmith project {project}")

    root: dict[str, object] = {}
    seen = False  # the run exists in LangSmith, finished or not
    last_other: int | None = None  # the last answer that was not 200, 404, 401, 403
    try:
        while True:
            r = _langsmith(s, "GET", endpoint, f"/runs/{run_id}", api_key)
            if refused(r):
                raise SmokeTestError("trace: LangSmith refused the API key")
            if r.status == 200:
                seen = True
                found = _json(r, "trace")
                if isinstance(found, dict):
                    extra = found.get("extra")
                    meta = extra.get("metadata") if isinstance(extra, dict) else None
                    if (
                        found.get("end_time")
                        and isinstance(meta, dict)
                        and "decline" in meta
                    ):
                        root = found
                        break
            elif r.status != 404:
                last_other = r.status
            s.wait("the ask's trace")
    except SmokeTestError as e:
        if "the deadline passed" not in str(e):
            raise
        last = f"; last answer {last_other}" if last_other else ""
        if seen:
            raise SmokeTestError(
                f"trace: run {run_id} reached LangSmith but never finished with its metadata{last}"
            ) from None
        raise SmokeTestError(
            f"trace: run {run_id} never reached LangSmith "
            f"(is tracing on, and the sampling rate trace-sampling-rate 1?){last}"
        ) from None

    if root.get("name") != "ask":
        raise SmokeTestError(
            f"trace: run {run_id} is named {root.get('name')!r}, expected 'ask'"
        )
    if root.get("session_id") != project_id:
        raise SmokeTestError(f"trace: run {run_id} is not in the project {project}")
    extra = root.get("extra")
    metadata = extra.get("metadata", {}) if isinstance(extra, dict) else {}
    missing = [k for k in TRACE_METADATA if k not in metadata]
    if missing:
        raise SmokeTestError(f"trace: the ask run lacks metadata {', '.join(missing)}")
    if metadata["thread_id"] != run.thread_id:
        raise SmokeTestError("trace: the ask run belongs to another thread")

    # The server returns some fields only when selected (as the LangSmith SDK always does),
    # so ask for the ones a secret could hide in; otherwise the scan could pass over trimmed runs.
    r = _langsmith(
        s,
        "POST",
        endpoint,
        "/runs/query",
        api_key,
        {"trace": run_id, "limit": 100, "select": QUERY_SELECT},
    )
    if refused(r):
        raise SmokeTestError("trace: LangSmith refused the API key")
    if r.status != 200:
        raise SmokeTestError(
            f"trace: LangSmith run query gave {r.status}, expected 200"
        )
    queried = _json(r, "trace")
    runs = queried.get("runs", []) if isinstance(queried, dict) else []
    blob = json.dumps([root, *runs])
    if s.token and s.token in blob:
        raise SmokeTestError("trace: the trace holds the learner's access token")
    if username and username in blob:
        raise SmokeTestError("trace: the trace names the learner (username found)")
    return f"ask trace {run_id} is in {project}"


def clean_up(s: _Session, run: _Run) -> str | None:
    """Delete the run's document; a failure message, or None. Threads are kept, so the thread stays."""
    if run.document_id is None or s.token is None:
        return None
    # Clean up even when the run used up the deadline.
    s.deadline = max(s.deadline, time.monotonic() + REQUEST_TIMEOUT)
    try:
        r = s.api("DELETE", f"/api/documents/{run.document_id}")
    except (SmokeTestError, http.client.HTTPException, OSError) as e:
        return f"clean-up: deleting document {run.document_id} failed: {e}"
    if r.status == 409:
        return f"clean-up: document {run.document_id} is still processing (409); delete it from the library later"
    if r.status not in (204, 404):
        return f"clean-up: deleting document {run.document_id} gave {r.status}, expected 204"
    return None


def run_end_to_end(
    base: str,
    deadline: float,
    interval: float,
    username: str,
    password: str,
    trace: tuple[str, str, str] | None = None,
) -> int:
    s = _Session(base, deadline, interval)
    run = _Run(secrets.token_hex(4))
    failure: str | None = None
    try:
        sign_in(s, username, password)
        print("signed in")
        upload_id = upload(s, run)
        print("uploaded")
        wait_until_ready(s, run, upload_id)
        print("document ready")
        ask(s, run)
        print("cited answer received")
        if trace:
            print(check_trace(s, run, *trace, username))
    except SmokeTestError as e:
        failure = str(e)
    except (http.client.HTTPException, OSError, KeyError, TypeError, ValueError) as e:
        failure = f"{type(e).__name__}: {e}"
    finally:
        cleanup_failure = clean_up(s, run)
    if failure or cleanup_failure:
        print(f"end-to-end smoke test FAILED against {base}:")
        for line in (failure, cleanup_failure):
            if line:
                print(f"  - {line}")
        return 1
    print(f"end-to-end smoke test passed: {base}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url")
    parser.add_argument("--deadline-seconds", type=float, default=600)
    parser.add_argument("--interval-seconds", type=float, default=15)
    parser.add_argument(
        "--end-to-end",
        action="store_true",
        help="also sign in as SMOKE_TEST_USERNAME, upload a PDF, and require a cited answer",
    )
    parser.add_argument(
        "--trace-project",
        help="also require the ask's trace in this LangSmith project (needs LANGSMITH_API_KEY)",
    )
    args = parser.parse_args(argv)

    trace: tuple[str, str, str] | None = None
    if args.trace_project:
        if not args.end_to_end:
            print("--trace-project needs --end-to-end")
            return 1
        langsmith_key = os.environ.get("LANGSMITH_API_KEY", "")
        if not langsmith_key:
            print("--trace-project needs LANGSMITH_API_KEY in the environment")
            return 1
        endpoint = os.environ.get("LANGSMITH_ENDPOINT", DEFAULT_LANGSMITH_ENDPOINT)
        trace = (args.trace_project, endpoint, langsmith_key)

    username = os.environ.get("SMOKE_TEST_USERNAME", "")
    password = os.environ.get("SMOKE_TEST_PASSWORD", "")
    if args.end_to_end:
        names = ("SMOKE_TEST_USERNAME", "SMOKE_TEST_PASSWORD")
        missing = [n for n, v in zip(names, (username, password)) if not v]
        if missing:
            print(f"--end-to-end needs {' and '.join(missing)} in the environment")
            return 1

    deadline = time.monotonic() + args.deadline_seconds
    attempt = 0
    while True:
        attempt += 1
        failures = run_checks(args.url)
        if not failures:
            print(f"smoke test passed on attempt {attempt}: {args.url}")
            if args.end_to_end:
                return run_end_to_end(
                    args.url.rstrip("/"),
                    deadline,
                    args.interval_seconds,
                    username,
                    password,
                    trace,
                )
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
