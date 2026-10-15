# backend

The one Python package, `smart_tutor`, shared by every backend deployable.

| Path | What |
|---|---|
| `src/smart_tutor/shared/` | Shared kernel: ids, `TokenUsage`, `Citation`, `ModelFactory` (LangChain chat and embedding models by role), auth, infra clients, settings |
| `src/smart_tutor/<module>/` | Feature modules (`knowledge`, `tutoring`, `learning`, `accounts`, `insights`; R2: `catalog`, `quizzes`, `recommendations`, `reports`), each with `domain/ application/ ports/ adapters/` |
| `src/smart_tutor/apps/` | Entrypoints: `api`, `agent`, `mcp_server`, `worker`, `jobs` |
| `tests/` | `unit/` (fakes, no I/O), `integration/` (Compose stack), `isolation/` (US-12), `fakes/` |
| `evals/` | Langfuse dataset generators, evaluators, thresholds, runner |

## Commands

```bash
uv sync                      # core + dev group (includes the PDF loader and chunking deps)
uv sync --extra ingest       # + PDF loader (worker)
uv sync --extra eval         # + evaluation deps
uv run pytest                # unit tests
uv run pytest -m integration # needs `make up`
uv run lint-imports          # architecture rules (see pyproject.toml)
uv run ruff check . && uv run mypy
```

## Images

`Dockerfile` has one target per deployable: `api`, `agent`, `mcp`, `worker` (only the worker installs `[ingest]`). CronJobs reuse the `api` image.

Design: `sdd/specs/2026-10-02-project-structure-design.md`.

## Check sign-in against Compose

The unit tests fake Keycloak; this is the end-to-end check for US-1 (#45).

1. `docker compose down -v && docker compose --profile app up -d --build` (re-imports the realm, runs `migrate`). `down -v` wipes local Compose data (database, Keycloak users).
2. Open http://localhost:10453, sign in as `learner@example.com` / `learner`: the Library shows "Upload your first document" and the user menu shows "Local Learner".
3. In the browser's dev tools, copy the `Authorization` header of the `GET /me` request, then:
   `curl -i http://localhost:10450/me -H "Authorization: Bearer <token>"` → `200`.
4. Sign out from the user menu, then repeat the `curl` → `401` (the token is revoked although not expired).
5. `curl -i http://localhost:10450/me` → `401` with `WWW-Authenticate: Bearer`.

## Compose check: upload a PDF (#60)

1. `docker compose --profile app up -d --build` and open http://localhost:10453; sign in as `learner@example.com` / `learner`.
2. Library → **Choose PDFs** (**Upload** once the library has documents) → pick a PDF under 50 MB. A row with the file name shows **Processing** within a few seconds.
3. `docker compose logs worker` shows `upload <id>: stored`; the object is in `contents/`, not in `uploads/`:
   `docker compose exec localstack awslocal s3 ls s3://smart-tutor-documents/ --recursive`
4. After the first upload is processed, choose the same file again: the browser check says **Already in your library** and uploads nothing. A duplicate the server detects (the browser check can be bypassed) shows **Already in your library** on the tray row and adds no row. Sign in as `learner2@example.com` and upload the same file: it gets its own document, processed in full. The contents count goes up by one per learner: `docker compose exec postgres psql -U smart_tutor -c "select owner_id, count(*) from contents group by owner_id"`.

## Compose check: processing to ready (#61)

1. Put `AWS_PROFILE=<profile>` in `.env` (Bedrock embeddings; the worker mounts `~/.aws` read-only), then `docker compose --profile app up -d --build`.
2. Sign in at http://localhost:10453 as `learner@example.com` / `learner` and upload an arXiv PDF in the Library. After processing, the row turns **Ready** with subject **General**.
3. Verify:
   - `docker compose exec localstack awslocal s3 ls s3://smart-tutor-documents/contents/` shows `<owner_id>/<content_id>.pdf` and `<owner_id>/<content_id>.pages.json`.
   - `docker compose exec postgres psql -U smart_tutor -c "select seq, page, left(text, 40) from chunks order by content_id, seq limit 5"`
   - `docker compose exec postgres psql -U smart_tutor -c "select chunker, embedding_model, embedding_dim, pages from contents"`
4. Upload a non-PDF renamed `.pdf`: the row shows **Failed — This file isn't a readable PDF**. Upload a scanned (image-only) PDF: **Failed — No text layer (scanned PDFs are not supported yet)**. Neither creates chunks.

The inline `configs.content` in `compose.yaml` needs Docker Compose 2.23.1 or newer.
