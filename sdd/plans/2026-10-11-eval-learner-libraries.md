# Eval learners' libraries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command (`uv run --extra eval python -m evals.learners`) downloads the seed corpus, verifies it, and loads both eval learners' libraries on the local stack through the real upload path, idempotently (issue #222).

**Architecture:** Two small modules in `backend/evals/`. `corpus.py` reads `seed_corpus/manifest.yaml` and downloads each PDF into `data/seed_corpus/`, refusing bytes whose SHA-256 differs. `learners.py` reads `seed_corpus/learners.yaml` (which seed documents each realm learner holds), signs each learner in through Keycloak's login form (PKCE, client `smart-tutor-web`, like `deploy/pilot/smoke_test.py`), and drives the API exactly as the web app does: duplicate check → `POST /uploads` → presigned POST to LocalStack S3 → upload status → document state → choose the labeled subjects → ready. A document already in the learner's library is never uploaded again.

**Tech Stack:** Python 3.12, httpx (core dependency), PyYAML (via `eval` extra and langchain), pytest with `httpx.MockTransport`.

**Spec:** GitHub issue #222 (parent #220, PRD §10.3). No PRD change: no product behavior changes.

## Global Constraints

- Local URLs: API `http://localhost:10450` (no `/api` prefix), Keycloak issuer `http://localhost:10401/realms/smart-tutor`, web redirect URI `http://localhost:10453/` (the only redirect `smart-tutor-web` allows). All overridable by flags.
- Direct access grants are off on every client: sign in through the login form (`<form id="kc-form-login" action=...>`), then exchange the code with the PKCE verifier.
- Access tokens last 900 s (realm `accessTokenLifespan`); a 401 means sign in again once.
- A learner's library is only theirs: one `httpx.Client` (one cookie jar) per learner — Keycloak's SSO cookie would otherwise sign learner 2 in as learner 1.
- Upload limit on the local stack: 20 per learner per hour (LocalStack SSM). Only new documents count.
- Subjects are chosen as `new_names` = the manifest's labeled subject names; the API reuses an existing subject with the same name (PRD D20).
- `/data/` is git-ignored; downloaded PDFs go to `<repo>/data/seed_corpus/<arXiv ref>.pdf` (the names `web/src/features/viewer/fixtures/README.md` already uses), `<id>.pdf` for `url` sources.
- Code style: ruff line length 120, docstrings say what/why in one or two sentences, like `evals/highlight_fixture.py`. `mypy` checks only `src/`; still type-annotate everything.
- Tests live in `backend/tests/unit/evals/`; add `"."` to `[tool.pytest.ini_options] pythonpath` so `import evals` works.

## Review Focus

1. **Shared cookie jar across learners** → learner 2 silently gets learner 1's token and documents. Pinned by `test_each_learner_signs_in_as_themselves` (Task 3).
2. **Second run re-uploads** (e.g. duplicate check skipped or wrong hash) → new documents and chunks. Pinned by `test_a_second_run_uploads_nothing` (Task 3).
3. **A document stuck processing** must end the run with a timeout problem, not hang. Pinned by `test_a_document_still_processing_times_out` (Task 3).
4. **Token expiry during a long wait** (900 s) → 401s abort the run. Pinned by `test_an_expired_token_signs_in_again` (Task 2).
5. **A changed or truncated download** must never be uploaded or kept. Pinned by `test_a_download_with_the_wrong_hash_is_refused` (Task 1).

---

### Task 1: Seed corpus manifest and download

**Files:**
- Create: `backend/evals/corpus.py`
- Create: `backend/tests/unit/evals/test_corpus.py`
- Modify: `backend/pyproject.toml` (`pythonpath = ["tests", "."]`)

**Interfaces:**
- Produces: `SeedDocument(id: str, url: str, sha256: str, subjects: tuple[str, ...], file_name: str)` (frozen dataclass); `load_manifest(path: Path = MANIFEST) -> dict[str, SeedDocument]`; `download(documents: Iterable[SeedDocument], dest: Path = DOWNLOADS, fetch: Callable[[str], bytes] = fetch_url) -> dict[str, Path]`; `sha256_of(data: bytes) -> str`; `CorpusError(Exception)`; constants `MANIFEST`, `DOWNLOADS`.

- [ ] **Step 1: Write the failing tests** (`backend/tests/unit/evals/test_corpus.py`)

```python
"""The seed corpus: the manifest's documents and their verified download (PRD §10.3)."""

from pathlib import Path

import pytest

from evals.corpus import CorpusError, SeedDocument, download, load_manifest, sha256_of

PDF = b"%PDF-1.7 seed"


def _seed(data: bytes = PDF) -> SeedDocument:
    return SeedDocument("react-2022", "https://arxiv.org/pdf/2210.03629v3", sha256_of(data), ("LLM agents",), "2210.03629v3.pdf")


def test_the_manifest_lists_each_document_with_its_source_hash_and_subjects() -> None:
    seeds = load_manifest()
    react = seeds["react-2022"]
    assert react.url == "https://arxiv.org/pdf/2210.03629v3"
    assert react.file_name == "2210.03629v3.pdf"
    assert react.sha256 == "f285b0971ae4a790e402fb93966bed3adde2cf0a04977d08b2b40d6ab0cace69"
    assert react.subjects == ("LLM agents",)
    assert seeds["self-rag-2023"].subjects == ("Retrieval-augmented generation", "LLM agents")


def test_a_missing_pdf_is_downloaded_and_verified(tmp_path: Path) -> None:
    fetched: list[str] = []

    def fetch(url: str) -> bytes:
        fetched.append(url)
        return PDF

    paths = download([_seed()], tmp_path, fetch)
    assert fetched == ["https://arxiv.org/pdf/2210.03629v3"]
    assert paths == {"react-2022": tmp_path / "2210.03629v3.pdf"}
    assert paths["react-2022"].read_bytes() == PDF


def test_a_pdf_already_downloaded_is_not_fetched_again(tmp_path: Path) -> None:
    (tmp_path / "2210.03629v3.pdf").write_bytes(PDF)

    def fetch(url: str) -> bytes:
        raise AssertionError("fetched again")

    assert download([_seed()], tmp_path, fetch) == {"react-2022": tmp_path / "2210.03629v3.pdf"}


def test_a_changed_local_pdf_is_downloaded_again(tmp_path: Path) -> None:
    (tmp_path / "2210.03629v3.pdf").write_bytes(b"truncated")
    download([_seed()], tmp_path, lambda url: PDF)
    assert (tmp_path / "2210.03629v3.pdf").read_bytes() == PDF


def test_a_download_with_the_wrong_hash_is_refused(tmp_path: Path) -> None:
    with pytest.raises(CorpusError, match="react-2022"):
        download([_seed()], tmp_path, lambda url: b"something else")
    assert not (tmp_path / "2210.03629v3.pdf").exists()
```

- [ ] **Step 2: Add `"."` to pytest's pythonpath and run the tests to see them fail**

In `backend/pyproject.toml`: `pythonpath = ["tests", "."]  # so tests can `import fakes` and `import evals``.
Run: `cd backend && uv run pytest tests/unit/evals/test_corpus.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'evals.corpus'`).

- [ ] **Step 3: Implement `backend/evals/corpus.py`**

```python
"""The seed corpus (PRD §10.3): the documents in seed_corpus/manifest.yaml, downloaded into data/seed_corpus/.

Usage: uv run --extra eval python -m evals.corpus [--dest ../data/seed_corpus]
Fetches each PDF that is missing or changed and refuses bytes whose SHA-256 differs from the manifest's.
"""

import argparse
import hashlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

MANIFEST = Path(__file__).parent / "seed_corpus" / "manifest.yaml"
DOWNLOADS = Path(__file__).parents[2] / "data" / "seed_corpus"  # <repo>/data is git-ignored
FETCH_TIMEOUT = 60


class CorpusError(Exception):
    """A seed document can't be used: an unknown source, or bytes that don't match the manifest."""


@dataclass(frozen=True)
class SeedDocument:
    id: str
    url: str
    sha256: str
    subjects: tuple[str, ...]  # the labeled subjects, chosen for it when it is loaded into a library
    file_name: str  # the file's name in data/seed_corpus/ and the name it is uploaded under


def _seed(entry: dict[str, Any]) -> SeedDocument:
    source = entry["source"]
    if source["type"] == "arxiv":
        url, file_name = f"https://arxiv.org/pdf/{source['ref']}", f"{source['ref']}.pdf"
    elif source["type"] == "url":
        url, file_name = source["ref"], f"{entry['id']}.pdf"
    else:
        raise CorpusError(f"{entry['id']}: unknown source type {source['type']!r}")
    return SeedDocument(entry["id"], url, entry["sha256"], tuple(entry["subjects"]), file_name)


def load_manifest(path: Path = MANIFEST) -> dict[str, SeedDocument]:
    """The manifest's documents by id."""
    entries = yaml.safe_load(path.read_text(encoding="utf-8"))["documents"]
    return {e["id"]: _seed(e) for e in entries}


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_url(url: str) -> bytes:
    response = httpx.get(url, follow_redirects=True, timeout=FETCH_TIMEOUT)
    response.raise_for_status()
    return response.content


def download(
    documents: Iterable[SeedDocument], dest: Path = DOWNLOADS, fetch: Callable[[str], bytes] = fetch_url
) -> dict[str, Path]:
    """Each document's verified PDF in `dest`, by id; fetched only when missing or changed."""
    dest.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for seed in documents:
        path = dest / seed.file_name
        if not path.exists() or sha256_of(path.read_bytes()) != seed.sha256:
            data = fetch(seed.url)
            if sha256_of(data) != seed.sha256:
                raise CorpusError(f"{seed.id}: {seed.url} has SHA-256 {sha256_of(data)}, the manifest says {seed.sha256}")
            path.write_bytes(data)
        paths[seed.id] = path
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, default=DOWNLOADS)
    args = parser.parse_args()
    for seed_id, path in download(load_manifest().values(), args.dest).items():
        print(f"{seed_id}: {path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest tests/unit/evals/test_corpus.py -q` → PASS. Then `uv run ruff check . && uv run ruff format --check .`.

- [ ] **Step 5: Commit**

`git add backend/evals/corpus.py backend/tests/unit/evals backend/pyproject.toml && git commit` — subject: `Download the seed corpus verified against its manifest`.

---

### Task 2: Learner assignments and the learner's session (sign-in and API calls)

**Files:**
- Create: `backend/evals/seed_corpus/learners.yaml`
- Create: `backend/evals/learners.py` (this task: `Learner`, `load_learners`, `LoadError`, `Tutor`, URL constants)
- Create: `backend/tests/fakes/evals_stack.py` (in-memory Keycloak + API + S3 for tests; used again by Task 3)
- Create: `backend/tests/unit/evals/test_learners.py`

**Interfaces:**
- Consumes: `load_manifest`, `SeedDocument` (Task 1).
- Produces:
  - `LEARNERS: Path`, `API = "http://localhost:10450"`, `ISSUER = "http://localhost:10401/realms/smart-tutor"`, `APP = "http://localhost:10453/"`, `CLIENT_ID = "smart-tutor-web"`.
  - `Learner(username: str, password: str, documents: tuple[str, ...])` frozen dataclass; `load_learners(path: Path, known: Collection[str]) -> list[Learner]` (raises `ValueError` naming unknown ids).
  - `LoadError(Exception)`.
  - `Tutor(http: httpx.Client, username: str, password: str, *, api: str = API, issuer: str = ISSUER, app: str = APP)` with `sign_in() -> None`, `call(method: str, path: str, body: object | None = None, ok: int = 200) -> Any` (parsed JSON or `None` for an empty body; raises `LoadError` on another status; signs in first when needed and once more on 401), `upload(file_name: str, data: bytes) -> str` (upload id).
  - Test fake `FakeStack` with `handler(request) -> httpx.Response`, `client() -> httpx.Client`, `documents: dict[str, FakeDocument]`, `uploads_started: int`, `sign_ins: int`, `expire_tokens()`, `process: Callable[[FakeDocument], None]` (what the worker does to a stored upload; default sets `state="awaiting_subjects"`), `add(owner, data, **fields) -> FakeDocument`.

- [ ] **Step 1: Write `learners.yaml`**

```yaml
# Synthetic learners for evals (PRD §10.3): the Compose realm's learners and the seed documents in their libraries
# (ids from manifest.yaml). Load them with `uv run --extra eval python -m evals.learners` (../README.md).
# Learner 2 holds documents learner 1 must never see, so isolation and injection evals have a second library to probe.
# Passwords are the local realm's (local/keycloak/realm-smart-tutor.json), never a deployed one's.
learners:
  - username: learner@example.com
    password: learner
    documents: [react-2022, cot-2022, reflexion-2023]
  - username: learner2@example.com
    password: learner2
    documents: [self-rag-2023]
```

- [ ] **Step 2: Write the fake stack** (`backend/tests/fakes/evals_stack.py`)

```python
"""The local stack in memory for evals.learners tests: Keycloak's login form and token endpoint, the API's library
routes, and LocalStack's presigned POST. Each learner sees only their own documents, as in the real API."""

import hashlib
import itertools
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
        self.process: Callable[[FakeDocument], None] = lambda d: setattr(d, "state", "awaiting_subjects")
        self._ids = (f"00000000-0000-0000-0000-{n:012d}" for n in itertools.count(1))
        self._codes: dict[str, tuple[str, str]] = {}  # code -> (username, PKCE challenge)
        self._tokens: dict[str, str] = {}  # live access token -> username
        self._pending: dict[str, str] = {}  # login session cookie -> PKCE challenge, state, redirect
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
        location = f"{auth['redirect_uri']}?state={auth['state']}&session_state=x&code={code}"
        return httpx.Response(302, headers={"Location": location, "Set-Cookie": f"KC_SESSION={username}; Path=/"})

    def _keycloak(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/protocol/openid-connect/auth"):
            auth = dict(request.url.params)
            assert auth["client_id"] == "smart-tutor-web" and auth["code_challenge_method"] == "S256"
            session = request.headers.get("cookie", "")
            if session.startswith("KC_SESSION="):  # an SSO session: straight back to the app
                return self._redirect_with_code(session.removeprefix("KC_SESSION="), auth)
            self._auth["current"] = auth
            page = f'<html><form id="kc-form-login" action="{LOGIN_ACTION}" method="post"></form></html>'
            return httpx.Response(200, text=page)
        if path.endswith("/login-actions/authenticate"):
            assert request.url.params["tab_id"] == "t"  # the action's &amp; was unescaped
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            if PASSWORDS.get(form["username"]) != form.get("password"):
                return httpx.Response(200, text='<form id="kc-form-login" action="x"></form>Invalid password')
            return self._redirect_with_code(form["username"], self._auth["current"])
        if path.endswith("/protocol/openid-connect/token"):
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            username, challenge = self._codes.pop(form["code"])
            verifier_hash = hashlib.sha256(form["code_verifier"].encode()).digest()
            import base64

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
        parts = [(p.get_param("name", header="content-disposition"), p.get_payload(decode=True)) for p in message.iter_parts()]
        assert parts[-1][0] == "file", "S3 needs the file as the last part"
        fields = dict(parts)
        upload = self.uploads[fields["key"].decode()]
        sha = hashlib.sha256(fields["file"]).hexdigest()
        new = self.documents[upload["document_id"]]
        existing = next((d for d in self.library(upload["owner"]) if d.sha256 == sha), None)
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
        user = self._tokens.get(request.headers.get("authorization", "").removeprefix("Bearer "))
        if user is None:
            return httpx.Response(401)
        method, path = request.method, request.url.path
        body = httpx.Response(200, content=request.content).json() if request.content else None
        if (method, path) == ("POST", "/documents/duplicate-check"):
            found = next((d for d in self.library(user) if d.sha256 == body["sha256"]), None)
            return httpx.Response(200, json={"document_id": found.document_id if found else None})
        if (method, path) == ("POST", "/uploads"):
            self.uploads_started += 1
            upload_id, doc = next(self._ids), FakeDocument(next(self._ids), user, None)
            self.documents[doc.document_id] = doc
            self.uploads[upload_id] = {"owner": user, "document_id": doc.document_id, "outcome": None}
            fields = {"key": upload_id, "Content-Type": "application/pdf", "policy": "p"}
            return httpx.Response(201, json={"document_id": doc.document_id, "upload_id": upload_id, "url": BUCKET, "fields": fields})
        parts = path.strip("/").split("/")
        if parts[0] == "uploads" and method == "GET":
            upload = self.uploads.get(parts[1])
            if upload is None or upload["owner"] != user:
                return httpx.Response(404)
            ready = upload["outcome"] is not None
            return httpx.Response(200, json={"upload_id": parts[1], "outcome": upload["outcome"], "document_id": upload["document_id"] if ready else None, "archived": False})
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
```

(Move the `import base64` to the top of the file with the other imports; it is shown inline only to keep the snippet readable. Wrap lines over 120 characters when `ruff format` asks.)

- [ ] **Step 3: Write the failing tests for this task** (`backend/tests/unit/evals/test_learners.py`)

```python
"""Loading the eval learners' libraries (issue #222): which documents each learner holds, signing in, the API."""

from pathlib import Path

import pytest
from fakes.evals_stack import FakeStack

from evals.corpus import load_manifest
from evals.learners import LEARNERS, LoadError, Tutor, load_learners


def test_the_eval_learners_hold_different_seed_documents() -> None:
    learners = load_learners(LEARNERS, load_manifest())
    assert [learner.username for learner in learners] == ["learner@example.com", "learner2@example.com"]
    first, second = (set(learner.documents) for learner in learners)
    assert first and second - first, "learner 2 needs documents learner 1 must never see"


def test_a_document_missing_from_the_manifest_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "learners.yaml"
    path.write_text("learners:\n  - {username: a, password: b, documents: [react-2022, nope]}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="nope"):
        load_learners(path, load_manifest())


def test_a_learner_signs_in_through_the_login_form_with_pkce() -> None:
    stack = FakeStack()
    tutor = Tutor(stack.client(), "learner@example.com", "learner")
    tutor.sign_in()  # the fake checks the PKCE verifier against the challenge
    assert tutor.call("POST", "/documents/duplicate-check", {"sha256": "0" * 64}) == {"document_id": None}


def test_a_wrong_password_is_reported() -> None:
    with pytest.raises(LoadError, match="learner@example.com"):
        Tutor(FakeStack().client(), "learner@example.com", "wrong").sign_in()


def test_an_expired_token_signs_in_again() -> None:
    stack = FakeStack()
    tutor = Tutor(stack.client(), "learner@example.com", "learner")
    tutor.call("POST", "/documents/duplicate-check", {"sha256": "0" * 64})
    stack.expire_tokens()
    assert tutor.call("POST", "/documents/duplicate-check", {"sha256": "0" * 64}) == {"document_id": None}
    assert stack.sign_ins == 2


def test_an_unexpected_status_is_a_load_error() -> None:
    tutor = Tutor(FakeStack().client(), "learner@example.com", "learner")
    with pytest.raises(LoadError, match="404"):
        tutor.call("GET", "/documents/00000000-0000-0000-0000-000000000999")


def test_an_upload_posts_the_file_to_the_presigned_url() -> None:
    stack = FakeStack()
    tutor = Tutor(stack.client(), "learner@example.com", "learner")
    upload_id = tutor.upload("2210.03629v3.pdf", b"%PDF-1.7 react")
    status = tutor.call("GET", f"/uploads/{upload_id}")
    assert status["outcome"] == "stored"
    assert stack.documents[status["document_id"]].state == "awaiting_subjects"
```

Run: `cd backend && uv run pytest tests/unit/evals/test_learners.py -q` → FAIL (`No module named 'evals.learners'`).

- [ ] **Step 4: Implement the first half of `backend/evals/learners.py`**

```python
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
            raise LoadError(f"{self.username}: sign-in refused (wrong password in learners.yaml, or a required action?)")
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
```

Note: httpx puts `data` fields before `files` in a multipart body, which is what S3's presigned POST requires (the fake asserts it).

- [ ] **Step 5: Run the tests and checks**

Run: `cd backend && uv run pytest tests/unit/evals -q && uv run ruff check . && uv run ruff format --check .` → PASS.

- [ ] **Step 6: Commit**

`git add backend/evals/learners.py backend/evals/seed_corpus/learners.yaml backend/tests && git commit` — subject: `Sign eval learners in and call the API as them`.

---

### Task 3: Load a library and the command

**Files:**
- Modify: `backend/evals/learners.py` (add `load_library`, `load_all`, `main`)
- Modify: `backend/tests/unit/evals/test_learners.py`

**Interfaces:**
- Consumes: `Tutor`, `Learner`, `LoadError`, `load_learners`, `LEARNERS`, URL constants (Task 2); `SeedDocument`, `load_manifest`, `download`, `DOWNLOADS`, `CorpusError` (Task 1); `FakeStack` (Task 2).
- Produces:
  - `load_library(tutor: Tutor, seeds: Sequence[SeedDocument], paths: Mapping[str, Path], *, timeout: float, interval: float, log: Callable[[str], None] = print) -> list[str]` — problems (empty when every document is ready).
  - `load_all(learners: Sequence[Learner], seeds: Mapping[str, SeedDocument], paths: Mapping[str, Path], *, connect: Callable[[], httpx.Client], api: str, issuer: str, app: str, timeout: float, interval: float, log: Callable[[str], None] = print) -> list[str]` — one fresh client per learner; problems prefixed with the username.
  - `main(argv: Sequence[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing tests** (append to `test_learners.py`)

```python
from evals.corpus import SeedDocument, sha256_of
from evals.learners import Learner, load_all, load_library

REACT, COT = b"%PDF-1.7 react", b"%PDF-1.7 cot"


def _seeds(tmp_path: Path) -> tuple[list[SeedDocument], dict[str, Path]]:
    seeds = [
        SeedDocument("react-2022", "u", sha256_of(REACT), ("LLM agents",), "2210.03629v3.pdf"),
        SeedDocument("cot-2022", "u", sha256_of(COT), ("Prompting", "Reasoning"), "2201.11903v6.pdf"),
    ]
    paths = {"react-2022": tmp_path / "react.pdf", "cot-2022": tmp_path / "cot.pdf"}
    paths["react-2022"].write_bytes(REACT)
    paths["cot-2022"].write_bytes(COT)
    return seeds, paths


def _load(stack: FakeStack, tmp_path: Path, timeout: float = 5) -> list[str]:
    seeds, paths = _seeds(tmp_path)
    tutor = Tutor(stack.client(), "learner@example.com", "learner")
    return load_library(tutor, seeds, paths, timeout=timeout, interval=0, log=lambda line: None)


def test_a_new_library_is_uploaded_and_gets_its_labeled_subjects(tmp_path: Path) -> None:
    stack = FakeStack()
    assert _load(stack, tmp_path) == []
    library = stack.library("learner@example.com")
    assert sorted((d.state, tuple(d.subjects)) for d in library) == [
        ("ready", ("LLM agents",)),
        ("ready", ("Prompting", "Reasoning")),
    ]


def test_a_second_run_uploads_nothing(tmp_path: Path) -> None:
    stack = FakeStack()
    _load(stack, tmp_path)
    before = (stack.uploads_started, {d.document_id: d.subjects for d in stack.documents.values()})
    assert _load(stack, tmp_path) == []
    assert (stack.uploads_started, {d.document_id: d.subjects for d in stack.documents.values()}) == before


def test_a_document_that_fails_is_reported(tmp_path: Path) -> None:
    stack = FakeStack()

    def fail(doc: FakeDocument) -> None:
        doc.state, doc.failure_reason = "failed", "The PDF has no text"

    stack.process = fail
    problems = _load(stack, tmp_path)
    assert len(problems) == 2 and all("The PDF has no text" in p for p in problems)
    assert stack.retries == 0  # a document that failed in this run is not retried


def test_a_document_still_processing_times_out(tmp_path: Path) -> None:
    stack = FakeStack()
    stack.process = lambda doc: None  # the worker never finishes
    problems = _load(stack, tmp_path, timeout=0.05)
    assert len(problems) == 2 and all("timed out" in p and "processing" in p for p in problems)


def test_a_document_that_failed_in_an_earlier_run_is_retried(tmp_path: Path) -> None:
    stack = FakeStack()
    stack.add("learner@example.com", REACT, state="failed", failure_reason="Bedrock throttled")
    assert _load(stack, tmp_path) == []
    assert stack.retries == 1
    assert all(d.state == "ready" for d in stack.library("learner@example.com"))


def test_an_archived_document_is_restored(tmp_path: Path) -> None:
    stack = FakeStack()
    stack.add("learner@example.com", REACT, state="awaiting_subjects", archived=True)
    assert _load(stack, tmp_path) == []
    assert all(not d.archived and d.state == "ready" for d in stack.library("learner@example.com"))


def test_a_ready_document_keeps_its_subjects(tmp_path: Path) -> None:
    stack = FakeStack()
    stack.add("learner@example.com", REACT, state="ready", subjects=["Agents I chose"])
    _load(stack, tmp_path)
    react = next(d for d in stack.library("learner@example.com") if d.sha256 == sha256_of(REACT))
    assert react.subjects == ["Agents I chose"]


def test_each_learner_signs_in_as_themselves(tmp_path: Path) -> None:
    stack = FakeStack()
    seeds, paths = _seeds(tmp_path)
    learners = [
        Learner("learner@example.com", "learner", ("react-2022",)),
        Learner("learner2@example.com", "learner2", ("cot-2022",)),
    ]
    problems = load_all(
        learners,
        {s.id: s for s in seeds},
        paths,
        connect=stack.client,
        api=API, issuer=ISSUER, app=APP,
        timeout=5,
        interval=0,
        log=lambda line: None,
    )
    assert problems == []
    assert [d.sha256 for d in stack.library("learner@example.com")] == [sha256_of(REACT)]
    assert [d.sha256 for d in stack.library("learner2@example.com")] == [sha256_of(COT)]


def test_a_learner_who_cannot_sign_in_is_a_problem_for_that_learner_only(tmp_path: Path) -> None:
    stack = FakeStack()
    seeds, paths = _seeds(tmp_path)
    learners = [
        Learner("learner@example.com", "wrong", ("react-2022",)),
        Learner("learner2@example.com", "learner2", ("cot-2022",)),
    ]
    problems = load_all(learners, {s.id: s for s in seeds}, paths, connect=stack.client, api=API, issuer=ISSUER,
                        app=APP, timeout=5, interval=0, log=lambda line: None)
    assert len(problems) == 1 and problems[0].startswith("learner@example.com")
    assert [d.state for d in stack.library("learner2@example.com")] == ["ready"]
```

(Import `FakeDocument` from the fake and `API, APP, ISSUER` from `evals.learners`.)

Run: `cd backend && uv run pytest tests/unit/evals/test_learners.py -q` → the new tests FAIL (`cannot import name 'load_library'`).

- [ ] **Step 2: Implement** (append to `backend/evals/learners.py`; add imports `argparse`, `sys`, `time`, `Callable`, `Mapping`, `Sequence`, `field`, and from `evals.corpus` `DOWNLOADS, CorpusError, SeedDocument, download, load_manifest`)

```python
@dataclass
class _Pending:
    """A seed document on its way into the learner's library."""

    seed: SeedDocument
    upload_id: str | None = None
    document_id: str | None = None
    found: bool = False  # already in the library before this run
    retried: bool = False
    state: str = "uploading"


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
        except LoadError as e:
            problems.append(f"{seed.id}: {e}")
    while pending:
        for p in list(pending):
            try:
                done = _advance(tutor, p)
            except LoadError as e:
                problems.append(f"{p.seed.id}: {e}")
                pending.remove(p)
                continue
            if done:
                log(f"{tutor.username} {p.seed.id}: ready")
                pending.remove(p)
        if pending and time.monotonic() >= deadline:
            problems += [f"{p.seed.id}: timed out after {timeout:g}s while {p.state}" for p in pending]
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
    try:
        paths = download(sorted({seeds[d] for learner in learners for d in learner.documents}, key=lambda s: s.id), args.downloads)
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
```

- [ ] **Step 3: Run the tests and checks**

Run: `cd backend && uv run pytest tests/unit/evals -q && uv run ruff check . && uv run ruff format --check .` → PASS.

- [ ] **Step 4: Commit** — subject: `Load the eval learners' libraries from the seed corpus`.

---

### Task 4: Docs, Makefile target, and a real run on the Compose stack

**Files:**
- Modify: `backend/evals/README.md` (table rows for `corpus.py`, `learners.py`, `seed_corpus/learners.yaml`; a "Eval learners" section: command, prerequisites, what a second run does)
- Modify: `backend/evals/seed_corpus/README.md` (the download step exists: `python -m evals.corpus`; synthetic learners come from `learners.yaml`, replacing the `../generators/` sentence)
- Modify: `Makefile` (`evals-learners:` target next to `evals-smoke`, added to `.PHONY`)

- [ ] **Step 1: Write the docs**

`backend/evals/README.md` section to add after the table:

```markdown
## Eval learners

Every eval asks as one of two synthetic learners whose libraries are built from the seed corpus. `seed_corpus/learners.yaml` says which documents each holds; learner 2 holds documents learner 1 must never see. Load both libraries with

    cd backend && uv run --extra eval python -m evals.learners     # or: make evals-learners

It downloads the seed PDFs into `data/seed_corpus/` (checked against the manifest's SHA-256), signs in as `learner@example.com` and `learner2@example.com`, uploads each document through the real upload path, chooses its labeled subjects, and waits until it is ready. It exits 1 when a document fails or doesn't get ready within `--timeout` seconds per learner (default 900). A second run uploads nothing: the learner's own duplicate check finds each document; a document an earlier run left failed is retried once, an archived one is restored.

Prerequisites:
- The Compose stack with the app profile (`docker compose --profile app up -d`), or the dependencies plus host processes (`make api`, `make worker`; README "Run the app").
- Your AWS profile (`AWS_PROFILE` in `.env`, logged in): the worker describes and embeds each PDF with Bedrock in us-east-1.
- Internet access to arxiv.org for the first download.
```

Makefile:

```make
evals-learners:  ## load the eval learners' libraries from the seed corpus (needs the app stack and your AWS profile)
	$(BACKEND) uv run --extra eval python -m evals.learners
```

- [ ] **Step 2: Real run.** With the app stack up and AWS credentials valid: `cd backend && uv run --extra eval python -m evals.learners`. Expected: each document "uploaded" then "ready", exit 0. Record counts first and after:

```bash
docker compose exec -T postgres psql -U smart_tutor -d smart_tutor -c "select count(*) from documents; select count(*) from chunks;"
```

(check the real table names with `\dt` first). Run the command a second time: every document "already in the library", exit 0, the same counts.

- [ ] **Step 3: Full checks and commit**

`cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest` → PASS. Commit — subject: `Document the eval learners command`.
