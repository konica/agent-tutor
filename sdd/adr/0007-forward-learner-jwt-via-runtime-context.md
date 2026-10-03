# 0007. Forward the learner JWT through LangGraph runtime context and the MCP SDK's token verifier

- Status: accepted
- Date: 2026-10-04

## Context

PRD §9.3 says the API forwards the learner's Keycloak access token to the agent, the agent attaches it to every MCP request (HTTP header, runtime context, never the prompt), and the MCP server validates it and reads `sub`. Unauthenticated calls to the API, agent, or MCP server return 401, and tokens never appear in prompts, logs, or traces. It does not say how LangGraph carries the token, how the MCP server hooks validation in, or how containers verify tokens whose issuer is the browser's URL.

Wayfinder ticket #29 prototyped the path in Docker Compose (branch `prototype/29-jwt-forwarding`, `backend/prototypes/jwt_forwarding_29/`): stand-in API, agent, and MCP services, with real tokens obtained through the `smart-tutor-web` client for two learners. All 14 checks passed:

- Each learner's `sub` reached the MCP tool from the verified token.
- The API, agent, and MCP server each answered 401 to a missing token and to a tampered one.
- The token was absent from the payloads LangSmith's `LangChainTracer` sends and from the LangGraph checkpoint.
- A positive control that put the token in state was caught in both.

## Decision

- **One token end to end, no token exchange.** Keycloak access tokens for `smart-tutor-web` carry `aud = [smart-tutor-api, rag-mcp]`. The API and the agent verify audience `smart-tutor-api`, and the MCP server verifies `rag-mcp`. Every verifier checks the RS256 signature against the realm JWKS, plus `iss` and `exp`, and requires `sub`. One verifier lives in `shared.adapters.auth` and takes the audience as a parameter.
- **The issuer and the JWKS URL are separate settings.** The issuer is the URL the browser uses, which is `http://localhost:8080/realms/smart-tutor` in Compose. Inside a container, `localhost` is the container itself, so verifiers fetch keys from `keycloak_jwks_url`. In Compose it is `http://keycloak:8080/realms/smart-tutor/protocol/openid-connect/certs`. Elsewhere it defaults to `<issuer>/protocol/openid-connect/certs`.
- **API → agent:** the API forwards the same token in the `Authorization` header. The agent verifies it again (the network policy is not the only gate).
- **Inside the agent, the token lives only in LangGraph runtime context.** The graph declares `context_schema` with an `access_token` field. Each request passes `context=...` to `invoke`/`stream`, and nodes read `runtime.context`. The token is never a state key, a node or tool input, a prompt variable, an argument of a traced function, or a `configurable` value. LangSmith records state and `configurable` metadata, and the checkpointer stores state, so the token would leak through any of those.
- **Agent → MCP:** the `tutoring` `Retriever` adapter builds an `httpx2.AsyncClient` per request with the `Authorization` header and passes it to `mcp.Client(streamable_http_client(url, http_client=...))`. The MCP SDK uses `httpx2`, not `httpx`.
- **The MCP server validates with the SDK's hook.** `MCPServer(token_verifier=<our verifier>, auth=AuthSettings(issuer_url=..., resource_server_url=..., validate_token_resource=False))`. `validate_token_resource` is false because our verifier checks `aud` itself. The SDK's `RequireAuthMiddleware` answers 401 with `WWW-Authenticate: Bearer` before any MCP handling. Tools take no user id; they read the caller with `get_access_token().subject` and pass it to `can_read`.

## Consequences

- `Settings` gains `keycloak_jwks_url`, and Compose sets it, along with the issuer, for `api`, `agent`, and `mcp`. The MCP server needs its own audience setting (`rag-mcp`).
- `shared.adapters.auth` uses PyJWT's `PyJWKClient` (already a dependency) with a key cache; no Keycloak SDK.
- A test that can see trace payloads (a LangSmith client that records instead of sending) guards "tokens never reach traces", with a positive control so the check cannot pass vacuously.
- Tests and scripts that sign in headlessly against Compose Keycloak must forward its `Secure` cookies by hand over `http://localhost`.
- MCP tools should return typed models so results arrive as `structured_content`; a bare `dict` comes back as JSON text.
- Not covered by the prototype: a token that expires during a streamed turn (access tokens last 15 minutes). The walking skeleton should decide whether the MCP server tolerates that or the web app refreshes before asking.
