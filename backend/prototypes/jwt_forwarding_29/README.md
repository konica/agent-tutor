# PROTOTYPE (#29): forwarding the learner JWT API → agent → MCP

Throwaway code that answered one question; it lives only on the `prototype/29-jwt-forwarding` branch.
The decision it validated is ADR 0007 (PR #37).

**Question:** how does the learner's Keycloak JWT travel API → LangGraph agent (runtime context, never state or
prompt) → MCP server (HTTP header), and how does the MCP server validate it, in Docker Compose? Do unauthenticated
calls get 401, and do tokens stay out of traces? (PRD §9.3, US-1, US-12)

**Round 2 (PR #37 review: "verify the token with Keycloak"):** every service now validates by calling Keycloak's
token introspection endpoint instead of checking the signature locally against the JWKS. Round 1 (local JWKS) is
commit `403e833`.

## Run

```bash
docker compose up -d                                   # pgvector, Keycloak, LocalStack
docker compose -f compose.yaml -f backend/prototypes/jwt_forwarding_29/compose.yaml \
  up -d --build --no-deps keycloak proto-mcp proto-agent proto-api   # recreates Keycloak with KC_HOSTNAME
cd backend
uv run python prototypes/jwt_forwarding_29/setup_keycloak.py   # secrets for smart-tutor-api and rag-mcp (local realm)
uv run python prototypes/jwt_forwarding_29/run.py              # prints each hop, then 18 PASS/FAIL checks
```

`run.py` signs in like the web app (auth code + PKCE on `smart-tutor-web`, `learner@example.com` and
`learner2@example.com`), so the tokens are the real ones the API will receive. It ends by logging learner 1 out.
Undo the Keycloak changes with `docker compose down -v` (or `up -d keycloak` from `main` for the hostname only).

## Result (2026-10-04): 18/18 checks pass

| Check | Result |
|---|---|
| API → agent → MCP with a real learner token | 200; MCP reads `sub` from the introspected token, not from tool arguments |
| Second learner | MCP sees learner 2's own `sub` |
| Token in LangSmith payloads (real `LangChainTracer`, recording client) | absent (full token and signature) |
| Token in LangGraph checkpoint | absent |
| Positive control `?leak=1` (token put in state) | detected in traces and checkpoint, so the check is not vacuous |
| API / agent / MCP without token, tampered signature | 401 each; MCP sends `WWW-Authenticate: Bearer error="invalid_token"` |
| Learner 1 logged out (admin), token unexpired | a local JWKS check still accepts it; API and MCP answer 401; learner 2 unaffected |

## What we learned

1. **Runtime context works as the carrier.** `StateGraph(State, context_schema=AgentContext)`, `graph.ainvoke(..., context=AgentContext(access_token=...))`, node reads `runtime.context.access_token`. LangSmith receives only state inputs/outputs and `configurable` metadata (`thread_id`); the runtime object is not serialized, and the checkpointer stores state only.
2. **The token must never be a node input, a state key, or an argument of a `@traceable`/tool function**: those are traced. The positive control shows how easily it leaks.
3. **MCP SDK 2.x has the hook we need:** `MCPServer(token_verifier=..., auth=AuthSettings(issuer_url=..., resource_server_url=..., validate_token_resource=False))`. Its `RequireAuthMiddleware` answers 401 before any MCP handling; tools read the caller with `get_access_token().subject`. Our verifier checks `aud=rag-mcp`, so `validate_token_resource=False`. The hook is async, so introspection fits it directly.
4. **Client side:** `mcp.Client(streamable_http_client(url, http_client=httpx2.AsyncClient(headers={"Authorization": ...})))`. Note the SDK uses `httpx2`, not `httpx`. One client per request because the header is per learner.
5. **Introspection (RFC 7662):** `POST <internal-realm-url>/protocol/openid-connect/token/introspect` with the service's client credentials (HTTP Basic). Accept only `active: true`, `aud` containing the service's audience, `iss` equal to the public issuer, and a `sub`. The API and agent use the `smart-tutor-api` client; the MCP server uses `rag-mcp`. Both must become confidential clients with secrets (today they are bearer-only).
6. **Revocation is the gain.** After an admin logout, the token is still correctly signed and unexpired, so a JWKS check accepts it for up to 15 minutes; introspection rejects it at once on every hop.
7. **Cost:** one question = 5 introspections: API 1, agent 1, MCP 3 (the SDK middleware checks each HTTP request of the MCP session: initialize, initialized notification, tool call). Each takes about 6–9 ms inside the Compose network (20–38 ms on a cold first call), so roughly 30–45 ms per question. Keycloak becomes a hard dependency on every request.
8. **Compose: Keycloak must pin its hostname.** Without `KC_HOSTNAME`, Keycloak derives the issuer from the request's host, so introspecting a `localhost:8080` token through `keycloak:8080` silently returns `200 {"active": false}`. With `KC_HOSTNAME=http://localhost:8080` and `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true`, containers call `keycloak:8080` and get `active: true`. Services need the public issuer and an internal Keycloak URL as separate settings.
9. **Audiences:** Keycloak's tokens for `smart-tutor-web` carry `aud=[smart-tutor-api, rag-mcp, account]`. One token end to end, no exchange.
10. **Test login gotcha:** Keycloak 26 marks login cookies `Secure`; httpx drops them on `http://localhost`, so headless logins must forward `Set-Cookie` by hand.
11. A tool returning a bare `dict` has no output schema; the result comes back as JSON text, not `structured_content`. Real tools should return typed models.
