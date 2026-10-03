# PROTOTYPE (#29): forwarding the learner JWT API → agent → MCP

Throwaway code that answered one question; it lives only on the `prototype/29-jwt-forwarding` branch.
The decision it validated is ADR 0006 on `main`.

**Question:** how does the learner's Keycloak JWT travel API → LangGraph agent (runtime context, never state or
prompt) → MCP server (HTTP header), and how does the MCP server validate it, in Docker Compose? Do unauthenticated
calls get 401, and do tokens stay out of traces? (PRD §9.3, US-1, US-12)

## Run

```bash
docker compose up -d                                   # pgvector, Keycloak, LocalStack
docker compose -f compose.yaml -f backend/prototypes/jwt_forwarding_29/compose.yaml \
  up -d --build --no-deps proto-mcp proto-agent proto-api
cd backend && uv run python prototypes/jwt_forwarding_29/run.py   # prints each hop, then 14 PASS/FAIL checks
```

`run.py` signs in like the web app (auth code + PKCE on `smart-tutor-web`, `learner@example.com` and
`learner2@example.com`), so the tokens are the real ones the API will receive.

## Result (2026-10-04): 14/14 checks pass

| Check | Result |
|---|---|
| API → agent → MCP with a real learner token | 200; MCP reads `sub` from the verified token, not from tool arguments |
| Second learner | MCP sees learner 2's own `sub` |
| Token in LangSmith payloads (real `LangChainTracer`, recording client) | absent (full token and signature) |
| Token in LangGraph checkpoint | absent |
| Positive control `?leak=1` (token put in state) | detected in traces and checkpoint, so the check is not vacuous |
| API / agent / MCP without token, tampered signature | 401 each; MCP sends `WWW-Authenticate: Bearer error="invalid_token"` |

## What we learned

1. **Runtime context works as the carrier.** `StateGraph(State, context_schema=AgentContext)`, `graph.ainvoke(..., context=AgentContext(access_token=...))`, node reads `runtime.context.access_token`. LangSmith receives only state inputs/outputs and `configurable` metadata (`thread_id`); the runtime object is not serialized, and the checkpointer stores state only.
2. **The token must never be a node input, a state key, or an argument of a `@traceable`/tool function**: those are traced. The positive control shows how easily it leaks.
3. **MCP SDK 2.x has the hook we need:** `MCPServer(token_verifier=..., auth=AuthSettings(issuer_url=..., resource_server_url=..., validate_token_resource=False))`. Its `RequireAuthMiddleware` answers 401 before any MCP handling; tools read the caller with `get_access_token().subject`. Our verifier checks `aud=rag-mcp`, so `validate_token_resource=False`.
4. **Client side:** `mcp.Client(streamable_http_client(url, http_client=httpx2.AsyncClient(headers={"Authorization": ...})))`. Note the SDK uses `httpx2`, not `httpx`. One client per request because the header is per learner.
5. **Issuer ≠ JWKS URL in Compose.** Tokens say `iss=http://localhost:8080/realms/smart-tutor` (the browser's URL). Inside a container, `localhost:8080` is the container itself (the agent answered 404 to its own JWKS fetch). Verifiers need a separate `keycloak_jwks_url` (`http://keycloak:8080/.../certs` in Compose; defaults to `<issuer>/protocol/openid-connect/certs` in EKS).
6. **Audiences:** Keycloak's tokens for `smart-tutor-web` carry `aud=[smart-tutor-api, rag-mcp, account]`. API and agent verify `smart-tutor-api`; MCP verifies `rag-mcp`. One token, no exchange.
7. **Test login gotcha:** Keycloak 26 marks login cookies `Secure`; httpx drops them on `http://localhost`, so headless logins must forward `Set-Cookie` by hand.
8. A tool returning a bare `dict` has no output schema; the result comes back as JSON text, not `structured_content`. Real tools should return typed models.
