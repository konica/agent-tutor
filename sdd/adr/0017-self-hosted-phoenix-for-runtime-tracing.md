# 0017. Self-hosted Arize Phoenix for runtime tracing; evals stay on LangSmith

- Status: accepted
- Date: 2026-10-12
- Supersedes: the LangSmith parts of PRD §10.2 and §10.4 (#229) for runtime traces and ratings, and 0014's amendment (the worker no longer reaches `api.smith.langchain.com`)

## Context

The agent's `ask` runs, the worker's `ingest` runs, and learners' ratings went to LangSmith cloud. Production and local development share one LangSmith workspace on the free Developer plan, which caps traces per month. On 2026-10-12 the workspace hit that cap: every upload returns `429 Monthly unique traces usage limit exceeded`, so production and local chats leave no trace. The last production `ask` trace is from 2026-10-11 09:58 UTC.

Our own test suite helped use up the cap. Tracing is off only under `tests/unit`, but the default run also collects `tests/isolation`, whose ingestion tests call a `FakeChatModel`. When `.env` is loaded (IDE test runner, `uv run --env-file ../.env`), each run sends 100+ root runs to `smart-tutor-local`.

Self-hosted LangSmith needs an Enterprise contract. The product owner asked for a self-hosted tool instead.

What the tracing has to keep (PRD §10.4, D25, ADR 0007):
- one `ask` trace per question whose id is stored with the turn (`thread_turns.run_id`), carrying deployment, model ids, thread id, `limited`, decline code, and chunk count;
- the learner named only by a keyed hash (HMAC-SHA256 of the user id), never the user id, email, or token;
- traces deleted after at most 180 days;
- a tracing failure never fails a request or a document's processing;
- a sampling rate setting (`trace-sampling-rate`).

The on-premise host is one t3.large (2 vCPU, 8 GiB) that already runs Postgres, Keycloak, the API, agent, MCP server, worker, web, Caddy, and the egress proxy.

## Decision

**Tool.** Runtime tracing moves to a self-hosted **Arize Phoenix** (Elastic License 2.0: free to self-host; we never offer Phoenix itself as a service). Evals, datasets, annotation queues, and the CI smoke evals stay on LangSmith cloud. Their volume is a few hundred runs per eval run, which fits the free plan once tests stop tracing.

**One instance, on the on-premise production host.** Phoenix runs as a container in `deploy/on-premise/compose.yaml`, behind Caddy at `https://<domain>/phoenix` (`PHOENIX_HOST_ROOT_PATH`). Production and local development both send to it: there is no Phoenix in the local Compose file.
- On-premise services send inside Compose to `http://phoenix:6006/v1/traces`. Phoenix joins the worker's internal network, so the worker reaches it without the egress proxy, and `api.smith.langchain.com` leaves the Squid allowlist.
- Developers send to `https://<domain>/phoenix/v1/traces` over TLS.

**Storage.** A `phoenix` database and role in the existing Postgres container, made by `deploy.sh`'s role bootstrap. It is left out of the nightly `pg-dump`: traces are observability data, not learner records, and losing them on a restore is acceptable.

**Access.** Phoenix authentication is on (`PHOENIX_ENABLE_AUTH`, `PHOENIX_SECRET`). People sign in with local Phoenix accounts made by the Phoenix admin: the product owner as viewer, engineers as members. Services send with system API keys (`authorization: Bearer`):
- production: Secrets Manager `<prefix>/phoenix/api-key`;
- local development: a separate key shared by developers in `.env`, which can be revoked without touching production.

Without a key, a process runs untraced, as it does today without a LangSmith key.

**Projects and retention.** `smart-tutor-on-premise` and `smart-tutor-on-premise-ingestion` keep traces 180 days (D25), by Phoenix project retention policies. `smart-tutor-local` and `smart-tutor-local-ingestion` keep them 14 days.

**Instrumentation.** The OpenTelemetry SDK with an OTLP/HTTP exporter, plus OpenInference's `LangChainInstrumentor` for the LangGraph and model child spans.
- `ask` (agent) and `ingest` (worker) are root spans we create, carrying the metadata above as span attributes.
- An `ask` trace's id is the turn's `run_id`, and its root span id is derived from it (its low 64 bits). The API can then address the root span from the stored `run_id` without a lookup.
- Sampling is a parent-based trace-id ratio sampler set from `trace-sampling-rate`.
- Exporting is batched and off the request path. Export errors are logged and dropped.
- The agent, worker, and API no longer import `langsmith` at runtime. Only `backend/evals` and its CI do.

**Ratings.** `learner_rating` is sent as a `HUMAN` span annotation on the `ask` root span (score 1 or 0, label up or down, upserted by name; clearing a rating deletes it). It goes off the request through the existing `AnswerFeedback` port. The on-premise API gets the Phoenix settings, so production ratings are sent; until now they were only saved (§10.2). LangSmith's "a 👎 extends the trace's retention" has no Phoenix equivalent and is dropped: every production trace already lives the full 180 days.

**Tests never trace.** Tracing is switched off for the whole of `tests/`, not only `tests/unit`. A developer's test run must not reach production Phoenix or LangSmith. The privacy test (no token, user id, or email in any span or annotation, with a positive control, ADR 0007) runs against an in-memory span exporter.

**Native-cloud is out of scope.** It isn't deployed. Its Helm charts keep their LangSmith wiring until native-cloud is picked up again, which then needs its own decision on how to run Phoenix there.

## Alternatives rejected

- **Upgrade LangSmith to Plus.** Restores traces quickly for about $39 a seat per month plus per-trace overage. Rejected by the product owner in favour of self-hosting; production trace volume would keep the bill growing with usage.
- **Self-hosted LangSmith.** Enterprise contract only.
- **Langfuse v3** (MIT). Needs Postgres, ClickHouse, Redis, and S3 storage beside its web and worker containers (about 4 vCPU / 8 GB), which doesn't fit beside the app on the t3.large. Retention policies are Enterprise-only, so D25 would need a deletion job of ours.
- **LangSmith SDK in OpenTelemetry-only mode, sending to Phoenix.** Mostly configuration. But we don't control trace and span ids, so ratings would need a lookup. LangSmith's span attributes show as generic spans in Phoenix, not as LLM, retriever, and chain spans. And the private `run_helpers` restore in our current wrapper would stay.
- **A Phoenix per developer in local Compose.** No shared key and no internet hop. Rejected so the product owner and engineers look at one place for both environments.
- **Keycloak OIDC sign-in to Phoenix.** Our realm holds learners. Staff accounts and roles in it are a separate decision. Phoenix's `PHOENIX_OAUTH2_*` settings leave the door open.

## Consequences

- One more container on the on-premise host (about 1–2 GB of RAM) and a growing `phoenix` database on the data volume. The monitoring runbook watches host memory and the database's size.
- Local traces cross the internet to production, and local and production traces sit in one database, separated by project. A system key can read as well as write through Phoenix's API, production projects included. So the local key is a secret like the production one: never in the repository (ADR 0013), handed to developers out of band, and revoked in Phoenix's settings when it leaks or a developer leaves.
- Production traces hold learners' questions and answers. Anyone with a Phoenix account can read them, as anyone in the LangSmith workspace could before.
- The worker's egress allowlist shrinks to AWS endpoints only. `check-egress.py` stops probing LangSmith and checks that Phoenix answers over the internal network.
- PRD §10.2, §10.3 item 7, §10.4, D25, Q34, and §9's job table change wording from LangSmith to Phoenix in the slices that ship the behaviour. Growing eval datasets from 👎-rated production turns (§10.3 item 7) now needs an export from Phoenix into LangSmith datasets. That export is not built yet.
- The pilot smoke test's trace check queries Phoenix's API instead of LangSmith's.
- Evals still need `LANGSMITH_API_KEY` locally and in CI. The quota now covers eval runs only.
