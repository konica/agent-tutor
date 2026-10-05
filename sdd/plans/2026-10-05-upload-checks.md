# Checks Before and After Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ticket #62. The browser refuses non-PDFs and files over the size limit with a clear reason and no upload request. The worker fails PDFs over the page limit, unparseable PDFs, and scanned PDFs, and the Library shows the reason. The limits come from SSM settings.

**Architecture:** A `FileLimits` value object (knowledge domain) is loaded once per process from SSM through a new shared `ParameterStore` port (SSM adapter in `shared/adapters/aws`). The API presigns with `limits.max_bytes` and serves the limits at `GET /uploads/limits`. The worker passes `limits.max_pages` to the `PdfExtractor`, which raises `TooManyPagesError` before reading any text. The web loads the limits and checks each picked file before calling the API.

**Tech Stack:** Python 3 / FastAPI / boto3 (SSM) / pypdf; React + TypeScript + Vitest; AWS CDK (Python); LocalStack.

**Spec:** GitHub issue #62 (`gh issue view 62`); PRD `sdd/prd.md` §8 US-2 (second criterion), §9.5 step 6, §9.12 settings row, §11; mockup round v0.4 states `library-rejected`, `library-failed`.

## Global Constraints

- SSM parameter names: `/smart-tutor/max-upload-mb` (value `50`, meaning MiB: 50 × 1,048,576 = 52,428,800 bytes) and `/smart-tutor/max-pages` (value `500`). No limit numbers in production code paths; tests may use literals.
- Failure reasons (exact text): `This file isn't a readable PDF` (exists), `No text layer (scanned PDFs are not supported yet)` (exists), new: `This PDF has {pages} pages; the limit is {max_pages}`.
- Browser rejection copy (exact): `Not uploaded. Only PDF files can be uploaded.`, `Not uploaded. This file is empty.`, `Not uploaded. This file is {size} MB; the limit is {limit} MB.` where `size` is MiB rounded **up** to one decimal place (`Math.ceil(x * 10) / 10`) with a trailing `.0` dropped (72 → `72`, 50.0000009 → `50.1`), so a file just over the limit never reads as equal to it.
- A file counts as a PDF when `file.type === "application/pdf"`, or `file.type === ""` and the name ends in `.pdf` (case-insensitive).
- A missing or non-positive SSM parameter fails process startup with an error naming the parameter.
- Import rules: `domain`/`application`/`ports` import no vendor SDKs; `shared` imports no module; run `PYTHONUTF8=1 uv run lint-imports`.
- Backend checks: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`. Web: `cd web && npm run build && npx vitest run`. Infra: `cd infra && uv run pytest`.
- Commit subjects in the imperative mood; body says why; end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A file with an empty MIME type but a `.pdf` name (Windows drag/drop) must be accepted; a `.PDF` upper-case name too — test in Task 5.
2. A file just over the limit (52,428,801 bytes) must be rejected and must not display "50 MB; the limit is 50 MB" — test in Task 5.
3. Picking several files where some are rejected must still upload the good ones and list every rejection — test in Task 5.
4. A PDF with exactly `max_pages` pages is accepted; `max_pages + 1` fails — test in Task 3.
5. SSM parameter missing or holding `"abc"`/`"0"` → startup error naming the parameter, never a silent default — test in Task 1.

---

### Task 1: FileLimits loaded from SSM

**Files:**
- Create: `backend/src/smart_tutor/knowledge/domain/limits.py`
- Create: `backend/src/smart_tutor/shared/ports/parameter_store.py`
- Create: `backend/src/smart_tutor/shared/adapters/aws/ssm_parameters.py`
- Create: `backend/src/smart_tutor/knowledge/application/limits.py`
- Modify: `backend/src/smart_tutor/knowledge/application/__init__.py` (export `FileLimits`, `load_file_limits`)
- Modify: `backend/src/smart_tutor/shared/adapters/aws/clients.py` (add `ssm_client`)
- Modify: `backend/src/smart_tutor/shared/config.py` (two param-name settings)
- Modify: `backend/pyproject.toml` (`boto3-stubs[s3,sqs,ssm]`), then `uv lock`
- Create: `backend/tests/fakes/parameters.py` (`FakeParameterStore`), export from `backend/tests/fakes/__init__.py`; also export `TEST_LIMITS`
- Test: `backend/tests/unit/knowledge/test_limits.py`, `backend/tests/unit/shared/test_ssm_parameters.py`, extend `backend/tests/unit/shared/test_aws_clients.py`

**Interfaces:**
- Produces:
  - `smart_tutor.knowledge.domain.limits.MIB = 1024 * 1024`
  - `@dataclass(frozen=True) class FileLimits: max_bytes: int; max_pages: int` — `__post_init__` raises `ValueError` if either ≤ 0.
  - `smart_tutor.shared.ports.parameter_store`: `class ParameterNotFoundError(Exception)`; `class ParameterStore(ABC): def get(self, name: str) -> str` (raises `ParameterNotFoundError`).
  - `smart_tutor.shared.adapters.aws.ssm_parameters.SsmParameterStore(client: "SSMClient")`.
  - `smart_tutor.shared.adapters.aws.clients.ssm_client(settings: Settings) -> "SSMClient"` (dummy keys when `settings.localstack`).
  - `Settings.max_upload_mb_param: str = "/smart-tutor/max-upload-mb"`, `Settings.max_pages_param: str = "/smart-tutor/max-pages"`.
  - `smart_tutor.knowledge.application.load_file_limits(store: ParameterStore, max_upload_mb_param: str, max_pages_param: str) -> FileLimits` — raises `ValueError(f"SSM parameter {name} must be a positive whole number, got {value!r}")` for bad values and lets `ParameterNotFoundError(name)` propagate.
  - `fakes.TEST_LIMITS = FileLimits(max_bytes=50 * MIB, max_pages=500)`; `fakes.FakeParameterStore(values: dict[str, str])`.

- [ ] **Step 1: Write failing tests**

`backend/tests/unit/knowledge/test_limits.py`:
```python
import pytest

from fakes import FakeParameterStore
from smart_tutor.knowledge.application import FileLimits, load_file_limits
from smart_tutor.knowledge.domain.limits import MIB
from smart_tutor.shared.ports.parameter_store import ParameterNotFoundError

MB, PAGES = "/smart-tutor/max-upload-mb", "/smart-tutor/max-pages"


def test_reads_megabytes_and_pages_from_parameters() -> None:
    store = FakeParameterStore({MB: "50", PAGES: "500"})

    assert load_file_limits(store, MB, PAGES) == FileLimits(max_bytes=50 * MIB, max_pages=500)


@pytest.mark.parametrize("bad", ["abc", "0", "-3", "1.5", ""])
def test_a_bad_value_names_the_parameter(bad: str) -> None:
    store = FakeParameterStore({MB: "50", PAGES: bad})

    with pytest.raises(ValueError, match="/smart-tutor/max-pages"):
        load_file_limits(store, MB, PAGES)


def test_a_missing_parameter_is_not_defaulted() -> None:
    with pytest.raises(ParameterNotFoundError, match="/smart-tutor/max-upload-mb"):
        load_file_limits(FakeParameterStore({PAGES: "500"}), MB, PAGES)


@pytest.mark.parametrize(("size", "pages"), [(0, 1), (1, 0)])
def test_limits_must_be_positive(size: int, pages: int) -> None:
    with pytest.raises(ValueError):
        FileLimits(max_bytes=size, max_pages=pages)
```

`backend/tests/unit/shared/test_ssm_parameters.py` (botocore `Stubber`, no network):
```python
import boto3
import pytest
from botocore.stub import Stubber

from smart_tutor.shared.adapters.aws.ssm_parameters import SsmParameterStore
from smart_tutor.shared.ports.parameter_store import ParameterNotFoundError


def _client():  # type: ignore[no-untyped-def]
    return boto3.client("ssm", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")


def test_returns_the_parameter_value() -> None:
    client = _client()
    with Stubber(client) as stub:
        stub.add_response("get_parameter", {"Parameter": {"Name": "/a", "Value": "50"}}, {"Name": "/a"})
        assert SsmParameterStore(client).get("/a") == "50"


def test_a_missing_parameter_raises_with_its_name() -> None:
    client = _client()
    with Stubber(client) as stub:
        stub.add_client_error("get_parameter", service_error_code="ParameterNotFound")
        with pytest.raises(ParameterNotFoundError, match="/a"):
            SsmParameterStore(client).get("/a")
```

In `test_aws_clients.py`, add `ssm_client` to both existing tests (`assert _access_key(ssm_client(settings)) == "test"` / `"real-ish"`).

- [ ] **Step 2: Run to verify they fail** — `cd backend && uv run pytest tests/unit/knowledge/test_limits.py tests/unit/shared -q` → ImportError.

- [ ] **Step 3: Implement**

`knowledge/domain/limits.py`:
```python
"""Per-file limits (PRD D24, §11): checked in the browser and by the presigned POST (size) and by the worker (pages)."""

from dataclasses import dataclass

MIB = 1024 * 1024


@dataclass(frozen=True)
class FileLimits:
    max_bytes: int
    max_pages: int

    def __post_init__(self) -> None:
        if self.max_bytes <= 0 or self.max_pages <= 0:
            raise ValueError("File limits must be positive")
```

`shared/ports/parameter_store.py`:
```python
"""Settings that operators change without a release (SSM Parameter Store, `/smart-tutor/*`; PRD §9.12)."""

from abc import ABC, abstractmethod


class ParameterNotFoundError(Exception):
    """The named parameter doesn't exist."""


class ParameterStore(ABC):
    @abstractmethod
    def get(self, name: str) -> str:
        """The parameter's value; raises ParameterNotFoundError."""
```

`shared/adapters/aws/ssm_parameters.py`:
```python
"""ParameterStore on SSM Parameter Store."""

from typing import TYPE_CHECKING

from smart_tutor.shared.ports.parameter_store import ParameterNotFoundError, ParameterStore

if TYPE_CHECKING:
    from mypy_boto3_ssm import SSMClient


class SsmParameterStore(ParameterStore):
    def __init__(self, client: "SSMClient") -> None:
        self._client = client

    def get(self, name: str) -> str:
        try:
            return self._client.get_parameter(Name=name)["Parameter"]["Value"]
        except self._client.exceptions.ParameterNotFound:
            raise ParameterNotFoundError(name) from None
```

`clients.py` — add next to `sqs_client`:
```python
def ssm_client(settings: Settings) -> "SSMClient":
    return boto3.client(
        "ssm",
        region_name=settings.aws_region,
        aws_access_key_id=_dummy_key(settings),
        aws_secret_access_key=_dummy_key(settings),
    )
```
(import `SSMClient` from `mypy_boto3_ssm` under `TYPE_CHECKING`; update the module docstring to mention `AWS_ENDPOINT_URL_SSM`.)

`config.py` — next to `learning_record_idle_minutes_param`:
```python
    # File limits (PRD §11), read once at startup by the API (presigned POST, GET /uploads/limits) and the worker.
    max_upload_mb_param: str = "/smart-tutor/max-upload-mb"
    max_pages_param: str = "/smart-tutor/max-pages"
```

`knowledge/application/limits.py`:
```python
"""Load the per-file limits from settings (SSM), never from code (PRD §9.12)."""

from smart_tutor.knowledge.domain.limits import MIB, FileLimits
from smart_tutor.shared.ports.parameter_store import ParameterStore


def _positive(store: ParameterStore, name: str) -> int:
    value = store.get(name)
    if not value.isdigit() or int(value) <= 0:
        raise ValueError(f"SSM parameter {name} must be a positive whole number, got {value!r}")
    return int(value)


def load_file_limits(store: ParameterStore, max_upload_mb_param: str, max_pages_param: str) -> FileLimits:
    return FileLimits(
        max_bytes=_positive(store, max_upload_mb_param) * MIB, max_pages=_positive(store, max_pages_param)
    )
```

`tests/fakes/parameters.py`:
```python
from smart_tutor.knowledge.domain.limits import MIB, FileLimits
from smart_tutor.shared.ports.parameter_store import ParameterNotFoundError, ParameterStore

TEST_LIMITS = FileLimits(max_bytes=50 * MIB, max_pages=500)


class FakeParameterStore(ParameterStore):
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def get(self, name: str) -> str:
        if name not in self._values:
            raise ParameterNotFoundError(name)
        return self._values[name]
```

`pyproject.toml`: `"boto3-stubs[s3,sqs,ssm]>=1.40"`, then `uv lock`.

- [ ] **Step 4: Run** — the new tests, then the full backend checks (Global Constraints). Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "Load per-file limits from SSM settings"` (body: limits must come from settings, PRD §9.12; startup fails loudly instead of defaulting).

---

### Task 2: API presigns with the limit and serves it

**Files:**
- Modify: `backend/src/smart_tutor/knowledge/application/upload_service.py` (drop `MAX_UPLOAD_BYTES`; take `limits: FileLimits`; expose `limits` property)
- Modify: `backend/src/smart_tutor/apps/api/services.py` (load limits via `SsmParameterStore(ssm_client(settings))`)
- Modify: `backend/src/smart_tutor/apps/api/routes/knowledge.py` (add `GET /uploads/limits`)
- Modify every `UploadService(...)` call site in tests to pass `TEST_LIMITS` (see grep: `tests/isolation/test_documents.py`, `tests/unit/apps/api/test_knowledge_routes.py`, `tests/unit/apps/worker/test_worker.py`, `tests/unit/knowledge/test_document_service.py`, `test_ingestion_service.py`, `test_processing.py`, `test_upload_service.py`)
- Regenerate: `web/src/api/openapi.json` and `web/src/api/generated/` via `make api-client` (or the Makefile line run directly)
- Test: `backend/tests/unit/knowledge/test_upload_service.py`, `backend/tests/unit/apps/api/test_knowledge_routes.py`, `backend/tests/unit/apps/api/test_auth.py` (it checks every route needs a token — confirm the new route is covered)

**Interfaces:**
- Consumes: `FileLimits`, `TEST_LIMITS`, `load_file_limits`, `SsmParameterStore`, `ssm_client`, `Settings.max_upload_mb_param/max_pages_param` (Task 1).
- Produces:
  - `UploadService(uow, objects, clock, limits: FileLimits, new_id=new_uuid)`; `UploadService.limits -> FileLimits`.
  - `GET /uploads/limits`, `operation_id="get_upload_limits"`, response `UploadLimitsResponse {max_bytes: int, max_pages: int}`; generated TS function `getUploadLimits` and type `UploadLimitsResponse`.

- [ ] **Step 1: Failing tests**

In `test_upload_service.py`, change the factory to pass a small limit and assert the presign uses it:
```python
def test_presigns_with_the_configured_size_limit() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    service = UploadService(library.unit_of_work, objects, FixedClock(), FileLimits(max_bytes=1234, max_pages=9))

    service.start_upload(UserId("ada"), "a.pdf")

    assert objects.presigned[-1].max_bytes == 1234
```
(Read `FakeObjectStore.presign_post` in `tests/fakes/knowledge.py` first and assert through whatever it records; if it records nothing, make it record `(key, content_type, max_bytes)` in a list.)

In `test_knowledge_routes.py`:
```python
def test_upload_limits_come_from_the_upload_service(client: TestClient) -> None:
    response = client.get("/uploads/limits", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"max_bytes": 50 * 1024 * 1024, "max_pages": 500}


def test_upload_limits_need_a_token(client: TestClient) -> None:
    assert client.get("/uploads/limits").status_code == 401
```

- [ ] **Step 2: Run** — expect failures (TypeError on constructor / 404 or 405 on the route).

- [ ] **Step 3: Implement**

`upload_service.py`: remove `MAX_UPLOAD_BYTES`; constructor:
```python
    def __init__(
        self,
        uow: Callable[[], LibraryUnitOfWork],
        objects: ObjectStore,
        clock: Clock,
        limits: FileLimits,
        new_id: Callable[[], str] = new_uuid,
    ) -> None:
        self._uow, self._objects, self._clock, self._limits, self._new_id = uow, objects, clock, limits, new_id

    @property
    def limits(self) -> FileLimits:
        return self._limits
```
and `max_bytes=self._limits.max_bytes` in `presign_post`. Grep for `MAX_UPLOAD_BYTES` and remove other references (web has its own; Task 5 handles it).

`services.py`:
```python
    limits = load_file_limits(
        SsmParameterStore(ssm_client(settings)), settings.max_upload_mb_param, settings.max_pages_param
    )
    ...
        uploads=UploadService(library, objects, SystemClock(), limits),
```

`routes/knowledge.py` — declare **before** any `/uploads/{...}` route if one exists:
```python
class UploadLimitsResponse(BaseModel):
    max_bytes: int
    max_pages: int


@router.get("/uploads/limits", operation_id="get_upload_limits")
def get_upload_limits(uploads: Uploads) -> UploadLimitsResponse:
    """The per-file limits, so the browser can refuse a file before uploading it (PRD §8 US-2)."""
    return UploadLimitsResponse(max_bytes=uploads.limits.max_bytes, max_pages=uploads.limits.max_pages)
```

Pass `TEST_LIMITS` at every `UploadService(` test call site (4th positional argument; in `test_upload_service.py` the `new_id` lambda becomes 5th).

Regenerate the client: run the `api-client` Makefile line (read it with `grep -n -A3 "^api-client" Makefile`; on Windows Git Bash run the command directly).

- [ ] **Step 4: Run** — full backend checks + `cd web && npm run build`. The OpenAPI snapshot test must pass.
- [ ] **Step 5: Commit** — `"Presign uploads with the configured size limit and serve the limits"`.

---

### Task 3: Worker fails PDFs over the page limit; scanned and corrupt fixtures

**Files:**
- Modify: `backend/src/smart_tutor/knowledge/ports/pdf_extractor.py` (add `TooManyPagesError`, `max_pages` parameter)
- Modify: `backend/src/smart_tutor/knowledge/adapters/pypdf_extractor.py`
- Modify: `backend/src/smart_tutor/knowledge/domain/content.py` (add `too_many_pages(pages, limit) -> str`)
- Modify: `backend/src/smart_tutor/knowledge/application/ingestion_service.py` (take `limits: FileLimits`; handle `TooManyPagesError`; update module docstring)
- Modify: `backend/src/smart_tutor/knowledge/application/__init__.py` (export `TooManyPagesError` if `UnreadablePdfError` is exported there)
- Modify: `backend/src/smart_tutor/apps/worker/main.py` (load limits from SSM, pass to `IngestionService`)
- Modify: `backend/tests/fakes/processing.py` (`FakePdfExtractor` honours `max_pages`), `backend/tests/fakes/pdfs.py` (add `make_scanned_pdf`)
- Modify every `IngestionService(...)` test call site to pass `TEST_LIMITS` (`tests/isolation/test_documents.py`, `tests/unit/apps/api/test_knowledge_routes.py`, `tests/unit/apps/worker/test_worker.py`, `test_ingestion_service.py`, `test_processing.py`)
- Test: `backend/tests/unit/knowledge/test_pypdf_extractor.py`, `backend/tests/unit/knowledge/test_processing.py`, `backend/tests/unit/knowledge/test_domain.py`

**Interfaces:**
- Consumes: `FileLimits`, `TEST_LIMITS`, `load_file_limits`, `SsmParameterStore`, `ssm_client` (Task 1).
- Produces:
  - `class TooManyPagesError(Exception): def __init__(self, pages: int)`; attribute `pages: int`.
  - `PdfExtractor.extract_pages(self, data: bytes, max_pages: int) -> list[str]` — raises `TooManyPagesError(page_count)` when `page_count > max_pages`, **before** extracting text; raises `UnreadablePdfError` as before.
  - `content.too_many_pages(pages: int, limit: int) -> str` → `f"This PDF has {pages} pages; the limit is {limit}"`.
  - `IngestionService(uow, objects, tools, limits: FileLimits, new_id=new_uuid)`.
  - `fakes.pdfs.make_scanned_pdf(pages: int) -> bytes` — image-only pages, no text operators.

- [ ] **Step 1: Failing tests**

`fakes/pdfs.py` — add a generator for an image-only ("scanned") PDF. Each page draws one 8×8 DeviceGray image XObject full-page; no fonts, no `BT/ET`:
```python
def make_scanned_pdf(pages: int) -> bytes:
    """A scan: each page is one full-page grey image and has no text layer (PRD M0 note: tested in US-2)."""
    image = bytes(range(0, 256, 4))  # 8x8 8-bit greys
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    image_id = 3 + 2 * pages
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(pages))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode())
    draw = b"q 612 0 0 792 0 0 cm /Im1 Do Q"
    for i in range(pages):
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /XObject << /Im1 {image_id} 0 R >> >> /Contents {4 + 2 * i} 0 R >>"
            ).encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(draw) + draw + b"\nendstream")
    objects.append(
        b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 /ColorSpace /DeviceGray "
        b"/BitsPerComponent 8 /Length %d >>\nstream\n" % len(image) + image + b"\nendstream"
    )
    return _assemble(objects)
```
Refactor `make_pdf` so both use one `_assemble(objects: list[bytes]) -> bytes` (the existing header/xref/trailer code, unchanged in behaviour).

`test_pypdf_extractor.py` — update all existing calls to `extract_pages(data, 500)` and add:
```python
def test_a_scanned_pdf_has_pages_but_no_text() -> None:
    pages = PypdfExtractor().extract_pages(make_scanned_pdf(3), 500)

    assert len(pages) == 3
    assert not has_text_layer(pages)


def test_more_pages_than_the_limit_raise_before_reading_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def never(self: PageObject, *args: object, **kwargs: object) -> str:
        raise AssertionError("text was extracted")

    monkeypatch.setattr(PageObject, "extract_text", never)

    with pytest.raises(TooManyPagesError) as raised:
        PypdfExtractor().extract_pages(make_pdf(["p"] * 4), 3)
    assert raised.value.pages == 4


def test_exactly_the_limit_is_accepted() -> None:
    assert len(PypdfExtractor().extract_pages(make_pdf(["p"] * 3), 3)) == 3
```

`test_domain.py`:
```python
def test_too_many_pages_reason_names_both_counts() -> None:
    assert too_many_pages(501, 500) == "This PDF has 501 pages; the limit is 500"
```

`test_processing.py` — read the file's `World`-style helper first (`__init__(self, tools=None)`, `upload(data)`), then pass `TEST_LIMITS` into `IngestionService` and add end-to-end cases through the **real** `PypdfExtractor` (it lives in `knowledge.adapters`, allowed in unit tests):
```python
def test_a_pdf_over_the_page_limit_fails_with_its_reason_and_stores_no_chunks() -> None:
    world = World(fake_tools(extractor=PypdfExtractor()), limits=FileLimits(max_bytes=50 * MIB, max_pages=500))
    content, document = world.upload(make_pdf(["page text " * 10] * 501))

    assert (content.state, content.failure_reason) == (ContentState.FAILED, "This PDF has 501 pages; the limit is 500")
    assert (document.state, document.failure_reason) == ("failed", "This PDF has 501 pages; the limit is 500")
    assert world.chunks_for(content) == []


def test_a_scanned_pdf_fails_with_no_text_layer_and_stores_no_chunks() -> None:
    world = World(fake_tools(extractor=PypdfExtractor()))
    content, document = world.upload(make_scanned_pdf(2))

    assert (content.state, content.failure_reason) == (ContentState.FAILED, NO_TEXT_LAYER)
    assert (document.state, document.failure_reason) == ("failed", NO_TEXT_LAYER)
    assert world.chunks_for(content) == []


def test_a_corrupt_pdf_fails_as_unreadable_and_stores_no_chunks() -> None:
    world = World(fake_tools(extractor=PypdfExtractor()))
    content, document = world.upload(make_pdf(["Hello"])[:40])

    assert (content.state, content.failure_reason) == (ContentState.FAILED, UNREADABLE_PDF)
    assert (document.state, document.failure_reason) == ("failed", UNREADABLE_PDF)
    assert world.chunks_for(content) == []
```
Adapt names (`World`, `upload`, how chunks and the document are read) to the helper that already exists in `test_processing.py`; add a `limits` keyword (default `TEST_LIMITS`) and a `chunks_for` helper only if missing. Also assert no `pages.json` was put, mirroring the existing no-chunk test.

Also add to `FakePdfExtractor`:
```python
    def extract_pages(self, data: bytes, max_pages: int) -> list[str]:
        if not data.startswith(b"%PDF"):
            raise UnreadablePdfError("not a PDF")
        pages = data.decode("utf-8").partition(" ")[2].split("\f")
        if len(pages) > max_pages:
            raise TooManyPagesError(len(pages))
        return pages
```
and a fake-extractor test in `test_processing.py`: a 3-page fake PDF with `max_pages=2` fails with `too_many_pages(3, 2)`.

- [ ] **Step 2: Run** — `uv run pytest tests/unit/knowledge -q` → failures.

- [ ] **Step 3: Implement**

`ports/pdf_extractor.py`:
```python
class TooManyPagesError(Exception):
    """The PDF has more pages than the limit; raised before any text is read."""

    def __init__(self, pages: int) -> None:
        super().__init__(f"{pages} pages")
        self.pages = pages


class PdfExtractor(ABC):
    @abstractmethod
    def extract_pages(self, data: bytes, max_pages: int) -> list[str]:
        """Raw text per page (index = page number - 1; blank pages are "").

        Raises TooManyPagesError over `max_pages` (before reading text) and UnreadablePdfError.
        """
```

`pypdf_extractor.py`:
```python
    def extract_pages(self, data: bytes, max_pages: int) -> list[str]:
        try:
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted:
                raise UnreadablePdfError("The PDF is encrypted.")
            count = len(reader.pages)
            if count > max_pages:
                raise TooManyPagesError(count)
            return [page.extract_text() or "" for page in reader.pages]
        except (UnreadablePdfError, TooManyPagesError):
            raise
        except Exception as error:
            ...unchanged
```

`content.py`:
```python
def too_many_pages(pages: int, limit: int) -> str:
    return f"This PDF has {pages} pages; the limit is {limit}"
```

`ingestion_service.py`: add `limits: FileLimits` as the 4th constructor parameter (before `new_id`), store it, and in `process_content`:
```python
        try:
            pages = self._tools.extractor.extract_pages(self._objects.read(content.s3_key), self._limits.max_pages)
        except TooManyPagesError as error:
            return self._fail(content_id, too_many_pages(error.pages, self._limits.max_pages))
        except UnreadablePdfError:
            return self._fail(content_id, UNREADABLE_PDF)
```
Docstring: "only a file over the page limit, one we can't read, or one with no text layer ends failed."

`apps/worker/main.py`:
```python
    limits = load_file_limits(
        SsmParameterStore(ssm_client(settings)), settings.max_upload_mb_param, settings.max_pages_param
    )
    ingestion = IngestionService(
        library, S3ObjectStore(s3_client(settings), settings.documents_bucket), tools, limits
    )
```

Pass `TEST_LIMITS` at every `IngestionService(` test call site.

- [ ] **Step 4: Run** — full backend checks. Expected: PASS.
- [ ] **Step 5: Commit** — `"Fail PDFs over the page limit before reading their text"` (body: PRD §11 ≤ 500 pages; adds scanned-PDF fixture required by the PRD M0 note; corrupt and scanned covered end to end through pypdf).

---

### Task 4: Seed the limits locally and in CDK; reach SSM from Compose

**Files:**
- Modify: `local/localstack/init/ready.d/10-smart-tutor.sh`
- Modify: `compose.yaml` (api and worker: `AWS_ENDPOINT_URL_SSM: http://localstack:4566`)
- Modify: `infra/smart_tutor_infra/stacks/config.py`
- Test: `infra/tests/test_config_stack.py` (new)

**Interfaces:**
- Consumes: the parameter names and values from Global Constraints.
- Produces: SSM parameters `/smart-tutor/max-upload-mb` = `50`, `/smart-tutor/max-pages` = `500` locally and in CDK.

- [ ] **Step 1: Failing infra test** — `infra/tests/test_config_stack.py`:
```python
import aws_cdk as cdk
from aws_cdk.assertions import Template

from smart_tutor_infra.stacks.config import ConfigStack


def test_file_limits_are_ssm_parameters() -> None:
    template = Template.from_stack(ConfigStack(cdk.App(), "Config"))

    template.has_resource_properties("AWS::SSM::Parameter", {"Name": "/smart-tutor/max-upload-mb", "Value": "50"})
    template.has_resource_properties("AWS::SSM::Parameter", {"Name": "/smart-tutor/max-pages", "Value": "500"})
```
Run `cd infra && uv run pytest -q` → FAIL.

- [ ] **Step 2: Implement CDK** — in `ConfigStack.__init__`:
```python
        # Per-file limits (PRD §11), read at startup by the API and the worker; change them here, not in code.
        for name, value in (("max-upload-mb", "50"), ("max-pages", "500")):
            ssm.StringParameter(self, f"Param-{name}", parameter_name=f"/smart-tutor/{name}", string_value=value)
```
(`from aws_cdk import aws_ssm as ssm`; update the module docstring.) Run infra tests → PASS (the existing synth test must still see 7 stacks).

- [ ] **Step 3: LocalStack seed** — after the existing `put-parameter` line:
```bash
# Per-file limits (PRD §11): the API presigns and serves them, the worker checks pages.
awslocal ssm put-parameter --name /smart-tutor/max-upload-mb --type String --value 50 --overwrite
awslocal ssm put-parameter --name /smart-tutor/max-pages --type String --value 500 --overwrite
```

- [ ] **Step 4: Compose** — add `AWS_ENDPOINT_URL_SSM: http://localstack:4566` to the `api` service (comment: "SSM is read by the API itself, so it uses the in-network endpoint") and to the `worker` service. `.env.example` already sets `AWS_ENDPOINT_URL_SSM=http://localhost:10402` for host runs; leave it. Validate with `docker compose config -q` if Docker is available; otherwise check YAML with `python -c "import yaml,sys;yaml.safe_load(open('compose.yaml'))"` via `uv run`.

- [ ] **Step 5: Commit** — `"Seed the file limits in LocalStack and CDK"`.

---

### Task 5: Web refuses non-PDFs and oversized files with a clear reason

**Files:**
- Modify: `web/src/api/documents.ts` (remove `MAX_UPLOAD_BYTES`; add `loadUploadLimits`, `rejectionReason`; `uploadPdf` no longer checks size)
- Modify: `web/src/features/library/LibraryPage.tsx`, `LibraryPage.module.css`
- Test: `web/src/api/documents.test.ts`, `web/src/features/library/LibraryPage.test.tsx`

Read `DESIGN.md` (tokens, accessibility, document states) before writing UI. Look at `.design-shots/v0.4/library-rejected.light.png` (render with `cd web && npm run design:shots -- --states library-rejected --round v0.4 --theme both`). The mockup's floating "Uploads" tray is a later slice; this task shows the same per-file lines inline, above the table, using `--danger`/`--danger-soft` like the existing `.error` block.

**Interfaces:**
- Consumes: generated `getUploadLimits` and `UploadLimitsResponse` (Task 2).
- Produces:
  - `export type UploadLimits = UploadLimitsResponse` (`{ max_bytes: number; max_pages: number }`).
  - `export async function loadUploadLimits(apiClient: Client = client): Promise<UploadLimits>` — same 401/`SessionExpiredError` and error handling as `loadDocuments`.
  - `export function rejectionReason(file: File, limits: UploadLimits): string | null` — returns the exact copy from Global Constraints, or null.
  - `LibraryPage` props gain `loadLimits?: () => Promise<UploadLimits>` (default `() => loadUploadLimits()`).

- [ ] **Step 1: Failing unit tests** in `documents.test.ts`:
```ts
describe("rejectionReason", () => {
  const limits = { max_bytes: 52_428_800, max_pages: 500 };
  const file = (name: string, type: string, size = 10) => {
    const f = new File(["x"], name, { type });
    Object.defineProperty(f, "size", { value: size });
    return f;
  };

  it("accepts a PDF by type, or by a .pdf name when the browser gives no type", () => {
    expect(rejectionReason(file("a.pdf", "application/pdf"), limits)).toBeNull();
    expect(rejectionReason(file("B.PDF", ""), limits)).toBeNull();
  });

  it("refuses other types", () => {
    expect(rejectionReason(file("reading-list.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"), limits))
      .toBe("Not uploaded. Only PDF files can be uploaded.");
    expect(rejectionReason(file("notes.txt", ""), limits)).toBe("Not uploaded. Only PDF files can be uploaded.");
  });

  it("refuses an empty file", () => {
    expect(rejectionReason(file("a.pdf", "application/pdf", 0), limits)).toBe("Not uploaded. This file is empty.");
  });

  it("refuses a file over the limit and never shows it as equal to the limit", () => {
    expect(rejectionReason(file("big.pdf", "application/pdf", 72 * 1_048_576), limits))
      .toBe("Not uploaded. This file is 72 MB; the limit is 50 MB.");
    expect(rejectionReason(file("edge.pdf", "application/pdf", 52_428_801), limits))
      .toBe("Not uploaded. This file is 50.1 MB; the limit is 50 MB.");
    expect(rejectionReason(file("ok.pdf", "application/pdf", 52_428_800), limits)).toBeNull();
  });
});

describe("loadUploadLimits", () => {
  it("returns the limits", async () => {
    const { apiClient } = api(() => json({ max_bytes: 1, max_pages: 2 }));
    await expect(loadUploadLimits(apiClient)).resolves.toEqual({ max_bytes: 1, max_pages: 2 });
  });

  it("rejects with SessionExpiredError on 401", async () => {
    const { apiClient } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(loadUploadLimits(apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });
});
```
Remove any existing `uploadPdf` test that expects the size check inside `uploadPdf` (the check moves to `rejectionReason`).

In `LibraryPage.test.tsx`, pass `loadLimits={async () => ({ max_bytes: 52_428_800, max_pages: 500 })}` everywhere `LibraryPage` renders (define `const limits = async () => (...)`), **replace** the "refuses an oversized file" test, and add:
```tsx
  it("refuses a non-PDF and an oversized file in the browser, uploads the rest, and says why", async () => {
    const upload = vi.fn(async () => {});
    render(<LibraryPage load={async () => []} upload={upload} loadLimits={limits} />);
    await screen.findByText("Upload your first document");
    const docx = new File(["x"], "reading-list.docx", { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" });
    const big = new File(["x"], "deep-learning-book-full.pdf", { type: "application/pdf" });
    Object.defineProperty(big, "size", { value: 72 * 1_048_576 });
    const good = new File(["%PDF"], "paper.pdf", { type: "application/pdf" });

    await userEvent.upload(screen.getByLabelText("Upload PDFs"), [docx, big, good], { applyAccept: false });

    expect(await screen.findByText("Not uploaded. Only PDF files can be uploaded.")).toBeVisible();
    expect(screen.getByText("reading-list.docx")).toBeVisible();
    expect(screen.getByText("Not uploaded. This file is 72 MB; the limit is 50 MB.")).toBeVisible();
    expect(upload).toHaveBeenCalledTimes(1);
    expect(upload).toHaveBeenCalledWith(good);
  });

  it("makes no request at all for a refused file", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    const upload = vi.fn(async () => {});
    render(<LibraryPage load={async () => []} upload={upload} loadLimits={limits} />);
    await screen.findByText("Upload your first document");
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), new File(["x"], "a.txt", { type: "text/plain" }), { applyAccept: false });
    expect(await screen.findByText("Not uploaded. Only PDF files can be uploaded.")).toBeVisible();
    expect(upload).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
    fetch.mockRestore();
  });

  it("states the limits from settings in the first-run card", async () => {
    render(<LibraryPage load={async () => []} upload={vi.fn()} loadLimits={async () => ({ max_bytes: 10 * 1_048_576, max_pages: 200 })} />);
    expect(await screen.findByText(/PDFs up to 10 MB and 200 pages/)).toBeVisible();
  });
```
Run `cd web && npx vitest run src/api src/features/library` → FAIL.

- [ ] **Step 2: Implement `documents.ts`**
```ts
import { getUploadLimits, listDocuments, startUpload } from "./generated/sdk.gen";
import type { DocumentResponse, UploadLimitsResponse } from "./generated/types.gen";

export type UploadLimits = UploadLimitsResponse;

const MIB = 1_048_576;

export async function loadUploadLimits(apiClient: Client = client): Promise<UploadLimits> {
  const { data, error, response } = await getUploadLimits({ client: apiClient, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`GET /uploads/limits failed (${response?.status ?? "no response"})`);
  return data;
}

// Rounded up, so a file just over the limit never reads as equal to it.
const megabytes = (bytes: number) => String(Math.ceil((bytes / MIB) * 10) / 10);

function isPdf(file: File): boolean {
  return file.type === "application/pdf" || (file.type === "" && file.name.toLowerCase().endsWith(".pdf"));
}

// Checked before upload (PRD §8 US-2); the presigned POST enforces the size again on the server.
export function rejectionReason(file: File, limits: UploadLimits): string | null {
  if (!isPdf(file)) return "Not uploaded. Only PDF files can be uploaded.";
  if (file.size === 0) return "Not uploaded. This file is empty.";
  if (file.size > limits.max_bytes)
    return `Not uploaded. This file is ${megabytes(file.size)} MB; the limit is ${megabytes(limits.max_bytes)} MB.`;
  return null;
}
```
Remove `MAX_UPLOAD_BYTES` and the size check from `uploadPdf` (update its comment). Note: `Math.ceil(72*10)/10` = 72 → "72"; 52,428,801 B → 50.0000009 MiB → ceil(500.00001)/10 = 50.1 → "50.1". Good.

- [ ] **Step 3: Implement `LibraryPage.tsx`**
- New prop `loadLimits = defaultLoadLimits` (`const defaultLoadLimits = () => loadUploadLimits();`).
- State `const [limits, setLimits] = useState<UploadLimits | null>(null);` loaded in a `useEffect` (ignore errors — the pick handler retries).
- State `rejected: { name: string; reason: string }[]`; clear it at the start of each pick (with `failed`).
- In `onPick`: `const current = limits ?? (await loadLimits().then((l) => (setLimits(l), l)).catch(() => null));`. If `current` is null, treat every file as an upload failure (existing message). For each file: `const reason = rejectionReason(file, current)`; if a reason, push `{ name: file.name, reason }`, and continue (no `upload`, no `refresh` for that file). Otherwise run the existing upload flow.
- Announce rejections in the live region: after the loop, if any were rejected and nothing else set the status last, `setStatus` to `"Not uploaded: <names joined by ', '>."` — keep it simple: set status per rejected file as `Not uploaded: ${file.name}.` inside the loop (the last message wins, like the existing flow).
- Render, below the existing `{failed && ...}` block:
```tsx
      {rejected.length > 0 && (
        <ul className={styles.rejected} aria-label="Files not uploaded">
          {rejected.map((r) => (
            <li key={r.name}>
              <AlertCircle aria-hidden="true" strokeWidth={1.75} />
              <span>
                <span className={styles.rejectedName}>{r.name}</span>
                <span className={styles.rejectedReason}>{r.reason}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
```
(`AlertCircle` from `lucide-react`.) Keys: if two files share a name use `${r.name}-${index}`.
- First-run copy: `PDFs up to {limits ? megabytes : 50} MB...` — to avoid a code literal, render the sentence only with the limits: `{limits ? <p>PDFs up to {limits.max_bytes / 1_048_576} MB and {limits.max_pages} pages. Your documents stay private to you.</p> : <p>Your documents stay private to you.</p>}`.

CSS in `LibraryPage.module.css` (tokens only):
```css
.rejected {
  margin: 0 0 var(--sp-4); padding: 0; list-style: none;
  border-radius: var(--r-md); background: var(--danger-soft);
}
.rejected li { display: flex; gap: var(--sp-3); padding: var(--sp-3) var(--sp-4); }
.rejected li + li { border-top: 1px solid var(--border); }
.rejected svg { flex: none; width: 1.25rem; height: 1.25rem; color: var(--danger); }
.rejectedName { display: block; font-weight: 600; color: var(--text-1); overflow-wrap: anywhere; }
.rejectedReason { display: block; color: var(--danger); }
```
Check every token name exists in the token CSS (`grep -rn -- "--text-1\|--border:" web/src`); use the names actually defined.

- [ ] **Step 4: Run** — `cd web && npx vitest run && npm run build`. Render the page against the mockup if the stack is available; otherwise compare against the PNG. Expected: PASS.
- [ ] **Step 5: Commit** — `"Refuse non-PDFs and oversized files in the browser with their reason"`.

---

### Task 6: Docs

**Files:**
- Modify: `sdd/prd.md` — bump the status line to v2.11 and set "Changes from v2.10": the limits are SSM parameters `/smart-tutor/max-upload-mb` (50) and `/smart-tutor/max-pages` (500), read at startup; `GET /uploads/limits` serves them to the browser; the new failure reason "This PDF has N pages; the limit is 500"; browser rejection copy. Add the two parameter names to the §9.12 settings row ("file limits" → "file limits (`max-upload-mb` 50, `max-pages` 500)"), and the page-limit reason to the §9.5/§9.6 failed-transition text that lists the reasons.
- Modify: `backend/src/smart_tutor/knowledge/README.md` — mention `FileLimits`, `load_file_limits`, `TooManyPagesError`.
- Modify: `README.md` or `backend/README.md` only if they describe the local SSM parameters or the 50 MB constant (grep `50 MB\|MAX_UPLOAD\|learning-record-idle`).

- [ ] **Step 1:** Make the edits. Keep the PRD's existing wording style.
- [ ] **Step 2:** `grep -rn "MAX_UPLOAD_BYTES" backend web/src` → no hits.
- [ ] **Step 3: Commit** — `"Document file limits as settings in the PRD and knowledge README"`.
