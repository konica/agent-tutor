"""The local stack in memory for evals.learners tests: Keycloak's login form and token endpoint, the API's library
routes, and LocalStack's presigned POST. Each learner sees only their own documents, as in the real API."""

import base64
import hashlib
import itertools
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from email.parser import BytesParser
from email.policy import default
from typing import Any
from urllib.parse import parse_qs

import httpx

from evals.learners import API, ISSUER

PASSWORDS = {"learner@example.com": "learner", "learner2@example.com": "learner2"}
LOGIN_ACTION = "http://localhost:10401/realms/smart-tutor/login-actions/authenticate?session_code=s&amp;tab_id=t"
# Keycloak's cookies are Secure, which a browser still sends to http://localhost but a plain cookie jar does not.
SECURE_COOKIE = "Path=/realms/smart-tutor/; Secure; HttpOnly; SameSite=None"
BUCKET = "http://localhost:10402/smart-tutor-documents"


@dataclass
class FakeDocument:
    document_id: str
    owner: str
    sha256: str | None
    state: str = "processing"
    archived: bool = False
    can_retry: bool = True
    failure_reason: str | None = None
    subjects: list[str] = field(default_factory=list)


class FakeStack:
    def __init__(self) -> None:
        self.documents: dict[str, FakeDocument] = {}
        self.uploads: dict[str, dict[str, Any]] = {}  # upload id -> {"owner", "document_id", "outcome"}
        self.uploads_started = 0
        self.sign_ins = 0
        self.retries = 0
        self.redirect_to: str | None = None  # Keycloak sends the code to this URI instead of the requested one
        self.always_unauthorized = False  # the API answers 401 whatever the token
        self.disconnects = 0  # the next N API requests matching disconnect_if drop the connection
        self.disconnect_if: Callable[[httpx.Request], bool] = lambda request: True
        self.process: Callable[[FakeDocument], None] = lambda d: setattr(d, "state", "awaiting_subjects")
        self._ids = (f"00000000-0000-0000-0000-{n:012d}" for n in itertools.count(1))
        self._codes: dict[str, tuple[str, str]] = {}  # code -> (username, PKCE challenge)
        self._tokens: dict[str, str] = {}  # live access token -> username
        self._auth: dict[str, dict[str, str]] = {}

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    def add(self, owner: str, data: bytes, **fields: Any) -> FakeDocument:
        """A document already in `owner`'s library."""
        doc = FakeDocument(next(self._ids), owner, hashlib.sha256(data).hexdigest(), **fields)
        self.documents[doc.document_id] = doc
        return doc

    def library(self, owner: str) -> list[FakeDocument]:
        return [d for d in self.documents.values() if d.owner == owner]

    def expire_tokens(self) -> None:
        self._tokens.clear()

    # --- Keycloak ---------------------------------------------------------------------------------------------

    def _redirect_with_code(self, username: str, auth: dict[str, str]) -> httpx.Response:
        code = next(self._ids)
        self._codes[code] = (username, auth["code_challenge"])
        location = f"{self.redirect_to or auth['redirect_uri']}?state={auth['state']}&session_state=x&code={code}"
        return httpx.Response(
            302, headers={"Location": location, "Set-Cookie": f"KC_SESSION={username}; {SECURE_COOKIE}"}
        )

    @staticmethod
    def _cookies(request: httpx.Request) -> dict[str, str]:
        pairs = (c.strip().partition("=") for c in request.headers.get("cookie", "").split(";") if c.strip())
        return {name: value for name, _, value in pairs}

    def _keycloak(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/protocol/openid-connect/auth"):
            auth = dict(request.url.params)
            assert auth["client_id"] == "smart-tutor-web" and auth["code_challenge_method"] == "S256"
            sso = self._cookies(request).get("KC_SESSION")
            if sso:  # an SSO session: straight back to the app
                return self._redirect_with_code(sso, auth)
            self._auth["current"] = auth
            page = f'<html><form id="kc-form-login" action="{LOGIN_ACTION}" method="post"></form></html>'
            return httpx.Response(200, text=page, headers={"Set-Cookie": f"AUTH_SESSION_ID=a1; {SECURE_COOKIE}"})
        if path.endswith("/login-actions/authenticate"):
            assert request.url.params["tab_id"] == "t"  # the action's &amp; was unescaped
            if "AUTH_SESSION_ID" not in self._cookies(request):  # Keycloak: "Cookie not found"
                return httpx.Response(400)
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            if PASSWORDS.get(form["username"]) != form.get("password"):
                return httpx.Response(200, text='<form id="kc-form-login" action="x"></form>Invalid password')
            return self._redirect_with_code(form["username"], self._auth["current"])
        if path.endswith("/protocol/openid-connect/token"):
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            username, challenge = self._codes.pop(form["code"])
            verifier_hash = hashlib.sha256(form["code_verifier"].encode()).digest()
            assert base64.urlsafe_b64encode(verifier_hash).rstrip(b"=").decode() == challenge
            token = f"token-{next(self._ids)}"
            self._tokens[token] = username
            self.sign_ins += 1
            return httpx.Response(200, json={"access_token": token, "token_type": "Bearer"})
        return httpx.Response(404)

    # --- S3 (the worker runs as soon as the file is stored) -----------------------------------------------------

    def _s3(self, request: httpx.Request) -> httpx.Response:
        message = BytesParser(policy=default).parsebytes(
            b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.content
        )
        parts = [
            (p.get_param("name", header="content-disposition"), p.get_payload(decode=True))
            for p in message.iter_parts()
        ]
        assert parts[-1][0] == "file", "S3 needs the file as the last part"
        fields = dict(parts)
        upload = self.uploads[fields["key"].decode()]
        sha = hashlib.sha256(fields["file"]).hexdigest()
        new = self.documents[upload["document_id"]]
        existing = next(  # archived documents count here, as in the real _store
            (d for d in self.library(upload["owner"]) if d.sha256 == sha), None
        )
        if existing:  # the server-side duplicate check: the upload points at the learner's own copy
            del self.documents[new.document_id]
            upload.update(outcome="duplicate", document_id=existing.document_id)
        else:
            new.sha256 = sha
            upload["outcome"] = "stored"
            self.process(new)
        return httpx.Response(204)

    # --- API ----------------------------------------------------------------------------------------------------

    def _view(self, doc: FakeDocument) -> dict[str, Any]:
        return {
            "document_id": doc.document_id,
            "state": doc.state,
            "archived": doc.archived,
            "can_retry": doc.can_retry,
            "failure_reason": doc.failure_reason,
            "subjects": [{"subject_id": name, "name": name} for name in doc.subjects],
        }

    def _api(self, request: httpx.Request) -> httpx.Response:
        if self.disconnects and self.disconnect_if(request):
            self.disconnects -= 1
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        user = self._tokens.get(request.headers.get("authorization", "").removeprefix("Bearer "))
        if user is None or self.always_unauthorized:
            return httpx.Response(401)
        method, path = request.method, request.url.path
        body = json.loads(request.content) if request.content else None
        if (method, path) == ("POST", "/documents/duplicate-check"):
            found = next(
                (d for d in self.library(user) if d.sha256 == body["sha256"] and not d.archived), None
            )  # as find_in_library
            return httpx.Response(200, json={"document_id": found.document_id if found else None})
        if (method, path) == ("POST", "/uploads"):
            self.uploads_started += 1
            upload_id, doc = next(self._ids), FakeDocument(next(self._ids), user, None)
            self.documents[doc.document_id] = doc
            self.uploads[upload_id] = {"owner": user, "document_id": doc.document_id, "outcome": None}
            fields = {"key": upload_id, "Content-Type": "application/pdf", "policy": "p"}
            started = {"document_id": doc.document_id, "upload_id": upload_id, "url": BUCKET, "fields": fields}
            return httpx.Response(201, json=started)
        parts = path.strip("/").split("/")
        if parts[0] == "uploads" and method == "GET":
            upload = self.uploads.get(parts[1])
            if upload is None or upload["owner"] != user:
                return httpx.Response(404)
            ready = upload["outcome"] is not None
            status = {
                "upload_id": parts[1],
                "outcome": upload["outcome"],
                "document_id": upload["document_id"] if ready else None,
                "archived": False,
            }
            return httpx.Response(200, json=status)
        if parts[0] == "documents":
            doc = self.documents.get(parts[1])
            if doc is None or doc.owner != user:
                return httpx.Response(404)
            action = parts[2] if len(parts) > 2 else None
            if (method, action) == ("GET", None):
                return httpx.Response(200, json=self._view(doc))
            if (method, action) == ("PUT", "subjects"):
                if doc.archived or doc.state not in ("awaiting_subjects", "ready"):
                    return httpx.Response(409)
                assert body["subject_ids"] == [] and 1 <= len(body["new_names"]) <= 3
                doc.subjects, doc.state = list(body["new_names"]), "ready"
                return httpx.Response(200, json=self._view(doc))
            if (method, action) == ("POST", "retry"):
                self.retries += 1
                doc.state, doc.failure_reason = "processing", None
                self.process(doc)
                return httpx.Response(204)
            if (method, action) == ("POST", "restore"):
                doc.archived = False
                return httpx.Response(200, json=self._view(doc))
        return httpx.Response(404)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(ISSUER):
            return self._keycloak(request)
        if url.startswith(BUCKET):
            return self._s3(request)
        if url.startswith(API):
            return self._api(request)
        return httpx.Response(404)
