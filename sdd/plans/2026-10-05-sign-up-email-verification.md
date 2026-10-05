# Sign Up with Email Verification in Compose Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new visitor registers on Keycloak's page in Compose, receives a verification email caught by Mailpit, verifies, and lands in the app with the `learner` role (#47, PRD §8 US-1).

**Architecture:** Configuration only. Add a Mailpit service to `compose.yaml` (SMTP on the Compose network, web UI on the next free dependency port, 10403). The realm turns on `verifyEmail` and points `smtpServer` at `mailpit:1025`. Keycloak blocks token issuance until the `VERIFY_EMAIL` required action is done, so the app needs no change. New users already get `learner` through `default-roles-smart-tutor`; seeded users already have `emailVerified: true`. A unit test pins these realm settings.

**Tech Stack:** Docker Compose, Keycloak 26.3 realm import JSON, Mailpit (`axllent/mailpit`), pytest.

**Spec:** GitHub issue #47 (parent #8, PRD §8 US-1). No design doc: the slice needs no design (theme is the next slice).

## Global Constraints

- Host ports: dependency services count up from 10400; Mailpit's web UI takes 10403. SMTP stays on the Compose network (only Keycloak, which always runs in Docker, sends mail).
- The realm keeps the built-in roles `offline_access` and `uma_authorization`.
- The realm imports only on a fresh volume: docs say to run `docker compose down -v` after this change.
- Out of scope: Keycloak theme; production SMTP (M4).

## Review Focus

- Existing developer volumes: the realm doesn't re-import, so sign-up won't send mail until `docker compose down -v`. Docs must say so (README and AGENTS.md).
- Verification link host: links must point at `http://localhost:10401` (already pinned by `KC_HOSTNAME`), not `keycloak:8080`. Verified manually in Task 1 Step 7.
- Seeded users: must sign in with no verify step, so the test checks every seeded user has `emailVerified: true`.
- `learner` role for new users: the test checks `defaultRole` resolves to a composite that contains `learner`.
- Mailpit down: Keycloak shows an email error page on registration; acceptable locally, no handling needed.

---

### Task 1: Mailpit, realm email verification, realm test, docs

**Files:**
- Modify: `backend/tests/unit/test_local_realm.py`
- Modify: `local/keycloak/realm-smart-tutor.json`
- Modify: `compose.yaml` (new `mailpit` service after `localstack`; header comment)
- Modify: `README.md` (quick start comment, Keycloak line, ports table)
- Modify: `AGENTS.md` (Local development bullets)
- Modify: `.env.example` (comment documenting the Mailpit UI)

**Interfaces:**
- Consumes: nothing.
- Produces: Compose service `mailpit` (SMTP `mailpit:1025`, UI `http://localhost:10403`).

- [ ] **Step 1: Write the failing test** — append to `backend/tests/unit/test_local_realm.py`:

```python
def _realm() -> dict[str, Any]:
    return json.loads(REALM.read_text(encoding="utf-8"))


def test_visitors_sign_up_and_verify_their_email() -> None:
    realm = _realm()
    assert realm["registrationAllowed"] is True
    assert realm["verifyEmail"] is True
    assert realm["smtpServer"]["host"] == "mailpit"
    assert realm["smtpServer"]["from"]


def test_new_users_get_the_learner_role() -> None:
    realm = _realm()
    roles = {r["name"]: r for r in realm["roles"]["realm"]}
    default = roles[realm["defaultRole"]["name"]]
    assert "learner" in default["composites"]["realm"]
    assert {"offline_access", "uma_authorization"} <= roles.keys()


def test_seeded_users_skip_verification() -> None:
    users = _realm()["users"]
    assert users
    assert all(u["emailVerified"] is True for u in users)
```

Also make `_client` use `_realm()` (define `_realm` above `_client`).

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_local_realm.py -v`
Expected: `test_visitors_sign_up_and_verify_their_email` FAILS (`verifyEmail` is false, no `smtpServer`); the other new tests pass already (they pin existing behavior).

- [ ] **Step 3: Update the realm** — in `local/keycloak/realm-smart-tutor.json` set `"verifyEmail": true` and add after `"accessTokenLifespan": 900,`:

```json
  "smtpServer": {
    "host": "mailpit",
    "port": "1025",
    "from": "no-reply@smart-tutor.local",
    "fromDisplayName": "Smart Tutor",
    "auth": "false",
    "ssl": "false",
    "starttls": "false"
  },
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/test_local_realm.py -v`
Expected: all PASS.

- [ ] **Step 5: Add Mailpit to Compose** — in `compose.yaml`, header line 2 becomes `#   docker compose up -d                 # dependencies only: pgvector, Keycloak, LocalStack, Mailpit`; add after the `localstack` service:

```yaml
  # Catches Keycloak's emails (sign-up verification). Web UI at http://localhost:10403; SMTP stays on the network.
  mailpit:
    image: axllent/mailpit:v1.27
    ports: ["10403:8025"]
```

And add `mailpit: {condition: service_started}` to `keycloak.depends_on`.

- [ ] **Step 6: Update docs**
  - `README.md`: quick start `make up` comment → `# pgvector, Keycloak (realm imported), LocalStack, Mailpit`; after the Keycloak admin console line add: `Sign up from the app's sign-in page: Keycloak sends the verification email to Mailpit, http://localhost:10403. After pulling a realm change, run `docker compose down -v` so the realm re-imports.`; ports table row `| Mailpit (email UI) | 10403 | Docker | Docker |` after LocalStack; Option B `make up` comment gets `, Mailpit`.
  - `AGENTS.md` Local development: first bullet lists `LocalStack (:10402), and Mailpit (:10403, web UI for emails Keycloak sends)`.
  - `.env.example`: under `# Local dependency services`, add `# Mailpit catches Keycloak's emails (sign-up verification): http://localhost:10403`.

- [ ] **Step 7: Verify in Compose (manual)**

```bash
docker compose down -v && docker compose up -d
```
Then: `docker compose ps` shows mailpit running; `curl -s localhost:10403/api/v1/info` returns JSON; `curl -s localhost:10401/realms/smart-tutor/.well-known/openid-configuration` returns JSON (realm imported). Optionally register through the browser and see the email in Mailpit.

- [ ] **Step 8: Run checks and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest
git add compose.yaml local/keycloak/realm-smart-tutor.json backend/tests/unit/test_local_realm.py README.md AGENTS.md .env.example
git commit -m "Verify new users' email in Compose with Mailpit"
```
