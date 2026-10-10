# Upload and Ask in On-Premise Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On-premise mode runs the whole core product from the VM: a learner signs in, uploads a PDF, it is processed by the worker, and they ask a question and get a cited answer (#149).

**Architecture:** The worker, agent, and MCP server join `deploy/on-premise/compose.yaml`, reaching Bedrock, S3, SQS, and SSM through the instance profile. The instance role gets the union of native-cloud's API, worker, agent, and MCP permissions, built from one shared module so the two modes can't drift. The worker container is isolated (non-root, read-only root, no capabilities, no new privileges, CPU and memory limits) and PDF extraction runs in a child process killed after a per-file timeout. The pilot smoke test gains an opt-in end-to-end flow (sign in, upload, ready, ask, cited answer).

**Tech Stack:** Python 3.12 (backend, `multiprocessing`), AWS CDK (Python), Docker Compose, bash, stdlib-only smoke test.

**Spec:** GitHub issue #149 (parent #145); PRD `sdd/prd.md` v2.27 §9.5, §9.10, §9.12, Appendix A; ADR 0012.

## Global Constraints

- Native-cloud resources are untouched: the synthesized native-cloud templates must be byte-identical before and after (baseline dumped before Task 2).
- The egress allowlist is out of scope (#153).
- The viewer endpoint `GET /documents/{id}/file` is #123's; here only the on-premise bucket's CORS (GET from the on-premise origin) and an instance role that may `s3:GetObject` on `contents/*` (so its presigned GETs work).
- Tokens and secrets never on a command line, in logs, or in output (deploy.sh rule; the smoke test reads the learner's credentials from environment variables).
- Checks: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`; `cd infra && uv run pytest`.
- Files the VM runs keep LF line endings.

## Review Focus

1. A PDF that makes the parser hang or spin (C-level loop) → the document ends failed with a timeout reason; the worker keeps serving the next message. (Task 1 test with a child that sleeps forever.)
2. The parser child dies (OOM kill) → document fails "unreadable", worker continues. (Task 1 test with a child that `os._exit`s.)
3. `TooManyPagesError` crossing the process boundary keeps its page count. (Task 1 test.)
4. A worker container started without its isolation settings → the deploy fails. (Task 3 deploy.sh assertion + compose test.)
5. Smoke test leaves no document behind even when the ask step fails. (Task 4 test: cleanup runs on failure.)

---

### Task 1: Per-file extraction timeout in the worker (backend)

**Files:**
- Modify: `backend/src/smart_tutor/knowledge/ports/pdf_extractor.py` (add `ExtractionTimeoutError`)
- Create: `backend/src/smart_tutor/knowledge/adapters/time_limited_extractor.py`
- Modify: `backend/src/smart_tutor/knowledge/domain/content.py` (add `EXTRACTION_TIMED_OUT`)
- Modify: `backend/src/smart_tutor/knowledge/application/ingestion_service.py` (catch it → `_fail`)
- Modify: `backend/src/smart_tutor/shared/config.py` (`extraction_timeout_seconds: int = 300`)
- Modify: `backend/src/smart_tutor/apps/worker/main.py` (wrap `PypdfExtractor()`)
- Test: `backend/tests/unit/knowledge/test_time_limited_extractor.py`, `backend/tests/unit/knowledge/test_processing.py`

**Interfaces:**
- Produces: setting env var `SMART_TUTOR_EXTRACTION_TIMEOUT_SECONDS` (int seconds, default 300); `TimeLimitedExtractor(inner: PdfExtractor, timeout_seconds: float)`; `ExtractionTimeoutError`; reason `EXTRACTION_TIMED_OUT = "This PDF took too long to read"`.

Design: `TimeLimitedExtractor.extract_pages` starts a `multiprocessing.get_context("spawn").Process` running a module-level `_extract(conn, inner, data, max_pages, first)` that sends a tagged tuple over a `Pipe(duplex=False)`: `("pages", list[str])`, `("too_many", pages: int)`, `("unreadable", message: str)`. The parent waits with `conn.poll(timeout)`; on no data it `kill()`s and `join()`s the child and raises `ExtractionTimeoutError`; on EOF (child died with no result) raises `UnreadablePdfError(f"the parser exited with code {exitcode}")`. Always close both pipe ends and `join` the child. Tagged tuples instead of pickled exceptions because `TooManyPagesError(pages)` doesn't survive pickling (its args hold the message, not the count). A child process, not SIGALRM, because a signal can't interrupt a long C call (e.g. zlib inside pypdf). Spawn so it behaves the same on Linux and Windows and never forks a threaded process.

- [ ] Step 1: Tests in `test_time_limited_extractor.py`, with module-level (picklable) fake extractors: returns the inner's pages; `TooManyPagesError` keeps `.pages == 600`; `UnreadablePdfError` passes through; an inner that `time.sleep(60)` with `timeout_seconds=1` raises `ExtractionTimeoutError` in well under 10 s and leaves no live child (`multiprocessing.active_children() == []`); an inner that `os._exit(137)` raises `UnreadablePdfError`; real `PypdfExtractor` through the wrapper on `tests.fakes.pdfs.make_pdf(["hello world"])` returns the text.
- [ ] Step 2: Run, see them fail (`uv run pytest tests/unit/knowledge/test_time_limited_extractor.py`).
- [ ] Step 3: Implement the port error, adapter, reason constant.
- [ ] Step 4: In `test_processing.py`, a fake extractor raising `ExtractionTimeoutError` makes `process_content` return `ContentState.FAILED` and the document fails with `EXTRACTION_TIMED_OUT`. Implement: in `IngestionService.process_content` add `except ExtractionTimeoutError: return self._fail(content_id, EXTRACTION_TIMED_OUT)`; update the module docstring's list of failures.
- [ ] Step 5: Worker main: `extractor=TimeLimitedExtractor(PypdfExtractor(), settings.extraction_timeout_seconds)`; setting comment: "Seconds the worker lets the PDF parser run per extraction before the document fails (PRD §9.5, worker isolation)".
- [ ] Step 6: Full backend checks pass; commit "Time-limit PDF extraction in the worker (#149)".

### Task 2: Instance role = native-cloud's service permissions; on-premise bucket CORS (infra)

**Files:**
- Create: `infra/smart_tutor_infra/service_permissions.py`
- Modify: `infra/smart_tutor_infra/stacks/cluster.py` (use the module; template must not change)
- Modify: `infra/smart_tutor_infra/stacks/host.py` (add the statements to the instance role; expose `self.public_url`)
- Modify: `infra/smart_tutor_infra/stacks/storage.py` (`cors_methods` parameter)
- Modify: `infra/smart_tutor_infra/app_stacks.py` (Host before Storage; Storage `web_origin=host.public_url`, GET + POST)
- Test: `infra/tests/test_host.py`, `infra/tests/test_deployment_modes.py`, `infra/tests/test_storage.py`

**Interfaces:**
- Produces: `ServicePermissions(stack: cdk.Stack, names: ModeNames)` with attributes/methods `api() / worker() / agent() / mcp() -> list[iam.PolicyStatement]`, statements identical in content and order to the ones now inline in `ClusterStack` (they keep their `arn:aws:` f-strings and share the `ssm`, `chat`, `embed` statement objects). `HostStack.public_url: str` (`https://<domain>`, a token when the domain is the sslip.io default). `StorageStack(..., cors_methods: Sequence[s3.HttpMethods] = (s3.HttpMethods.POST,))`.

- [ ] Step 1: Failing tests: host instance role allows (a) `s3:PutObject` on `<on-prem bucket>/uploads/*` and `contents/*`, `s3:GetObject` on `uploads/*` and `contents/*` (the viewer's presigned GET), `s3:DeleteObject` on `uploads/*`, `s3:ListBucketVersions` and `s3:DeleteObjectVersion` as the API; (b) `sqs:SendMessage`, `ReceiveMessage`, `DeleteMessage`, `ChangeMessageVisibility`, `GetQueueAttributes` on the on-premise ingest queue ARN; (c) Bedrock invoke on the agent inference profile, its foundation model in `us-east-1`, `us-east-2`, `us-west-2`, and the embedding model; (d) no statement names a native-cloud resource (`smart-tutor-documents-`, `:smart-tutor-ingest`). On-premise Storage: CORS rule with `AllowedMethods` `["GET", "POST"]` and `AllowedOrigins` equal to the Host's public URL (an `Fn::ImportValue` when the domain is default; the literal `https://tutor.example.org` when `smart-tutor:on-premise-domain=tutor.example.org`). Replace `test_on_premise_bucket_has_no_cors_until_the_host_has_an_address`.
- [ ] Step 2: Implement. Order on-premise stacks so Host is built first and Storage gets `web_origin=host.public_url, cors_methods=(GET, POST)`; Host must not reference Storage. Update the Storage and Host docstrings (Storage: "#149 gives on-premise CORS for the Host's address; GET is for the document viewer's presigned link").
- [ ] Step 3: `cd infra && uv run pytest` passes; re-dump the native-cloud templates with `C:/Users/dtrun/.claude/jobs/88e442bd/tmp/dump_native.py` to `.../tmp/after-native` and `diff -r` against `.../tmp/baseline-native`: no difference.
- [ ] Step 4: Commit "Give the on-premise host the services' AWS permissions and CORS (#149)".

### Task 3: Worker, agent, and MCP server in Compose, with worker isolation (deploy)

**Files:**
- Modify: `deploy/on-premise/compose.yaml`, `deploy/on-premise/deploy.sh`
- Test: `infra/tests/test_host.py` (compose section)

**Interfaces:**
- Consumes: `SMART_TUTOR_EXTRACTION_TIMEOUT_SECONDS` (Task 1). Env file keys already rendered by deploy.sh: `REGISTRY, IMAGE_TAG, DOMAIN, AWS_REGION, SSM_PATH, DOCUMENTS_BUCKET, INGEST_QUEUE_URL, APP_DATABASE_URL, API_CLIENT_SECRET, MCP_CLIENT_SECRET`.

Services (mirror the Helm charts `deploy/helm/smart-tutor/charts/{agent,mcp-server,worker}`):
- `agent`: image `${REGISTRY:?}/smart-tutor/agent:${IMAGE_TAG:?}`; env `SMART_TUTOR_ENVIRONMENT=prod`, `SMART_TUTOR_AWS_REGION`, `AWS_REGION`, issuer `https://${DOMAIN:?}/auth/realms/smart-tutor`, internal `http://keycloak:8080/auth/realms/smart-tutor`, client `smart-tutor-api` + `${API_CLIENT_SECRET:?}`, `SMART_TUTOR_DATABASE_URL=${APP_DATABASE_URL:?}`, `SMART_TUTOR_MCP_URL=http://mcp:8000/mcp`, `HOME=/tmp`; health `python urllib /healthz` on 8080; `mem_limit: 512m`.
- `mcp`: image `.../smart-tutor/mcp:...`; env as agent but client `rag-mcp` + `${MCP_CLIENT_SECRET:?}`, `SMART_TUTOR_KEYCLOAK_AUDIENCE=rag-mcp`, `SMART_TUTOR_MCP_PORT=8000`, `SMART_TUTOR_MCP_URL=http://mcp:8000/mcp`; health: python socket connect to 127.0.0.1:8000 (an unauthenticated /mcp answers 401); `mem_limit: 512m`.
- `worker`: image `.../smart-tutor/worker:...`; env region, bucket, queue URL, database URL, `SMART_TUTOR_MAX_UPLOAD_MB_PARAM`/`SMART_TUTOR_MAX_PAGES_PARAM` under `${SSM_PATH:?}`, `SMART_TUTOR_EXTRACTION_TIMEOUT_SECONDS: "300"`, `HOME=/tmp`; `user: "10001:10001"`, `read_only: true`, `tmpfs: [/tmp:size=64m]`, `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, `cpus: 1.0`, `mem_limit: 1536m`, `pids_limit: 256`, `stop_grace_period: 60s`; health: `python -c` checks `/proc/1/cmdline` contains `smart_tutor.apps.worker` (no HTTP server).
- agent and mcp also get `read_only`, `/tmp` tmpfs, `cap_drop`, `no-new-privileges` (the Helm chart already runs them that way). `api` depends on `agent` (started); `agent` on `mcp`.
- Header comment: drop "The worker, agent, and MCP server join in #149".

deploy.sh: after `up -d --wait`, assert the running worker's isolation with `docker inspect` (`.Config.User == 10001:10001`, `.HostConfig.ReadonlyRootfs == true`, `CapDrop` contains `ALL`, `SecurityOpt` contains `no-new-privileges:true`) and exit non-zero with a clear message otherwise; also check the agent answers `/healthz` and the MCP server answers 401 without a token from inside the `api` container (as deploy-pilot.yml does).

- [ ] Step 1: Failing compose tests: services set = `LONG_RUNNING | {migrate, pg-dump}` with `LONG_RUNNING` gaining agent, mcp, worker; images from ECR by tag; worker isolation keys above; agent/mcp/worker params under `${SSM_PATH:?}`; worker reads the on-premise bucket and queue variables; no service other than caddy publishes ports; deploy.sh contains the isolation assertion (`ReadonlyRootfs`, `10001`, `CapDrop`, `no-new-privileges`) after `up -d --wait`.
- [ ] Step 2: Implement compose and deploy.sh. `bash -n deploy/on-premise/deploy.sh`.
- [ ] Step 3: `cd infra && uv run pytest`; commit "Run the worker, agent, and MCP server on the on-premise VM (#149)".

### Task 4: End-to-end pilot smoke test (deploy/pilot)

**Files:**
- Modify: `deploy/pilot/smoke_test.py`
- Test: `infra/tests/test_smoke_test.py`

**Interfaces:**
- Produces: `python3 deploy/pilot/smoke_test.py <url> --end-to-end` reads `SMOKE_TEST_USERNAME` and `SMOKE_TEST_PASSWORD` from the environment (fails with a clear message if missing).

Flow (stdlib only, one `http.cookiejar` opener, a redirect handler that stops at the app's own redirect URI):
1. Sign in: PKCE S256 authorization-code flow against `<url>/auth/realms/smart-tutor/protocol/openid-connect/auth` with `client_id=smart-tutor-web`, `redirect_uri=<url>/`, `scope=openid`; parse the login form's `action` (HTML-unescape), POST `username`, `password`, `credentialId=`; read `code` from the redirect `Location`; exchange at `/token` with the `code_verifier`.
2. Upload: build a one-page PDF in memory (port `backend/tests/fakes/pdfs.make_pdf`) whose text holds a per-run passphrase, e.g. "The Smart Tutor smoke test passphrase is <run-id>. ..." (≥ 50 non-space characters); `POST /api/uploads {"file_name": "smoke-test-<run-id>.pdf"}`; multipart POST the returned `fields` + `file` to `url` (expect 204/201).
3. Ready: poll `GET /api/uploads/{upload_id}` until `document_id`; poll `GET /api/documents` until that document is `awaiting_subjects` (fail on `failed`, reporting `failure_reason`); `GET .../subject-suggestions`; `PUT .../subjects` with the first suggestion that has a `subject_id`, else `new_names: ["Smoke testing"]` (one fixed name so the shared catalog gains at most one subject); the response state must be `ready`.
4. Ask: `POST /api/threads {"question": "What is the Smart Tutor smoke test passphrase?"}`, read the SSE stream; require `thread`, a `citations` event with ≥ 1 citation whose `document_id` is ours, and `done`.
5. Clean up in `finally`: `DELETE` the thread (if started; route in `backend/src/smart_tutor/apps/api/routes/threads.py`) and the document. A cleanup failure is reported but doesn't hide the original failure.
Deadline: the same `--deadline-seconds` for the whole flow (default 600). Never print the token or password.

- [ ] Step 1: Tests against the existing local fake server pattern in `test_smoke_test.py`: extend it with a fake Keycloak login form + token endpoint, a fake S3 POST, and fake API routes; cases: happy path passes and deletes thread and document; a `failed` document fails with its reason and still deletes; an answer with no citation of our document fails; missing env credentials → exit 1 with a message; the password never appears in captured output.
- [ ] Step 2: Implement; run `cd infra && uv run pytest tests/test_smoke_test.py`.
- [ ] Step 3: Commit "Smoke-test sign-in, upload, and a cited answer (#149)".

### Task 5: Docs (main session)

- `sdd/prd.md`: bump to v2.28; Changes row (#149): worker, agent, MCP on the VM, the extraction time limit and its reason "This PDF took too long to read" (§9.5 failure list), on-premise bucket CORS GET + POST for the host's address, the instance role's union of permissions incl. GetObject on `contents/*`.
- `docs/runbooks/on-premise-deploy.md`: end-to-end smoke test with the test learner from Secrets Manager; DLQ drill (stop the worker, send a message, receive 5 times with visibility 0, see it in the DLQ, start the worker, purge the DLQ); checking worker isolation by hand.
- `AGENTS.md` doc table unchanged; update `sdd/specs/2026-10-02-project-structure-design.md` only if it lists infra modules.
