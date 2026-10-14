# Langfuse host

A self-hosted Langfuse v4 on one EC2 VM (Docker Compose behind Caddy), shared by any app that sends it traces, scores,
and datasets. Its own CDK project, so it deploys and is destroyed apart from any app (ADR 0021).

| Path | What |
|---|---|
| `langfuse_platform/` | The stack `Langfuse-Host` |
| `deploy/` | What the VM runs: `compose.yaml`, `Caddyfile`, `deploy.sh` |
| `tests/` | `uv run pytest` |

Runbook: `docs/runbooks/langfuse-host.md`.
