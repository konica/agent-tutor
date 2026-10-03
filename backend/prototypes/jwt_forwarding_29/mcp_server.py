"""PROTOTYPE (#29) — throwaway. RAG MCP server stand-in: validates the forwarded JWT via the SDK's TokenVerifier hook.

The tool takes no user id: `sub` comes only from the verified token (get_access_token()).
"""

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from verify import ISSUER, Unauthorized, verify


class KeycloakVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = verify(token, audience="rag-mcp")
        except Unauthorized as e:
            print(f"[mcp] rejected token: {e}", flush=True)
            return None  # -> 401 from RequireAuthMiddleware
        return AccessToken(
            token=token,
            client_id=claims.get("azp", ""),
            scopes=claims.get("scope", "").split(),
            expires_at=claims["exp"],
            subject=claims["sub"],
            claims={"iss": claims["iss"]},
        )


mcp = MCPServer(
    "rag-mcp-prototype",
    token_verifier=KeycloakVerifier(),
    auth=AuthSettings(
        issuer_url=ISSUER,
        resource_server_url="http://mcp:8000/mcp",
        validate_token_resource=False,  # our verifier checks aud=rag-mcp itself
    ),
)


@mcp.tool()
def search(query: str, subject_ids: list[str]) -> dict:
    token = get_access_token()
    assert token is not None
    print(f"[mcp] search by sub={token.subject} query={query!r} subjects={subject_ids}", flush=True)
    return {"sub": token.subject, "query": query, "subject_ids": subject_ids, "chunks": []}


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
