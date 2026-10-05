import boto3
import pytest
from botocore.stub import Stubber

from smart_tutor.shared.adapters.aws.ssm_parameters import SsmParameterStore
from smart_tutor.shared.ports.parameter_store import ParameterNotFoundError


def _client():  # type: ignore[no-untyped-def]
    return boto3.client("ssm", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")


def test_returns_the_parameter_value() -> None:
    client = _client()
    with Stubber(client) as stub:
        stub.add_response("get_parameter", {"Parameter": {"Name": "/a", "Value": "50"}}, {"Name": "/a"})
        assert SsmParameterStore(client).get("/a") == "50"


def test_a_missing_parameter_raises_with_its_name() -> None:
    client = _client()
    with Stubber(client) as stub:
        stub.add_client_error("get_parameter", service_error_code="ParameterNotFound")
        with pytest.raises(ParameterNotFoundError, match="/a"):
            SsmParameterStore(client).get("/a")
