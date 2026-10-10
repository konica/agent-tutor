"""The post-deploy smoke test (deploy/pilot/smoke_test.py) against a local fake of the public address."""

import base64
import email.message
import email.parser
import email.policy
import hashlib
import http.client
import importlib.util
import json
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from urllib.parse import parse_qs, urlsplit

import pytest

SCRIPT = Path(__file__).parents[2] / "deploy/pilot/smoke_test.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("smoke_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = load()

Route = tuple[int, dict[str, str], bytes]


def healthy(base: str) -> dict[str, Route]:
    issuer = f"{base}/auth/realms/smart-tutor"
    return {
        "/": (
            200,
            {"Content-Type": "text/html"},
            b'<html><body><div id="root"></div></body></html>',
        ),
        "/api/healthz": (200, {"Content-Type": "application/json"}, b'{"status":"ok"}'),
        "/api/me": (
            401,
            {"WWW-Authenticate": "Bearer", "Content-Type": "application/json"},
            b'{"detail":"x"}',
        ),
        "/auth/realms/smart-tutor/.well-known/openid-configuration": (
            200,
            {"Content-Type": "application/json"},
            json.dumps({"issuer": issuer}).encode(),
        ),
    }


@pytest.fixture
def site() -> Iterator[tuple[str, Callable[[dict[str, Route]], None], list[str]]]:
    """A local server whose routes the test sets; it records whether any request carried Authorization."""
    routes: dict[str, Route] = {}
    auth_seen: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.headers.get("Authorization"):
                auth_seen.append(self.path)
            status, headers, body = routes.get(self.path, (404, {}, b""))
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"

    def set_routes(new: dict[str, Route]) -> None:
        routes.clear()
        routes.update(new)

    yield base, set_routes, auth_seen
    server.shutdown()


def test_healthy_site_passes(site) -> None:
    base, set_routes, auth_seen = site
    set_routes(healthy(base))
    assert smoke.run_checks(base) == []
    assert auth_seen == []  # the smoke test never sends a token


def test_trailing_slash_in_url_is_ignored(site) -> None:
    base, set_routes, _ = site
    set_routes(healthy(base))
    assert smoke.run_checks(base + "/") == []


def test_wrong_issuer_fails(site) -> None:
    base, set_routes, _ = site
    routes = healthy(base)
    routes["/auth/realms/smart-tutor/.well-known/openid-configuration"] = (
        200,
        {"Content-Type": "application/json"},
        json.dumps({"issuer": "http://internal-alb/auth/realms/smart-tutor"}).encode(),
    )
    set_routes(routes)
    failures = smoke.run_checks(base)
    assert len(failures) == 1 and "issuer" in failures[0]


def test_api_me_must_challenge_with_bearer(site) -> None:
    base, set_routes, _ = site
    routes = healthy(base)
    routes["/api/me"] = (401, {}, b"")  # no WWW-Authenticate
    set_routes(routes)
    failures = smoke.run_checks(base)
    assert len(failures) == 1 and "/api/me" in failures[0]


def test_api_me_answering_200_without_token_fails(site) -> None:
    base, set_routes, _ = site
    routes = healthy(base)
    routes["/api/me"] = (200, {"Content-Type": "application/json"}, b"{}")
    set_routes(routes)
    assert any("/api/me" in f for f in smoke.run_checks(base))


def test_web_without_app_shell_fails(site) -> None:
    base, set_routes, _ = site
    routes = healthy(base)
    routes["/"] = (200, {"Content-Type": "text/html"}, b"<html>maintenance</html>")
    set_routes(routes)
    assert any(f.startswith("/ ") or "app shell" in f for f in smoke.run_checks(base))


def test_unreachable_site_reports_every_check() -> None:
    failures = smoke.run_checks(
        "http://127.0.0.1:9"
    )  # nothing listens on the discard port
    assert len(failures) == 4


def test_retries_until_the_site_settles(site) -> None:
    base, set_routes, _ = site
    set_routes({p: (502, {}, b"") for p in healthy(base)})
    timer = threading.Timer(0.5, lambda: set_routes(healthy(base)))
    timer.start()
    assert (
        smoke.main([base, "--deadline-seconds", "10", "--interval-seconds", "0.2"]) == 0
    )


def test_gives_up_with_the_failing_checks(site, capsys) -> None:
    base, set_routes, _ = site
    set_routes({p: (503, {}, b"") for p in healthy(base)})
    assert (
        smoke.main([base, "--deadline-seconds", "0.5", "--interval-seconds", "0.1"])
        == 1
    )
    out = capsys.readouterr().out
    assert "/api/me" in out and "openid-configuration" in out


@pytest.mark.parametrize("body", [b"[]", b"null"])
def test_discovery_document_that_is_not_an_object_fails_without_raising(
    site, body
) -> None:
    base, set_routes, _ = site
    routes = healthy(base)
    routes["/auth/realms/smart-tutor/.well-known/openid-configuration"] = (
        200,
        {"Content-Type": "application/json"},
        body,
    )
    set_routes(routes)
    failures = smoke.run_checks(base)
    assert len(failures) == 1 and "openid-configuration" in failures[0]


def test_broken_response_body_fails_one_check_and_the_rest_still_run(
    site, monkeypatch
) -> None:
    base, set_routes, _ = site
    set_routes(healthy(base))
    real_fetch = smoke.fetch

    def truncated_health(url: str) -> smoke.Response:
        if url.endswith("/api/healthz"):
            raise http.client.IncompleteRead(b"")
        return real_fetch(url)

    monkeypatch.setattr(smoke, "fetch", truncated_health)
    failures = smoke.run_checks(base)
    assert len(failures) == 1 and "check_health" in failures[0]


# --- End-to-end mode: sign in, upload, document ready, ask, cited answer -------------------------------------------

USERNAME = "learner@example.com"
PASSWORD = "s3cret-Pa55word!"
TOKEN = "access-token-xyz"
CODE = "auth-code-123"
DOC = "11111111-1111-1111-1111-111111111111"
OTHER_DOC = "22222222-2222-2222-2222-222222222222"
UPLOAD = "33333333-3333-3333-3333-333333333333"
SUBJECT = "44444444-4444-4444-4444-444444444444"
THREAD = "55555555-5555-5555-5555-555555555555"
REALM = "/auth/realms/smart-tutor"


def _sse(event: str, data: object) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


def _form(body: bytes) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(body.decode(), keep_blank_values=True).items()}


class FakePilot:
    """The pilot's public address: web shell, Keycloak login form and token endpoint, S3 presigned POST, and the API."""

    def __init__(self, base: str) -> None:
        self.base = base
        # Scenario knobs
        self.final_state = "awaiting_subjects"
        self.failure_reason: str | None = None
        self.suggestions: list[dict[str, object]] = [
            {"subject_id": None, "name": "Brand new", "origin": "new"},
            {"subject_id": SUBJECT, "name": "Testing", "origin": "catalog"},
        ]
        self.cited_document = DOC
        self.stream: list[bytes] | None = None
        self.delete_status = 204
        # What happened
        self.state = "processing"
        self.document_polls = 0
        self.auth_request: dict[str, str] = {}
        self.followed_app_redirect = False
        self.s3_authorization: str | None = None
        self.s3_parts: list[tuple[str, bytes]] = []
        self.chosen: dict[str, object] | None = None
        self.questions: list[str] = []
        self.deleted: list[str] = []
        self.api_without_token: list[str] = []

    def _json(self, status: int, data: object) -> Route:
        return status, {"Content-Type": "application/json"}, json.dumps(data).encode()

    def _document(self) -> dict[str, object]:
        return {
            "document_id": DOC,
            "title": "smoke test",
            "state": self.state,
            "failure_reason": self.failure_reason if self.state == "failed" else None,
        }

    def _login_form(self, message: str = "") -> Route:
        action = (
            f"{self.base}{REALM}/login-actions/authenticate"
            "?session_code=sc&amp;execution=ex&amp;client_id=smart-tutor-web"
        )
        page = (
            f"<html><body><p>{message}</p>"
            '<form id="kc-form-login" onsubmit="login.disabled = true; return true;" '
            f'action="{action}" method="post">'
            '<input name="username"><input name="password" type="password">'
            '<input type="hidden" name="credentialId" value=""></form></body></html>'
        )
        cookie = f"KC_SESSION=abc; Path={REALM}/"
        return 200, {"Content-Type": "text/html", "Set-Cookie": cookie}, page.encode()

    def handle(
        self, method: str, target: str, headers: dict[str, str], body: bytes
    ) -> Route:
        parts = urlsplit(target)
        path, query = parts.path, {k: v[0] for k, v in parse_qs(parts.query).items()}
        site = healthy(self.base)
        if method == "GET" and path in site and not query:
            return site[path]
        if method == "GET" and path == "/" and "code" in query:
            self.followed_app_redirect = True
            return site["/"]
        if path == f"{REALM}/protocol/openid-connect/auth":
            self.auth_request = query
            return self._login_form()
        if path == f"{REALM}/login-actions/authenticate" and method == "POST":
            form = _form(body)
            ok = (
                query.get("execution") == "ex"
                and "KC_SESSION=abc" in headers.get("cookie", "")
                and form.get("username") == USERNAME
                and form.get("password") == PASSWORD
                and "credentialId" in form
            )
            if not ok:
                return self._login_form("Invalid username or password.")
            state = self.auth_request["state"]
            return (
                302,
                {
                    "Location": f"{self.base}/?state={state}&session_state=ss&code={CODE}"
                },
                b"",
            )
        if path == f"{REALM}/protocol/openid-connect/token" and method == "POST":
            form = _form(body)
            digest = hashlib.sha256(form.get("code_verifier", "").encode()).digest()
            challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
            if (
                form.get("grant_type") == "authorization_code"
                and form.get("client_id") == "smart-tutor-web"
                and form.get("code") == CODE
                and form.get("redirect_uri") == self.base + "/"
                and challenge == self.auth_request.get("code_challenge")
            ):
                return self._json(200, {"access_token": TOKEN, "token_type": "Bearer"})
            return self._json(400, {"error": "invalid_grant"})
        if path == "/s3/bucket" and method == "POST":
            self.s3_authorization = headers.get("authorization")
            message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
                f"Content-Type: {headers['content-type']}\r\n\r\n".encode() + body
            )
            assert isinstance(message, email.message.EmailMessage)
            for part in message.iter_parts():
                name = part.get_param("name", header="content-disposition")
                self.s3_parts.append((str(name), part.get_payload(decode=True)))
            return 204, {}, b""
        if path.startswith("/api/"):
            if headers.get("authorization") != f"Bearer {TOKEN}":
                self.api_without_token.append(path)
                return 401, {"WWW-Authenticate": "Bearer"}, b""
            return self._api(method, path, body)
        return 404, {}, b""

    def _api(self, method: str, path: str, body: bytes) -> Route:
        if method == "POST" and path == "/api/uploads":
            assert json.loads(body)["file_name"].endswith(".pdf")
            fields = {
                "key": "uploads/x.pdf",
                "policy": "cG9saWN5",
                "x-amz-signature": "sig",
            }
            started = {
                "document_id": DOC,
                "upload_id": UPLOAD,
                "url": f"{self.base}/s3/bucket",
                "fields": fields,
            }
            return self._json(201, started)
        if method == "GET" and path == f"/api/uploads/{UPLOAD}":
            stored = bool(self.s3_parts)
            status = {
                "upload_id": UPLOAD,
                "outcome": "stored" if stored else None,
                "document_id": DOC if stored else None,
                "archived": False,
            }
            return self._json(200, status)
        if method == "GET" and path == "/api/documents":
            self.document_polls += 1
            if self.state == "processing" and self.document_polls > 1:
                self.state = self.final_state
            other = {
                "document_id": OTHER_DOC,
                "title": "other",
                "state": "ready",
                "failure_reason": None,
            }
            return self._json(200, [self._document(), other])
        if method == "GET" and path == f"/api/documents/{DOC}/subject-suggestions":
            offered = {
                "document_id": DOC,
                "title": "t",
                "summary": None,
                "suggestions": self.suggestions,
            }
            return self._json(200, offered)
        if method == "PUT" and path == f"/api/documents/{DOC}/subjects":
            self.chosen = json.loads(body)
            self.state = "ready"
            return self._json(200, self._document())
        if method == "POST" and path == "/api/threads":
            self.questions.append(json.loads(body)["question"])
            citation = {
                "n": 1,
                "chunk_id": "c1",
                "document_id": self.cited_document,
                "document_title": "t",
                "page": 1,
            }
            events = self.stream or [
                _sse("thread", {"thread_id": THREAD}),
                _sse("delta", {"text": "The passphrase is "}),
                _sse("delta", {"text": "in your document [1]."}),
                _sse("citations", {"citations": [citation]}),
                _sse("done", {}),
            ]
            return 200, {"Content-Type": "text/event-stream"}, b"".join(events)
        if method == "DELETE" and path == f"/api/documents/{DOC}":
            if self.delete_status == 204:
                self.deleted.append(DOC)
            return self.delete_status, {}, b""
        return 404, {}, b""


@pytest.fixture
def pilot(monkeypatch) -> Iterator[FakePilot]:
    monkeypatch.setenv("SMOKE_TEST_USERNAME", USERNAME)
    monkeypatch.setenv("SMOKE_TEST_PASSWORD", PASSWORD)
    holder: list[FakePilot] = []

    class Handler(BaseHTTPRequestHandler):
        def _serve(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            headers = {k.lower(): v for k, v in self.headers.items()}
            status, out_headers, out = holder[0].handle(
                self.command, self.path, headers, body
            )
            self.send_response(status)
            for k, v in out_headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        do_GET = do_POST = do_PUT = do_DELETE = _serve

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    holder.append(FakePilot(f"http://127.0.0.1:{server.server_port}"))
    yield holder[0]
    server.shutdown()


def run_end_to_end(pilot: FakePilot) -> int:
    return smoke.main(
        [
            pilot.base,
            "--end-to-end",
            "--deadline-seconds",
            "10",
            "--interval-seconds",
            "0.05",
        ]
    )


def output_without_secrets(capsys) -> str:
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert PASSWORD not in output
    assert TOKEN not in output
    assert CODE not in output
    return output


def test_end_to_end_signs_in_uploads_asks_and_cleans_up(pilot, capsys) -> None:
    assert run_end_to_end(pilot) == 0

    # Signed in with PKCE S256 through the login form, and stopped at the app's redirect instead of following it.
    assert pilot.auth_request["client_id"] == "smart-tutor-web"
    assert pilot.auth_request["redirect_uri"] == pilot.base + "/"
    assert pilot.auth_request["response_type"] == "code"
    assert pilot.auth_request["code_challenge_method"] == "S256"
    assert "openid" in pilot.auth_request["scope"].split()
    assert not pilot.followed_app_redirect
    # Uploaded every presigned field, then the file last, without a bearer token to S3.
    assert [name for name, _ in pilot.s3_parts] == [
        "key",
        "policy",
        "x-amz-signature",
        "file",
    ]
    assert pilot.s3_authorization is None
    pdf = pilot.s3_parts[-1][1]
    assert pdf.startswith(b"%PDF-") and b"passphrase is" in pdf
    # Chose the first suggestion that has a subject id, asked the passphrase question, and deleted the document.
    assert pilot.chosen == {"subject_ids": [SUBJECT], "new_names": []}
    assert pilot.questions == ["What is the Smart Tutor smoke test passphrase?"]
    assert pilot.deleted == [DOC]
    assert pilot.api_without_token == []

    assert "passed" in output_without_secrets(capsys)


def test_end_to_end_uses_one_fixed_new_subject_when_no_suggestion_has_an_id(
    pilot, capsys
) -> None:
    pilot.suggestions = [{"subject_id": None, "name": "Brand new", "origin": "new"}]
    assert run_end_to_end(pilot) == 0
    assert pilot.chosen == {"subject_ids": [], "new_names": ["Smoke testing"]}


def test_failed_document_fails_with_its_reason_and_is_still_deleted(
    pilot, capsys
) -> None:
    pilot.final_state = "failed"
    pilot.failure_reason = "This PDF has no text layer"
    assert run_end_to_end(pilot) == 1
    assert "This PDF has no text layer" in output_without_secrets(capsys)
    assert pilot.deleted == [DOC]
    assert pilot.questions == []


def test_answer_without_a_citation_of_our_document_fails(pilot, capsys) -> None:
    pilot.cited_document = OTHER_DOC
    assert run_end_to_end(pilot) == 1
    assert "citation" in output_without_secrets(capsys)
    assert pilot.deleted == [DOC]


def test_error_event_in_the_answer_fails_with_its_message(pilot, capsys) -> None:
    pilot.stream = [
        _sse("thread", {"thread_id": THREAD}),
        _sse("error", {"code": "unavailable", "message": "The tutor is unavailable"}),
    ]
    assert run_end_to_end(pilot) == 1
    assert "The tutor is unavailable" in output_without_secrets(capsys)
    assert pilot.deleted == [DOC]


def test_wrong_password_fails_sign_in_without_printing_it(
    pilot, capsys, monkeypatch
) -> None:
    monkeypatch.setenv("SMOKE_TEST_PASSWORD", "wrong-" + PASSWORD)
    assert run_end_to_end(pilot) == 1
    assert "sign" in output_without_secrets(capsys).lower()
    assert pilot.s3_parts == []


@pytest.mark.parametrize("missing", ["SMOKE_TEST_USERNAME", "SMOKE_TEST_PASSWORD"])
def test_missing_credentials_fail_with_a_message(
    pilot, capsys, monkeypatch, missing
) -> None:
    monkeypatch.delenv(missing)
    assert run_end_to_end(pilot) == 1
    assert missing in output_without_secrets(capsys)
    assert pilot.auth_request == {}


def test_cleanup_failure_is_reported_without_hiding_the_original_failure(
    pilot, capsys
) -> None:
    pilot.final_state = "failed"
    pilot.failure_reason = "This PDF has no text layer"
    pilot.delete_status = 500
    assert run_end_to_end(pilot) == 1
    output = output_without_secrets(capsys)
    assert "This PDF has no text layer" in output
    assert "clean" in output.lower() and "500" in output


def test_smoke_pdf_has_enough_text_per_page_to_not_read_as_scanned() -> None:
    text = smoke.smoke_test_text("abcd1234")
    assert "passphrase is abcd1234" in text
    assert len("".join(text.split())) >= 50
    pdf = smoke.make_pdf([text])
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
