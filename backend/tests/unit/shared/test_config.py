import pytest
from pydantic import ValidationError

from smart_tutor.shared.config import Settings

ISSUER = "http://localhost:10401/realms/smart-tutor"


def test_introspection_url_defaults_to_the_issuer() -> None:
    s = Settings(keycloak_issuer=ISSUER, keycloak_internal_url=None)
    assert s.keycloak_introspection_url == f"{ISSUER}/protocol/openid-connect/token/introspect"


def test_introspection_url_uses_the_internal_url_when_set() -> None:
    s = Settings(keycloak_issuer=ISSUER, keycloak_internal_url="http://keycloak:8080/realms/smart-tutor/")
    assert s.keycloak_introspection_url == (
        "http://keycloak:8080/realms/smart-tutor/protocol/openid-connect/token/introspect"
    )


def test_client_secret_is_not_printed() -> None:
    s = Settings(keycloak_client_secret="local-api-secret")
    assert "local-api-secret" not in repr(s)


@pytest.mark.parametrize("seconds", [0, -1])
def test_extraction_timeout_must_be_positive(seconds: int) -> None:
    # 0 would fail every PDF at once: the worker would stop the parser before it has started.
    with pytest.raises(ValidationError, match="extraction_timeout_seconds"):
        Settings(extraction_timeout_seconds=seconds)
