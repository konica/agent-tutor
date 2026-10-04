# 0007. Forward the learner JWT through LangGraph runtime context; Keycloak validates it on every hop

- Status: accepted
- Date: 2026-10-04

## Context

PRD §9.3 says the API forwards the learner's Keycloak access token to the agent, the agent attaches it to every MCP request (HTTP header, runtime context, never the prompt), and the MCP server validates it and reads `sub`. Unauthenticated calls to the API, agent, or MCP server return 401, and tokens never appear in prompts, logs, or traces. It does not say how LangGraph carries the token, how the MCP server hooks validation in, or how a service decides a token is valid.

Wayfinder ticket #29 prototyped the path in Docker Compose (branch `prototype/29-jwt-forwarding`, `backend/prototypes/jwt_forwarding_29/`): stand-in API, agent, and MCP services, with real tokens obtained through the `smart-tutor-web` client for two learners. The first round validated tokens locally (signature against the realm JWKS). Review of this ADR asked for Keycloak itself to verify the token, so the second round validates by **token introspection** (RFC 7662). All 18 checks passed:

- Each learner's `sub` reached the MCP tool from the validated token.
- The API, agent, and MCP server each answered 401 to a missing token and to a tampered one.
- After an admin logout of learner 1, their token was still correctly signed and unexpired, so a local JWKS check accepted it. The API and the MCP server rejected it with 401, and learner 2 was unaffected.
- The token was absent from the payloads LangSmith's `LangChainTracer` sends and from the LangGraph checkpoint.
- A positive control that put the token in state was caught in both.

## Decision

- **One token end to end, no token exchange.** Keycloak access tokens for `smart-tutor-web` carry `aud = [smart-tutor-api, rag-mcp]`.
- **Keycloak validates the token on every hop, by introspection.** Each service sends the token to `<realm>/protocol/openid-connect/token/introspect`, authenticated as its own confidential client: the API and the agent as `smart-tutor-api`, the MCP server as `rag-mcp`. A token is accepted only if:
  - the response says `active: true`;
  - `aud` contains the service's audience (`smart-tutor-api`, or `rag-mcp` for the MCP server);
  - `iss` equals the configured issuer;
  - `sub` is present.

  Anything else, including Keycloak being unreachable, is a 401. One verifier lives in `shared.adapters.auth` and takes the client and audience as parameters.
- **The public issuer and the internal Keycloak URL are separate settings.** The issuer is the URL the browser uses (`http://localhost:8080/realms/smart-tutor` in Compose). Services call Keycloak at an internal URL (`http://keycloak:8080/realms/smart-tutor` in Compose). Elsewhere, the internal URL defaults to the issuer. In Compose, Keycloak pins its hostname (`KC_HOSTNAME=http://localhost:8080`, `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true`). Without that, it derives the issuer from the request's host and reports every browser-issued token as `active: false` to containers.
- **API → agent:** the API forwards the same token in the `Authorization` header. The agent validates it again (the network policy is not the only gate).
- **Inside the agent, the token lives only in LangGraph runtime context.** The graph declares `context_schema` with an `access_token` field. Each request passes `context=...` to `invoke`/`stream`, and nodes read `runtime.context`. The token is never a state key, a node or tool input, a prompt variable, an argument of a traced function, or a `configurable` value. LangSmith records state and `configurable` metadata, and the checkpointer stores state, so the token would leak through any of those.
- **Agent → MCP:** the `tutoring` `Retriever` adapter builds an `httpx2.AsyncClient` per request with the `Authorization` header and passes it to `mcp.Client(streamable_http_client(url, http_client=...))`. The MCP SDK uses `httpx2`, not `httpx`.
- **The MCP server plugs introspection into the SDK's hook.** `MCPServer(token_verifier=<our verifier>, auth=AuthSettings(issuer_url=..., resource_server_url=..., validate_token_resource=False))`. `validate_token_resource` is false because our verifier checks `aud` itself. The SDK's `RequireAuthMiddleware` answers 401 with `WWW-Authenticate: Bearer` before any MCP handling. Tools take no user id; they read the caller with `get_access_token().subject` and pass it to `can_read`.

### Considered and rejected

- **Local signature check against the realm JWKS** (round 1 of the prototype): no network call per request, and Keycloak can be down briefly without blocking chat. But a logged-out or revoked token keeps working until it expires (up to 15 minutes), on every hop.
- **Introspection at the API only, JWKS downstream:** cheaper, but the MCP server, which enforces `can_read`, would then trust a token Keycloak may already have revoked.

## Consequences

- Logout, session revocation, and disabled users take effect on the next request, not at token expiry.
- **Keycloak is on the request path.** One question costs 5 introspections in the prototype: one each in the API and the agent, and 3 in the MCP server, because the SDK middleware checks each HTTP request of an MCP session (initialize, initialized notification, tool call). Each takes about 6–9 ms inside Compose (20–38 ms cold), roughly 30–45 ms per question. Keycloak availability becomes chat availability; production Keycloak needs to be sized and monitored for this.
- If that cost matters, the first lever is reusing one MCP session per turn, then a short cache keyed by a hash of the token (seconds, never longer than the token's `exp`). Neither is built until a measurement asks for it.
- The realm turns `smart-tutor-api` and `rag-mcp` from bearer-only into confidential clients with secrets (no login flows, no service accounts). Their secrets come from Secrets Manager in EKS and from `.env` locally.
- `Settings` gains the internal Keycloak URL and per-service client credentials. Compose sets them for `api`, `agent`, and `mcp`, and pins Keycloak's hostname.
- `shared.adapters.auth` needs no JWT library for validation; it is an `httpx` call. `pyjwt` stays only if something else needs it.
- A test that can see trace payloads (a LangSmith client that records instead of sending) guards "tokens never reach traces", with a positive control so the check cannot pass vacuously.
- Tests and scripts that sign in headlessly against Compose Keycloak must forward its `Secure` cookies by hand over `http://localhost`.
- MCP tools should return typed models so results arrive as `structured_content`; a bare `dict` comes back as JSON text.
- Not covered by the prototype: a token that expires during a streamed turn (access tokens last 15 minutes). Because every hop now asks Keycloak, a search late in a turn fails if the token expired after the API accepted it. The walking skeleton should decide whether the web app refreshes before asking or the agent turns that failure into a "sign in again" message. *Decided in #31:* the web app calls `keycloak.updateToken(60)` before every API call, and a 401 after that shows "Please sign in again".
