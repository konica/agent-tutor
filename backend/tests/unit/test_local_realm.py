"""The Compose realm matches ADR 0007: resource clients are confidential so they can introspect."""

import json
from pathlib import Path
from typing import Any

REALM = Path(__file__).parents[3] / "local" / "keycloak" / "realm-smart-tutor.json"


def _realm() -> dict[str, Any]:
    return json.loads(REALM.read_text(encoding="utf-8"))


def _client(client_id: str) -> dict[str, Any]:
    return next(c for c in _realm()["clients"] if c["clientId"] == client_id)


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


def test_visitors_sign_up_and_verify_their_email() -> None:
    realm = _realm()
    assert realm["registrationAllowed"] is True
    assert realm["verifyEmail"] is True
    assert realm["smtpServer"]["host"] == "mailpit"
    assert realm["smtpServer"]["from"]


def test_new_users_get_the_learner_role() -> None:
    realm = _realm()
    roles = {r["name"]: r for r in realm["roles"]["realm"]}
    default = roles[realm["defaultRole"]["name"]]
    assert "learner" in default["composites"]["realm"]
    assert {"offline_access", "uma_authorization"} <= roles.keys()


def test_seeded_users_skip_verification() -> None:
    users = _realm()["users"]
    assert users
    assert all(u["emailVerified"] is True for u in users)
