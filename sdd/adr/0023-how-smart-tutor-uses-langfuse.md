# 0023. How Smart Tutor uses Langfuse: OTLP ingestion, three projects, a retention job of ours

- Status: accepted
- Date: 2026-10-14
- Supersedes: what remains of ADR 0017 once the Langfuse migration (#316–#322) lands: Phoenix for runtime traces and
  ratings, its local Compose instance, and its retention policy. 0017's tracing rules carry over (below).

## Context

ADR 0021 chose Langfuse for traces, ratings, annotation queues, datasets, experiments, and CI evals, on a shared
self-hosted host (`platform/langfuse`, Langfuse v4) that knows nothing about Smart Tutor and runs 07:00–18:00
Asia/Ho_Chi_Minh (ADR 0022). It left open how Smart Tutor uses it (#315). Facts checked on 2026-10-14 against Langfuse's
docs and source (v4.58.0):

- **Ingestion.** Langfuse takes OTLP/HTTP (protobuf or JSON, no gRPC) at `/api/public/otel/v1/traces`, with Basic auth
  (public key : secret key) and the header `x-langfuse-ingestion-version: 4` (without it, ingestion can lag up to 10
  minutes). The API key alone selects the project; no span attribute can. It maps OpenInference's span kinds (CHAIN,
  RETRIEVER, TOOL, LLM → generation, EMBEDDING), `input.value`/`output.value`, and `llm.token_count.*`. It reads
  `user.id` and `session.id` as the trace's user and session, `langfuse.trace.metadata.*` as trace metadata, and
  `langfuse.environment` (span or resource) as the environment. Other attributes land under `metadata.attributes`.
  Trace ids are the OpenTelemetry trace id as 32 lowercase hex characters, so a run id's `uuid.hex`.
- **v4 is observations-first.** Filters on user, session, and metadata apply per observation, so those attributes
  belong on every span of a trace, not only the root.
- **Retention is Enterprise-only when self-hosted.** The project retention setting and `LANGFUSE_INIT_PROJECT_RETENTION`
  do nothing without a licence key. There is no delete-by-date API. `DELETE /api/public/traces` takes 1–1,000 trace ids
  and deletes asynchronously (usually within 15 minutes), with each trace's observations, scores, raw events in S3, and
  media. ClickHouse TTLs would work, but Langfuse says its ClickHouse schema is not a stable contract.
- **Scores.** `POST /api/public/scores` (name, value, `dataType` NUMERIC, BOOLEAN, or CATEGORICAL, `traceId`,
  `environment`, optional `id` and `configId`) is processed asynchronously. A re-post with the same id replaces the
  score only on the same day; the server sets the timestamp. The score's environment defaults to `default` and is not
  taken from the trace. `DELETE /api/public/scores/{id}` deletes one.
- **Licence.** Datasets, experiments, annotation queues, score configs, and LLM-as-a-judge evaluators on live traces
  are in the MIT edition. Project-level roles (RBAC), retention, and the API that creates projects need a licence. In
  the MIT edition, a member's role applies to every project of their organization.
- **Projects.** Headless initialization makes one organization and one project (the host's `Platform` / `Sandbox`).
  Further projects and their keys are made in the UI.
- **Sampling** is client-side only.

What ADR 0017 required of tracing still holds: one `ask` trace per question whose id is the turn's run id; deployment,
model ids, thread id, `limited`, decline code, and chunk count on it; the learner named only by the keyed learner hash,
never a user id, email, or token (ADR 0007); a tracing failure never fails a request or a document's processing; the
`trace-sampling-rate` setting; traces gone after at most 180 days (D25); no test run sends a trace anywhere.

## Decision

### 1. Ingestion: keep OpenTelemetry and OpenInference, export to Langfuse's OTLP endpoint

- The exporter's endpoint becomes `<langfuse-url>/api/public/otel/v1/traces`, with `authorization: Basic
  base64(public:secret)` and `x-langfuse-ingestion-version: 4`. The rest stays: the `ask` and `ingest` root spans we
  create, `LangChainInstrumentor` for LangGraph and model spans, the run-id trace ids (`RunIds`), the `RunIdRatio`
  sampler, the batched export off the request path, and `never_raising`.
- **The environment** is a resource attribute: `langfuse.environment` = the process's deployment (`local`,
  `on-premise`), or `ci` in the CI eval stack.
- **The learner and the thread** go on every span of the run. Start the run inside OpenInference's
  `using_attributes(user_id=<learner hash>, session_id=<thread id>)`, which the instrumentor copies onto each LangChain
  span, and set `user.id` and `session.id` on our root spans. Langfuse then lists each learner hash as a user and
  each thread as a session. The learner hash is the only user id Langfuse ever sees.
- **Run metadata** (deployment, model ids, `limited`, decline code, chunk count, thread id, learner hash, and for
  `ingest` the content id) goes into `langfuse.trace.metadata.<key>` on the root span. That makes each key a filterable
  trace field instead of a JSON blob under `metadata.attributes`.
- **The root's input and output** go into `langfuse.observation.input` and `langfuse.observation.output`, besides the
  OpenInference `input.value` and `output.value` (v4 deprecates `langfuse.trace.input`/`output`).
- **One project per environment for both services.** `ask` and `ingest` are told apart by trace name, not by an
  `-ingestion` project; a second project would need a second key pair everywhere.
- **The Langfuse SDK is not used at runtime.** The evals may use it (#317, #320).

### 2. Retention (D25, Q34): a daily deletion job of ours, on the app host

- A Smart Tutor scheduled job, `trace-retention` (`smart_tutor.apps.jobs`), runs daily on the on-premise host: a
  one-off container in Compose's `jobs` profile started by `smart-tutor-trace-retention.timer` with `Persistent=true`,
  as the nightly dump is. It lists the project's traces older than **178 days** and
  deletes them through `DELETE /api/public/traces` in batches of up to 1,000. The two days of margin cover a run missed
  while the host was off, the next morning's catch-up, and Langfuse's asynchronous delete, so no trace outlives 180
  days.
- It uses the on-premise project's own key, so it can only ever list or delete Smart Tutor's production traces.
  Deleting a trace also deletes its scores (ratings) and raw events.
- It runs only on the on-premise project. The local project holds developers' test data, and the evals project holds
  datasets and experiments that must not expire.
- A failure leaves the next run to catch up and is written to the journal (`journalctl -u smart-tutor-trace-retention`),
  where ADR 0022 says job failures are checked. The retention runbook lists the check.
- The Langfuse host stays app-neutral: it neither runs nor knows about this job.

### 3. Local development: the shared host, project `smart-tutor-local`; no Langfuse in Compose

- Developers' runtime traces go to the shared host's `smart-tutor-local` project, environment `local`. Each developer
  creates their own key pair in that project and puts it in their `.env` (`SMART_TUTOR_LANGFUSE_PUBLIC_KEY`,
  `SMART_TUTOR_LANGFUSE_SECRET_KEY`), so one key can be revoked without touching the others. Without keys, a local run
  is untraced, as it is without a Phoenix URL today.
- 18:00–07:00 the host is off and local runs are untraced. Export errors are logged by the OpenTelemetry SDK and
  dropped, as for any tracing failure.
- **ADR 0017's separation holds, now at the project level.** Keys are per project: a local key can neither write to
  nor read the production project, and no developer needs the production key. Production traces no longer live on the
  app host but on the Langfuse host, as they lived in LangSmith before ADR 0017.
- The local Phoenix leaves Compose with #322. Compose gets no Langfuse: it would add web, worker, ClickHouse, Postgres,
  Redis, and object storage to every developer's machine.

### 4. CI evals at night: check the host first and fail fast with a clear message

- The smoke workflow checks `<langfuse-url>/api/public/health` before starting the app stack. If Langfuse doesn't
  answer, the job fails within a minute, before any Bedrock spend, with the message "Langfuse is off 18:00–07:00
  Asia/Ho_Chi_Minh: re-run this job after 07:00, or start the host (`docs/runbooks/langfuse-host.md`)".
- It fails rather than skips, so an agent change merged at night can't pass the eval gate unseen. Forks and missing
  secrets still skip with a notice, as now.
- CI doesn't start the host: Smart Tutor's CI role would then need rights on the platform's instance, and a host
  started at night stays up until the 00:00 stop.

### 5. Projects, environments, keys, and people

All Smart Tutor projects live in a Langfuse organization of their own, **Smart Tutor**, made by the host's admin in the
UI. In the MIT edition roles are per organization, so this keeps other apps' members out of learners' traces and
Smart Tutor's members out of other apps'.

| Project | What it holds | Environments | Keys |
|---|---|---|---|
| `smart-tutor-on-premise` | Production `ask` and `ingest` traces, ratings | `on-premise` | Secrets Manager `<prefix>/langfuse/public-key` and `<prefix>/langfuse/secret-key`, created by the operator (runbook) |
| `smart-tutor-local` | Developers' runtime traces | `local` | One pair per developer, in their `.env` |
| `smart-tutor-evals` | Datasets, annotation queues, experiments, and the CI app stack's traces | `local`, `ci` | CI: GitHub secrets `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`; developers: one pair each in `.env` |

- **One evals project, not separate local and CI projects.** Langfuse datasets, queues, and experiments belong to one
  project, and a developer's eval run and CI's smoke run must read the same dataset versions. The environment tells
  their runs apart.
- **The evals use only endpoints Langfuse v4 keeps in `events_only` mode** (the host's default write mode, #342).
  That mode answers 404 on `GET /api/public/traces` and `GET /api/public/scores`, and 400 on
  `POST /api/public/ingestion` for everything but scores. So a review candidate is an OpenTelemetry root span sent to
  the OTLP endpoint (its trace's only observation, named `<dataset>-candidates`); the annotation queue holds that
  observation; candidates are read back with the Observations API v2 and the reviewer's `accepted` scores with the
  Scores API v3. Experiments run through the SDK's experiment runner. We do not set the host's
  `LANGFUSE_MIGRATION_V4_WRITE_MODE` to `legacy` or `dual`: it is shared by every app, and those modes are for migrating.
- **The Langfuse URL** is a setting (`SMART_TUTOR_LANGFUSE_URL`). On-premise it comes from the CDK context
  `smart-tutor:langfuse-url` through an SSM parameter. CI keeps it as a repository variable. It is the host's DuckDNS
  name, never a reference to the `Langfuse-Host` stack.
- **The learner-hash key** is a new CDK-generated secret, `<prefix>/langfuse/learner-hash-key`, so Langfuse traces
  start with one key throughout. Phoenix keeps its own key until #322 retires it; Phoenix traces aren't migrated.
- **The worker** reaches Langfuse through its Squid proxy. The allowlist gains the Langfuse host's name, by exact name
  (ADR 0014).
- **Without keys** a deployed process runs untraced, as now. The rule that a learner-hash key is required while
  tracing is on still applies.

### 6. Ratings: a `learner_rating` BOOLEAN score on the ask's trace

- Each 👍/👎 is a score named `learner_rating` with `dataType` BOOLEAN (1 for up, 0 for down) on the trace whose id is
  the turn's run id, with the deployment as its environment. It is checked against a score config of the same name
  in each project, and carries no comment, user id, email, or token.
- **Replacing and clearing.** A same-id re-post replaces a score only on the same day, and deletes are asynchronous.
  So each rating is posted with a **new** score id, then the adapter deletes the trace's other `learner_rating`
  scores (listed by trace and name). Clearing deletes them all. Reusing one id would let a pending delete remove the
  re-posted score. If a quick change leaves two scores for a moment, readers take the newest.
- It goes off the request on one background thread, in the order rated, through the existing `AnswerFeedback` port.
  A Langfuse outage is logged and never fails the rating, which is already saved with the turn.
- A score may name a trace that hasn't arrived yet: Langfuse never looks the trace up, so there is no retry (confirmed
  in #318 against the source of the host's version, 4.47.0).

### 7. Native-cloud stays out of scope

It isn't deployed. Its Helm charts lose their stale LangSmith wiring in #322 and get Langfuse settings when
native-cloud is picked up again.

## Alternatives rejected

- **Ingestion through the Langfuse Python SDK** (v4, OpenTelemetry-based). It gives typed observations and score
  helpers. But its span processor exports only Langfuse, `gen_ai.*`, and known instrumentation scopes, so our `ask`
  root would be dropped (and its children orphaned) unless we filter by hand. A custom trace id needs its
  `trace_context`. And it would be a second instrumentation path beside OpenInference, for no field the OTLP path
  can't set.
- **A Langfuse Enterprise licence for retention.** It sets 180 days per project with no code of ours, but it is a sales
  contract for one setting, on a host shared with other apps. Worth revisiting if the platform licenses Langfuse for
  other reasons. Then the job is removed.
- **ClickHouse TTLs on the host.** They change Langfuse's schema, which isn't a stable contract. They would apply to
  every app on the shared host and would be lost or would conflict on upgrades.
- **The Langfuse host runs the retention job.** The platform would then have to know each app's projects and keys.
- **A Langfuse in the local Compose stack.** Six more containers and several GiB of RAM per developer, for traces that
  only help while debugging.
- **A Langfuse project per developer.** Works, and a developer may still make one, but the default is one shared local
  project with a key pair per developer.
- **Separate local and CI eval projects.** Datasets and annotation queues would be duplicated and drift apart.
- **CI starts the Langfuse host on demand.** It couples Smart Tutor's CI role to the platform's instance, costs about
  5 minutes of boot per run, and leaves the host up until 00:00.
- **CI skips the smoke evals at night with a notice.** It would leave agent changes merged after 18:00 ungated.
- **A stable score id per run.** Simple, but it replaces only within a day, and an asynchronous delete can remove the
  re-posted score.
- **`ingest` in its own `-ingestion` project.** It would need a second key pair per environment. Langfuse filters by
  trace name.

## Consequences

- #316 changes the exporter's endpoint, headers, and attributes, not the pipeline, and makes one project per
  environment. The PRD's egress wording and the worker's Squid allowlist change with it: the worker's internet egress
  now includes the Langfuse host, which a compromised parser could use to write into our own production project with
  the worker's key.
- #321 builds the retention job (a new `apps/jobs` entry, its Compose job service and systemd timer, and the 178-day
  cut-off). D25 now depends
  on a job of ours running at least every day or two.
- #318 sends BOOLEAN scores with new ids and deletes the others. Analysis of ratings takes the newest per trace.
- #317, #319, and #320 use the `smart-tutor-evals` project; CI's smoke runs fail fast at night. #342 moved their
  trace and score reads and candidate writes to v4's endpoints; a Langfuse upgrade must keep the evals on endpoints the
  new version serves (its upgrade guide lists the removed ones).
- The Langfuse admin creates the **Smart Tutor** organization, its three projects, and the `learner_rating` score
  config by hand; the runbook lists the steps.
- Learners' questions and answers live on the shared Langfuse host for up to 180 days. Anyone in the Smart Tutor
  organization can read them, as anyone with a Phoenix account could.
- Langfuse recommends an S3 lifecycle rule on its raw-event prefix (`events/`). That is a host setting for every app
  and is left to the platform: Smart Tutor's deletes remove its raw events either way.

## Notes

- 2026-10-15 (#318): on the host's v4.47.0 in events_only mode the v1/v2 score and trace read APIs answer 404, so the adapter lists scores with `GET /api/public/v3/scores` and the smoke test reads traces with `GET /api/public/v2/observations`. A delete that reaches Langfuse before the score is ingested (about 5–10 s after its POST) removes nothing, so before deleting the score it last posted for a run, the adapter waits until the list shows it (up to about a minute). A score is checked against a config only by `configId`, so the adapter looks up the project's `learner_rating` config by name and sends its id. A rating of an unsampled ask names a trace that never exists; the retention job's trace deletes don't reach it, but it holds only the boolean.
