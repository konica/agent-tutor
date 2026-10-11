"""Load the eval learners' libraries from the seed corpus through the real upload path (PRD §10.3, issue #222).

Usage: uv run --extra eval python -m evals.learners [--timeout 900]

Needs the Compose stack with the app profile (or the host processes, README "Run the app") and your AWS profile: the
worker describes and embeds each PDF with Bedrock. Downloads the seed PDFs (evals.corpus), then for each learner in
seed_corpus/learners.yaml signs in through Keycloak's login form, uploads the documents their library lacks (the
learner's own duplicate check skips the rest), chooses each document's labeled subjects, and waits until every one is
ready. Exits 1 when a document fails or the time runs out. Running it again uploads nothing.
"""

import argparse
import base64
import hashlib
import html
import re
import secrets
import sys
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

from evals.corpus import DOWNLOADS, CorpusError, SeedDocument, download, load_manifest

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

    def _send_secure_cookies_to_localhost(self) -> None:
        # Keycloak's cookies are Secure; browsers send them to http://localhost, httpx's cookie jar does not.
        for cookie in self._http.cookies.jar:
            if cookie.domain in ("localhost", "localhost.local", "127.0.0.1"):
                cookie.secure = False

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
        self._send_secure_cookies_to_localhost()
        r = self._http.get(f"{oidc}/auth", params=params, follow_redirects=False)
        if not r.is_redirect:  # no SSO session yet: fill in the login form
            action = _login_form_action(r.text)
            if r.status_code != 200 or action is None:
                raise LoadError(f"{self.username}: Keycloak's login page gave {r.status_code} without a login form")
            form = {"username": self.username, "password": self._password, "credentialId": ""}
            self._send_secure_cookies_to_localhost()
            r = self._http.post(r.url.join(action), data=form, follow_redirects=False)
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


@dataclass
class _Pending:
    """A seed document on its way into the learner's library."""

    seed: SeedDocument
    upload_id: str | None = None
    document_id: str | None = None
    found: bool = False  # already in the library before this run
    retried: bool = False
    state: str = "uploading"
    last_error: str | None = None  # the last dropped connection while polling


def _advance(tutor: Tutor, p: _Pending) -> bool:
    """One look at a pending document: True once it is ready; LoadError when it can't become ready."""
    if p.document_id is None:
        status = tutor.call("GET", f"/uploads/{p.upload_id}")
        if status["document_id"] is None:
            return False  # the worker hasn't hashed the file yet
        p.document_id = status["document_id"]  # a server-side duplicate points at the learner's own copy
    path = f"/documents/{p.document_id}"
    doc = tutor.call("GET", path)
    p.state = doc["state"]
    if p.state == "processing":
        return False
    if p.state == "failed":
        if p.found and doc["can_retry"] and not p.retried:  # left failed by an earlier run: one more attempt
            tutor.call("POST", f"{path}/retry", ok=204)
            p.retried = True
            return False
        raise LoadError(f"failed: {doc['failure_reason']}")
    if doc["archived"]:
        tutor.call("POST", f"{path}/restore")
    if p.state == "awaiting_subjects":
        chosen = tutor.call("PUT", f"{path}/subjects", {"subject_ids": [], "new_names": list(p.seed.subjects)})
        if chosen["state"] != "ready":
            raise LoadError(f"is {chosen['state']} after choosing its subjects")
    return True


def load_library(
    tutor: Tutor,
    seeds: Sequence[SeedDocument],
    paths: Mapping[str, Path],
    *,
    timeout: float,
    interval: float,
    log: Callable[[str], None] = print,
) -> list[str]:
    """Bring the learner's library to hold every seed document, ready with its labeled subjects. A document already
    there is not uploaded again; a ready one keeps the subjects it has. The problems; empty when all are ready."""
    deadline = time.monotonic() + timeout
    pending: list[_Pending] = []
    problems: list[str] = []
    for seed in seeds:
        try:
            found = tutor.call("POST", "/documents/duplicate-check", {"sha256": seed.sha256})["document_id"]
            if found:
                pending.append(_Pending(seed, document_id=found, found=True))
                log(f"{tutor.username} {seed.id}: already in the library")
            else:
                pending.append(_Pending(seed, upload_id=tutor.upload(seed.file_name, paths[seed.id].read_bytes())))
                log(f"{tutor.username} {seed.id}: uploaded")
        except (LoadError, httpx.HTTPError) as e:  # not retried: POST /uploads creates a document each time
            problems.append(f"{seed.id}: {e}")
    while pending:
        for p in list(pending):
            try:
                done = _advance(tutor, p)
            except LoadError as e:
                problems.append(f"{p.seed.id}: {e}")
                pending.remove(p)
                continue
            except httpx.TransportError as e:  # a dropped connection: look again next time round
                p.last_error = str(e) or type(e).__name__
                continue
            if done:
                log(f"{tutor.username} {p.seed.id}: ready")
                pending.remove(p)
        if pending and time.monotonic() >= deadline:
            problems += [
                f"{p.seed.id}: timed out after {timeout:g}s while {p.state}"
                + (f" (last error: {p.last_error})" if p.last_error else "")
                for p in pending
            ]
            break
        if pending:
            time.sleep(interval)
    return problems


def load_all(
    learners: Sequence[Learner],
    seeds: Mapping[str, SeedDocument],
    paths: Mapping[str, Path],
    *,
    connect: Callable[[], httpx.Client],
    api: str,
    issuer: str,
    app: str,
    timeout: float,
    interval: float,
    log: Callable[[str], None] = print,
) -> list[str]:
    """Load every learner's library, each in their own client (Keycloak's session cookie must not carry over)."""
    problems: list[str] = []
    for learner in learners:
        with connect() as http:
            tutor = Tutor(http, learner.username, learner.password, api=api, issuer=issuer, app=app)
            try:
                found = load_library(
                    tutor, [seeds[d] for d in learner.documents], paths, timeout=timeout, interval=interval, log=log
                )
            except (LoadError, httpx.HTTPError) as e:
                found = [f"can't load the library: {e}"]
        problems += [f"{learner.username} {p}" for p in found]
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default=API)
    parser.add_argument("--issuer", default=ISSUER)
    parser.add_argument("--app", default=APP, help="smart-tutor-web's redirect URI")
    parser.add_argument("--downloads", type=Path, default=DOWNLOADS)
    parser.add_argument("--timeout", type=float, default=900, help="seconds per learner until every document is ready")
    parser.add_argument("--interval", type=float, default=3, help="seconds between status checks")
    args = parser.parse_args(argv)
    seeds = load_manifest()
    learners = load_learners(LEARNERS, seeds)
    wanted = sorted({seeds[d] for learner in learners for d in learner.documents}, key=lambda s: s.id)
    try:
        paths = download(wanted, args.downloads)
    except (CorpusError, httpx.HTTPError) as e:
        print(f"Can't download the seed corpus: {e}", file=sys.stderr)
        return 1
    problems = load_all(
        learners,
        seeds,
        paths,
        connect=lambda: httpx.Client(timeout=60),
        api=args.api.rstrip("/"),
        issuer=args.issuer.rstrip("/"),
        app=args.app,
        timeout=args.timeout,
        interval=args.interval,
    )
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
