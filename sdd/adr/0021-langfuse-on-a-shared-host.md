# 0021. Langfuse for observability and evaluation, on a shared host in its own CDK project

- Status: accepted
- Date: 2026-10-14
- Supersedes: ADR 0017's choice of Phoenix for runtime tracing (Phoenix keeps running until the Langfuse migration
  lands), and its "evals stay on LangSmith"

## Context

The LangSmith workspace hit its free plan's monthly trace cap (ADR 0017), and on 2026-10-14 it blocked eval work too
(#302's candidates couldn't be queued). Phoenix replaced LangSmith only for runtime tracing: it has no annotation
queues, so reviewing generated eval data, datasets, and experiments stayed on LangSmith. The product owner decided that
one tool, Langfuse, manages the whole lifecycle: traces, ratings, annotation queues, datasets, experiments, and CI
evals. Langfuse's self-hosted edition is MIT-licensed and includes these.

Self-hosting needs Postgres, ClickHouse (at least 2 CPU and 8 GiB for production), Redis or Valkey, and S3. That
doesn't fit beside the app on the on-premise t3.large (ADR 0017 rejected Langfuse for this reason), and the product
owner wants other apps to use the same Langfuse later.

## Decision

- **Langfuse v4, self-hosted, on a host of its own:** a t3.xlarge (4 vCPU, 16 GiB) running web, worker, ClickHouse,
  Postgres, Valkey, and Caddy with Docker Compose; files in an S3 bucket through the instance role; a 100 GiB data
  volume with daily snapshots kept 7 days.
- **Its own CDK project, `platform/langfuse`**, with the stack `Langfuse-Host`. It never references Smart Tutor's
  stacks, parameters, or secrets, and Smart Tutor never references it: apps reach it over HTTPS with a per-project API
  key. The folder can move to a repository of its own.
- **Access:** sign-up is off; headless initialization creates the first admin from Secrets Manager, who invites others.
- **Hours:** it follows the app host's hours (ADR 0022): stopped at 18:00 and 00:00 and started at 07:00
  Asia/Ho_Chi_Minh by its own copy of the scheduler construct, and patched weekly on Sunday 07:20; neither host needs
  the other to start.
- **Not decided here (the Langfuse migration):** moving Smart Tutor's tracing and ratings from Phoenix and its evals
  from LangSmith; the 180-day trace retention (D25), since Langfuse lists data-retention policies among its Enterprise
  features when self-hosted; and where CI reaches Langfuse at night, when it is off.

## Alternatives rejected

- **Langfuse on the app host:** needs about 20 GiB with the app, so a 32 GiB host (r7i.xlarge, about $193 a month
  always on); it ties Langfuse to one app.
- **Langfuse Cloud:** no host to run, but learners' questions in traces would go to a third party, which needs a
  privacy decision first.
- **Keep Phoenix and LangSmith:** two tools, and LangSmith's free cap keeps blocking evals.

## Consequences

- A second host (about $55 a month on demand at 11 hours a day, or $121 around the clock, plus its volume and
  Elastic IP) and a second deploy to run by hand (`docs/runbooks/langfuse-host.md`).
- Traces, scores, and datasets live on that host; a lost volume loses up to a day (snapshots), and there is no
  database dump.
- Evals and CI that use Langfuse work only while it runs (07:00–18:00).
