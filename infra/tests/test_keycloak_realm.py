"""The production realm (keycloak chart) matches the local one in clients and roles, without test users (#57)."""

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[2]
LOCAL = json.loads((ROOT / "local/keycloak/realm-smart-tutor.json").read_text())
PROD_TEXT = (ROOT / "deploy/helm/smart-tutor/charts/keycloak/files/realm-smart-tutor.json").read_text()
PROD = json.loads(PROD_TEXT)


def clients(realm: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["clientId"]: c for c in realm["clients"]}


def test_production_realm_has_the_local_clients_roles_and_mappers() -> None:
    assert PROD["realm"] == LOCAL["realm"]
    assert PROD["roles"] == LOCAL["roles"]
    assert PROD["defaultRole"] == LOCAL["defaultRole"]
    assert clients(PROD).keys() == clients(LOCAL).keys()
    for client_id, local in clients(LOCAL).items():
        prod = clients(PROD)[client_id]
        for key in ("publicClient", "standardFlowEnabled", "directAccessGrantsEnabled", "protocolMappers"):
            assert prod.get(key) == local.get(key), (client_id, key)


def test_production_realm_has_no_literal_secrets_or_users() -> None:
    assert "users" not in PROD
    assert "smtpServer" not in PROD
    assert PROD["registrationAllowed"] is False  # until sign-up (#47) runs in production
    assert PROD["sslRequired"] == "external"
    secrets = {c["clientId"]: c.get("secret") for c in PROD["clients"] if not c["publicClient"]}
    assert secrets == {
        "smart-tutor-api": "${SMART_TUTOR_API_CLIENT_SECRET}",
        "rag-mcp": "${SMART_TUTOR_MCP_CLIENT_SECRET}",
    }


def test_production_urls_come_from_the_public_url_placeholder() -> None:
    web = clients(PROD)["smart-tutor-web"]
    assert web["redirectUris"] == ["${SMART_TUTOR_PUBLIC_URL}/*"]
    assert web["webOrigins"] == ["${SMART_TUTOR_PUBLIC_URL}"]
    assert web["attributes"]["post.logout.redirect.uris"] == "${SMART_TUTOR_PUBLIC_URL}/*"
    assert not re.search(r"localhost|cloudfront\.net", PROD_TEXT)
