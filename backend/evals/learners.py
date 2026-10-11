"""Load the eval learners' libraries from the seed corpus through the real upload path (PRD §10.3, issue #222).

Usage: uv run --extra eval python -m evals.learners [--timeout 900]

Needs the Compose stack with the app profile (or the host processes, README "Run the app") and your AWS profile: the
worker describes and embeds each PDF with Bedrock. Downloads the seed PDFs (evals.corpus), then for each learner in
seed_corpus/learners.yaml signs in through Keycloak's login form, uploads the documents their library lacks (the
learner's own duplicate check skips the rest), chooses each document's labeled subjects, and waits until every one is
ready. Exits 1 when a document fails or the time runs out. Running it again uploads nothing.
"""

import base64
import hashlib
import html
import re
import secrets
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

LEARNERS = Path(__file__).parent / "seed_corpus" / "learners.yaml"
API = "http://localhost:10450"
ISSUER = "http://localhost:10401/realms/smart-tutor"
APP = "http://localhost:10453/"  # smart-tutor-web's redirect URI: the code comes back to it
CLIENT_ID = "smart-tutor-web"


class LoadError(Exception):
    """A learner's library could not be loaded: sign-in failed or the API answered unexpectedly."""


@dataclass(frozen=True)
class Learner:
    username: str
    password: str
    documents: tuple[str, ...]  # seed document ids


def load_learners(path: Path, known: Collection[str]) -> list[Learner]:
    """The learners and their seed documents; every id must be in the manifest (`known`)."""
    learners = [
        Learner(entry["username"], entry["password"], tuple(entry["documents"]))
        for entry in yaml.safe_load(path.read_text(encoding="utf-8"))["learners"]
    ]
    for learner in learners:
        unknown = [d for d in learner.documents if d not in known]
        if unknown:
            raise ValueError(f"{learner.username}: not in the seed corpus manifest: {', '.join(unknown)}")
    return learners


def _login_form_action(page: str) -> str | None:
    for tag in re.findall(r"<form\b[^>]*>", page, flags=re.IGNORECASE):
        if re.search(r'\bid="kc-form-login"', tag):
            action = re.search(r'\baction="([^"]*)"', tag)
            if action:
                return html.unescape(action.group(1))
    return None


class Tutor:
    """One learner's session: Keycloak sign-in (PKCE, through the login form: direct access grants are off), then
    the API with their bearer token. Give each learner their own client: Keycloak's SSO cookie lives in it."""

    def __init__(
        self, http: httpx.Client, username: str, password: str, *, api: str = API, issuer: str = ISSUER, app: str = APP
    ) -> None:
        self._http, self.username, self._password = http, username, password
        self._api, self._issuer, self._app = api, issuer, app
        self._token: str | None = None

    def sign_in(self) -> None:
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        oidc = f"{self._issuer}/protocol/openid-connect"
        params = {
            "client_id": CLIENT_ID,
            "redirect_uri": self._app,
            "response_type": "code",
            "scope": "openid",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        r = self._http.get(f"{oidc}/auth", params=params)
        if not r.is_redirect:  # no SSO session yet: fill in the login form
            action = _login_form_action(r.text)
            if r.status_code != 200 or action is None:
                raise LoadError(f"{self.username}: Keycloak's login page gave {r.status_code} without a login form")
            form = {"username": self.username, "password": self._password, "credentialId": ""}
            r = self._http.post(r.url.join(action), data=form)
        if not r.is_redirect:
            raise LoadError(
                f"{self.username}: sign-in refused (wrong password in learners.yaml, or a required action?)"
            )
        back = r.url.join(r.headers["location"])
        if str(back.copy_with(query=None, fragment=None)) != self._app or back.params.get("state") != state:
            raise LoadError(f"{self.username}: sign-in redirected to {back}, expected {self._app}")
        code = back.params.get("code")
        if not code:
            raise LoadError(f"{self.username}: Keycloak refused: {back.params.get('error')}")
        token = self._http.post(
            f"{oidc}/token",
            data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "code": code,
                "redirect_uri": self._app,
                "code_verifier": verifier,
            },
        )
        if token.status_code != 200:
            raise LoadError(f"{self.username}: the token endpoint gave {token.status_code}")
        self._token = token.json()["access_token"]

    def _send(self, method: str, path: str, body: object | None) -> httpx.Response:
        if self._token is None:
            self.sign_in()
        headers = {"Authorization": f"Bearer {self._token}"}
        return self._http.request(method, f"{self._api}{path}", json=body, headers=headers)

    def call(self, method: str, path: str, body: object | None = None, ok: int = 200) -> Any:
        """The API's JSON answer (None when empty) as this learner; signs in again once when the token expired."""
        r = self._send(method, path, body)
        if r.status_code == 401:
            self._token = None
            r = self._send(method, path, body)
        if r.status_code != ok:
            raise LoadError(f"{method} {path} gave {r.status_code}, expected {ok}: {r.text[:200]}")
        return r.json() if r.content else None

    def upload(self, file_name: str, data: bytes) -> str:
        """Start an upload and POST the PDF to its presigned URL, as the browser does; the upload id."""
        started = self.call("POST", "/uploads", {"file_name": file_name}, ok=201)
        stored = self._http.post(
            started["url"], data=started["fields"], files={"file": (file_name, data, "application/pdf")}
        )
        if stored.status_code not in (200, 201, 204):
            raise LoadError(f"{file_name}: the storage POST gave {stored.status_code}: {stored.text[:200]}")
        return str(started["upload_id"])
