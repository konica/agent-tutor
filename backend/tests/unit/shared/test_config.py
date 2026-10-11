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


def test_history_defaults() -> None:
    s = Settings()
    assert s.history_turns == 5
    assert s.history_answer_chars == 2000


@pytest.mark.parametrize(
    "overrides",
    [{"history_turns": 21}, {"history_turns": -1}, {"history_answer_chars": 8001}, {"history_answer_chars": 0}],
)
def test_history_settings_beyond_what_the_agent_accepts_stop_startup(overrides: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        Settings(**overrides)  # type: ignore[arg-type]


def test_client_secret_is_not_printed() -> None:
    s = Settings(keycloak_client_secret="local-api-secret")
    assert "local-api-secret" not in repr(s)


@pytest.mark.parametrize("seconds", [0, -1])
def test_extraction_timeout_must_be_positive(seconds: int) -> None:
    # 0 would fail every PDF at once: the worker would stop the parser before it has started.
    with pytest.raises(ValidationError, match="extraction_timeout_seconds"):
        Settings(extraction_timeout_seconds=seconds)


def test_answer_max_tokens_defaults_to_1500_and_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings(_env_file=None).answer_max_tokens == 1500
    monkeypatch.setenv("SMART_TUTOR_ANSWER_MAX_TOKENS", "800")
    assert Settings(_env_file=None).answer_max_tokens == 800


@pytest.mark.parametrize("tokens", [0, -1])
def test_answer_max_tokens_must_be_positive(tokens: int) -> None:
    with pytest.raises(ValidationError, match="answer_max_tokens"):
        Settings(answer_max_tokens=tokens)
