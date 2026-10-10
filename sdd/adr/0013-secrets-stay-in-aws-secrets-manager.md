# 0013. Secrets stay in AWS Secrets Manager; the repository holds no credential-shaped strings

- Status: proposed
- Date: 2026-10-09

## Context

GitGuardian's PR check failed on #166 (#148) with two "Generic Password" incidents in `deploy/on-premise/compose.yaml`. Both were the database URL `postgresql+psycopg://smart_tutor:${APP_DB_PASSWORD:?}@postgres:5432/smart_tutor`. The detector matches the `user:password@host` shape of a URL, and here the "password" was a Compose placeholder. No secret value was ever committed, so nothing needs rotating.

The product owner and the DevOps lead asked whether to adopt [SOPS](https://github.com/getsops/sops) and what else would prevent such findings. Today the secrets work like this in both deployment modes (ADR 0012):

- **Created by CDK.** CDK generates every secret in Secrets Manager: the database passwords, the Keycloak admin and client secrets, and the test learner. No person sees or types them.
- **Read at runtime.** Native-cloud reads them through External Secrets. On-premise, `deploy/on-premise/deploy.sh` reads them through the instance role into a root-only env file on the VM, and prints none of them.
- **Local development** uses fixed, non-secret values that are committed on purpose (`compose.yaml`, `local/keycloak/realm-smart-tutor.json`, `.env.example`).

## Options

| Option | Fits our case? |
|---|---|
| **SOPS** (CNCF Sandbox, v3.13.3). It encrypts the values in YAML, JSON, dotenv, or INI files with AWS KMS, age, PGP, or cloud KMS. Encrypted files are committed, and `sops exec-env` / `exec-file` hand the plaintext to a process. | **No, for now.** It moves secrets *into* the repository, which we don't need. People would have to author the values that CDK generates today, and a KMS key and its policy would be added. The ciphertext stays in history forever, so one leaked key decrypts every old version. Rotation becomes a commit plus a redeploy (`sops rotate` renews only the data key, not the secrets). Native-cloud would need a second path (`helm-secrets` or a SOPS-aware operator), giving two sources of truth. It also wouldn't have fixed this finding: the URL template would still have been in `compose.yaml`. |
| **SSM Parameter Store SecureString** instead of Secrets Manager | No. It is cheaper (standard parameters are free, against about $0.40 per secret per month, about $3 a month here), but CloudFormation can't create SecureString parameters or generate their values. That needs custom resources, and the saving is too small to justify them. |
| **Docker Compose `secrets:`** (files in `/run/secrets` instead of environment variables) | **Later, as hardening.** It keeps secrets out of `docker inspect`. Postgres reads `*_FILE`, and pydantic-settings reads a secrets directory, but Keycloak's `KC_*` options don't read files without a custom entrypoint. Revisit with the worker-isolation work (#149, #153). |
| **Silence the scanner** (`.gitguardian.yaml` `ignored_paths` or `ignored_detectors`) | No. Ignoring a path or the Generic Password detector would hide a real leak too. Only ignore a single reviewed match, by its SHA-256 (`secret.ignored_matches`), or mark it as a false positive in the dashboard. |
| **Keep Secrets Manager, and keep credential-shaped strings out of the repository** | **Yes.** |

## Decision

- **Secrets Manager stays the one home for secrets** in both modes. CDK generates them, and services read them at runtime. No secret value is committed, encrypted or not.
- **No credential-shaped strings in the repository.** Code that needs a URL with credentials builds it at runtime from the secret. On-premise, `deploy.sh` writes `APP_DATABASE_URL` into the root-only env file, and `compose.yaml` only references `${APP_DATABASE_URL}`. `infra/tests/test_host.py` fails when a `user:password@host` URL appears in `deploy/on-premise/`.
- **GitGuardian findings are triaged, never silenced in bulk.**
  - A placeholder or a local-development value is marked **false positive** in the dashboard, or ignored by its SHA-256 in `.gitguardian.yaml`, with a comment.
  - A real secret is **rotated first** (a new value in Secrets Manager, then a redeploy), and only then removed from the code.
  - Rewriting history is a last resort. Squash merges keep a PR's intermediate commits out of `main`.
- **Optional for developers:** run `ggshield secret scan pre-commit` as a pre-commit hook (it needs a GitGuardian API key), to catch findings before they are pushed.

## Consequences

- No new key, tool, or workflow. Rotating a secret is still "change it in Secrets Manager, redeploy". On-premise, the redeploy resets database role passwords and recreates the services that read them (`docs/runbooks/on-premise-deploy.md` §6).
- The #166 incidents stay in the GitGuardian dashboard (the flagged commit remains on the PR branch) until someone with dashboard access marks them as false positives.
- The committed local-development credentials are not secrets, but a scanner may flag them when a PR touches those lines. They are triaged as above.
- **Revisit SOPS** if secrets must be authored by people and versioned with the code, for example in a GitOps setup with Argo CD or Flux, or on a deployment target without Secrets Manager.
