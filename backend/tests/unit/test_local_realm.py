"""The Compose realm matches ADR 0007: resource clients are confidential so they can introspect."""

import json
from pathlib import Path
from typing import Any

REALM = Path(__file__).parents[3] / "local" / "keycloak" / "realm-smart-tutor.json"


def _client(client_id: str) -> dict[str, Any]:
    realm = json.loads(REALM.read_text(encoding="utf-8"))
    return next(c for c in realm["clients"] if c["clientId"] == client_id)


def test_resource_clients_are_confidential_without_login_flows() -> None:
    for client_id in ("smart-tutor-api", "rag-mcp"):
        c = _client(client_id)
        assert c["publicClient"] is False
        assert c["bearerOnly"] is False
        assert c["clientAuthenticatorType"] == "client-secret"
        assert c["secret"]
        assert c["standardFlowEnabled"] is False
        assert c["directAccessGrantsEnabled"] is False
        assert c["serviceAccountsEnabled"] is False


def test_web_client_can_log_out_back_to_the_app() -> None:
    c = _client("smart-tutor-web")
    assert c["publicClient"] is True
    assert c["attributes"]["pkce.code.challenge.method"] == "S256"
    assert c["attributes"]["post.logout.redirect.uris"] == "http://localhost:10453/*"
