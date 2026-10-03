"""PROTOTYPE (#29) — throwaway. API stand-in: validates the learner JWT, forwards the same token to the agent."""

import os
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from verify import Unauthorized, bearer, verify

AGENT_URL = os.environ.get("PROTO_AGENT_URL", "http://agent:8080")

app = FastAPI(title="api-prototype")


@app.post("/ask")
async def ask(body: dict[str, Any], request: Request, authorization: str | None = Header(None)) -> Any:
    try:
        token = bearer(authorization)
        claims = await verify(token, audience="smart-tutor-api")
    except Unauthorized as e:
        print(f"[api] 401: {e}", flush=True)
        raise HTTPException(401, "unauthorized") from e
    print(f"[api] verified sub={claims['sub']} aud={claims['aud']}; forwarding to agent", flush=True)
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(
            f"{AGENT_URL}/invoke",
            params=dict(request.query_params),
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code != 200:
        raise HTTPException(r.status_code, r.text)
    return {"api_sub": claims["sub"], **r.json()}
