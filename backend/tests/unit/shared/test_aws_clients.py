from collections.abc import Callable

import pytest

from smart_tutor.shared.adapters.aws.clients import s3_client, sqs_client, ssm_client
from smart_tutor.shared.config import Settings

CLIENTS: list[tuple[Callable[[Settings], object], str]] = [(s3_client, "S3"), (sqs_client, "SQS"), (ssm_client, "SSM")]


@pytest.fixture(autouse=True)
def _real_env_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("AWS_IGNORE_CONFIGURED_ENDPOINT_URLS", raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "real-ish")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "real-ish-secret")
    for _, service in CLIENTS:
        monkeypatch.delenv(f"AWS_ENDPOINT_URL_{service}", raising=False)


@pytest.fixture
def _localstack_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    for _, service in CLIENTS:
        monkeypatch.setenv(f"AWS_ENDPOINT_URL_{service}", "http://localhost:10402")


def _access_key(client: object) -> str:
    return client._request_signer._credentials.access_key  # type: ignore[attr-defined]


def _endpoint(client: object) -> str:
    return client.meta.endpoint_url  # type: ignore[attr-defined]


@pytest.mark.usefixtures("_localstack_endpoints")
def test_localstack_signs_s3_and_sqs_with_dummy_keys() -> None:
    settings = Settings(localstack=True)

    assert _access_key(s3_client(settings)) == "test"
    assert _access_key(sqs_client(settings)) == "test"
    assert _access_key(ssm_client(settings)) == "test"


@pytest.mark.usefixtures("_localstack_endpoints")
@pytest.mark.parametrize(("make_client", "service"), CLIENTS)
def test_localstack_keeps_its_endpoint_when_the_shell_ignores_configured_ones(
    monkeypatch: pytest.MonkeyPatch, make_client: Callable[[Settings], object], service: str
) -> None:
    # The deploy runbooks set this in PowerShell; it would send the dummy keys to real AWS.
    monkeypatch.setenv("AWS_IGNORE_CONFIGURED_ENDPOINT_URLS", "true")

    assert _endpoint(make_client(Settings(localstack=True))) == "http://localhost:10402"


@pytest.mark.parametrize(("make_client", "service"), CLIENTS)
def test_localstack_without_its_endpoint_stops(make_client: Callable[[Settings], object], service: str) -> None:
    with pytest.raises(RuntimeError, match=f"AWS_ENDPOINT_URL_{service}"):
        make_client(Settings(localstack=True))


def test_default_settings_keep_the_environment_credentials() -> None:
    settings = Settings()

    assert _access_key(s3_client(settings)) == "real-ish"
    assert _access_key(sqs_client(settings)) == "real-ish"
    assert _access_key(ssm_client(settings)) == "real-ish"


@pytest.mark.usefixtures("_localstack_endpoints")
def test_default_settings_leave_endpoints_to_boto3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_IGNORE_CONFIGURED_ENDPOINT_URLS", "true")

    assert "amazonaws.com" in _endpoint(ssm_client(Settings()))
