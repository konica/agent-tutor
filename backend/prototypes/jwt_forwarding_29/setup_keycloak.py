"""PROTOTYPE (#29) — throwaway. Makes smart-tutor-api and rag-mcp confidential clients with known secrets in the
LOCAL realm, so they can call token introspection. Idempotent. Undo with `docker compose down -v`.

    cd backend && uv run python prototypes/jwt_forwarding_29/setup_keycloak.py
"""

import httpx

KC = "http://localhost:8080"
SECRETS = {"smart-tutor-api": "proto-api-secret", "rag-mcp": "proto-mcp-secret"}

admin = httpx.post(
    f"{KC}/realms/master/protocol/openid-connect/token",
    data={"grant_type": "password", "client_id": "admin-cli", "username": "admin", "password": "admin"},
).json()["access_token"]
h = {"Authorization": f"Bearer {admin}"}

for client_id, secret in SECRETS.items():
    c = httpx.get(f"{KC}/admin/realms/smart-tutor/clients", params={"clientId": client_id}, headers=h).json()[0]
    c.update(
        publicClient=False,
        bearerOnly=False,
        clientAuthenticatorType="client-secret",
        secret=secret,
        standardFlowEnabled=False,
        directAccessGrantsEnabled=False,
        serviceAccountsEnabled=False,
    )
    r = httpx.put(f"{KC}/admin/realms/smart-tutor/clients/{c['id']}", json=c, headers=h)
    print(client_id, r.status_code)
