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


@pytest.fixture
def _localstack_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWS_IGNORE_CONFIGURED_ENDPOINT_URLS", raising=False)
    for service in ("S3", "SQS", "SSM"):
        monkeypatch.setenv(f"AWS_ENDPOINT_URL_{service}", "http://localhost:10402")


@pytest.mark.usefixtures("_localstack_endpoints")
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


@pytest.mark.usefixtures("_localstack_endpoints")
@pytest.mark.parametrize(("make_client", "variable"), [(s3_client, "S3"), (sqs_client, "SQS"), (ssm_client, "SSM")])
def test_localstack_refuses_a_real_aws_endpoint(
    monkeypatch: pytest.MonkeyPatch, make_client: object, variable: str
) -> None:
    # A value already set in the shell wins over `uv run --env-file`, so the dummy keys would reach AWS.
    monkeypatch.setenv(f"AWS_ENDPOINT_URL_{variable}", "https://example.us-east-1.amazonaws.com")

    with pytest.raises(RuntimeError, match=f"AWS_ENDPOINT_URL_{variable}"):
        make_client(Settings(localstack=True))  # type: ignore[operator]


@pytest.mark.usefixtures("_localstack_endpoints")
def test_localstack_refuses_ignored_endpoint_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_IGNORE_CONFIGURED_ENDPOINT_URLS", "true")

    with pytest.raises(RuntimeError, match="AWS_IGNORE_CONFIGURED_ENDPOINT_URLS"):
        ssm_client(Settings(localstack=True))
