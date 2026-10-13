from fastapi.testclient import TestClient
from pydantic import SecretStr

from fakes import FakeAnswerFeedback, FakeTokenVerifier, api_services
from smart_tutor.apps.api.main import create_app
from smart_tutor.shared.config import Settings


def test_shutdown_closes_the_answer_feedback() -> None:
    feedback = FakeAnswerFeedback()
    app = create_app(Settings(), verifier=FakeTokenVerifier(), services=api_services(feedback=feedback))
    with TestClient(app):
        assert not feedback.closed
    assert feedback.closed


def test_shutdown_closes_the_answer_feedback_with_the_real_verifier() -> None:
    feedback = FakeAnswerFeedback()
    settings = Settings(keycloak_client_secret=SecretStr("s"))
    with TestClient(create_app(settings, services=api_services(feedback=feedback))):
        assert not feedback.closed
    assert feedback.closed
