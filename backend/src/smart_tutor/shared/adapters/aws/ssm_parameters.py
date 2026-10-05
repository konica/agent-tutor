"""ParameterStore on SSM Parameter Store."""

from typing import TYPE_CHECKING

from smart_tutor.shared.ports.parameter_store import ParameterNotFoundError, ParameterStore

if TYPE_CHECKING:
    from mypy_boto3_ssm import SSMClient


class SsmParameterStore(ParameterStore):
    def __init__(self, client: "SSMClient") -> None:
        self._client = client

    def get(self, name: str) -> str:
        try:
            return self._client.get_parameter(Name=name)["Parameter"]["Value"]
        except self._client.exceptions.ParameterNotFound:
            raise ParameterNotFoundError(name) from None
