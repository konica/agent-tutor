"""PROTOTYPE (#29) — throwaway driver. Logs in like the web app (auth code + PKCE on smart-tutor-web),
then walks the API -> agent -> MCP path and the 401 cases, printing what each hop saw.

    cd backend && uv run python prototypes/jwt_forwarding_29/run.py
"""

import base64
import hashlib
import html
import json
import re
import secrets
from urllib.parse import parse_qs, urlparse

import httpx

KC = "http://localhost:8080/realms/smart-tutor/protocol/openid-connect"
REDIRECT = "http://localhost:5173/callback"
API, AGENT, MCP = "http://localhost:9001", "http://localhost:9002", "http://localhost:9000/mcp"
results: list[tuple[str, bool]] = []


def login(user: str, password: str) -> str:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    with httpx.Client(follow_redirects=False) as c:
        page = c.get(
            f"{KC}/auth",
            params={
                "client_id": "smart-tutor-web",
                "redirect_uri": REDIRECT,
                "response_type": "code",
                "scope": "openid",
                "state": "s",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        action = html.unescape(re.search(r'action="([^"]+)"', page.text).group(1))
        # Keycloak 26 marks its cookies Secure; httpx drops those on http://localhost, so send them by hand.
        cookie = "; ".join(h.split(";", 1)[0] for h in page.headers.get_list("set-cookie"))
        r = c.post(
            action,
            data={"username": user, "password": password, "credentialId": ""},
            headers={"Cookie": cookie},
        )
        code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
        tok = c.post(
            f"{KC}/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "smart-tutor-web",
                "code": code,
                "redirect_uri": REDIRECT,
                "code_verifier": verifier,
            },
        )
        return tok.json()["access_token"]


def claims(token: str) -> dict:
    body = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


def check(name: str, ok: bool, detail: object = "") -> None:
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


def mcp_initialize(headers: dict[str, str]) -> httpx.Response:
    return httpx.post(
        MCP,
        headers={"Accept": "application/json, text/event-stream", **headers},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "p", "version": "0"},
            },
        },
    )


t1 = login("learner@example.com", "learner")
t2 = login("learner2@example.com", "learner2")
c1 = claims(t1)
print("token claims:", {k: c1[k] for k in ("iss", "aud", "azp", "sub")}, "\n")

ask = {"question": "What is entropy?", "subject_ids": ["subj-1"]}
r = httpx.post(f"{API}/ask", json=ask, headers={"Authorization": f"Bearer {t1}"}, timeout=60)
print("happy path response:", json.dumps(r.json(), indent=2, default=str)[:2500], "\n")
body = r.json()
check("API -> agent -> MCP returns 200", r.status_code == 200)
check("MCP saw the learner's sub from the token", body["state"]["mcp_result"].get("sub") == c1["sub"])
check("token absent from LangSmith trace payloads", body["token_in_traces"] is False, f"runs={body['trace_runs']}")
check("token signature absent from traces", body["token_signature_in_traces"] is False)
check("token absent from checkpoint (state)", body["token_in_checkpoint"] is False)

r2 = httpx.post(f"{API}/ask", json=ask, headers={"Authorization": f"Bearer {t2}"}, timeout=60).json()
check("second learner -> MCP sees their own sub", r2["state"]["mcp_result"]["sub"] == claims(t2)["sub"] != c1["sub"])

leak = httpx.post(f"{API}/ask?leak=1", json=ask, headers={"Authorization": f"Bearer {t1}"}, timeout=60).json()
check("positive control: token in state IS detected in traces", leak["token_in_traces"] is True)
check("positive control: token in state IS detected in checkpoint", leak["token_in_checkpoint"] is True)

tampered = t1[:-4] + ("AAAA" if not t1.endswith("AAAA") else "BBBB")
check("API without token -> 401", httpx.post(f"{API}/ask", json=ask).status_code == 401)
r = httpx.post(f"{API}/ask", json=ask, headers={"Authorization": f"Bearer {tampered}"})
check("API with tampered token -> 401", r.status_code == 401)
check("agent without token -> 401", httpx.post(f"{AGENT}/invoke", json=ask).status_code == 401)
r = mcp_initialize({})
check("MCP without token -> 401", r.status_code == 401, r.headers.get("www-authenticate"))
check("MCP with tampered token -> 401", mcp_initialize({"Authorization": f"Bearer {tampered}"}).status_code == 401)
check("MCP with valid token -> 200", mcp_initialize({"Authorization": f"Bearer {t1}"}).status_code == 200)

print(f"\n{sum(ok for _, ok in results)}/{len(results)} checks passed")
raise SystemExit(0 if all(ok for _, ok in results) else 1)
