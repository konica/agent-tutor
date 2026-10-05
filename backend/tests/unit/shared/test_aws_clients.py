import pytest

from smart_tutor.shared.adapters.aws.clients import s3_client, sqs_client, ssm_client
from smart_tutor.shared.config import Settings


@pytest.fixture(autouse=True)
def _real_env_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "real-ish")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "real-ish-secret")


def _access_key(client: object) -> str:
    return client._request_signer._credentials.access_key  # type: ignore[attr-defined]


def test_localstack_signs_s3_and_sqs_with_dummy_keys() -> None:
    settings = Settings(localstack=True)

    assert _access_key(s3_client(settings)) == "test"
    assert _access_key(sqs_client(settings)) == "test"
    assert _access_key(ssm_client(settings)) == "test"


def test_default_settings_keep_the_environment_credentials() -> None:
    settings = Settings()

    assert _access_key(s3_client(settings)) == "real-ish"
    assert _access_key(sqs_client(settings)) == "real-ish"
    assert _access_key(ssm_client(settings)) == "real-ish"
