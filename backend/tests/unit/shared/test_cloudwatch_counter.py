import logging
from typing import cast

import pytest
from mypy_boto3_cloudwatch import CloudWatchClient

from smart_tutor.shared.adapters.aws.cloudwatch_counter import CloudWatchCounter


class RecordingCloudWatch:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self._error = error

    def put_metric_data(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return {}


def _counter(client: RecordingCloudWatch, dimensions: dict[str, str]) -> CloudWatchCounter:
    return CloudWatchCounter(cast(CloudWatchClient, client), "SmartTutor/Agent", "QuestionScreenFailures", dimensions)


async def test_increment_puts_one_count_with_the_dimensions() -> None:
    client = RecordingCloudWatch()
    await _counter(client, {"Deployment": "local"}).increment()
    assert client.calls == [
        {
            "Namespace": "SmartTutor/Agent",
            "MetricData": [
                {
                    "MetricName": "QuestionScreenFailures",
                    "Dimensions": [{"Name": "Deployment", "Value": "local"}],
                    "Value": 1,
                    "Unit": "Count",
                }
            ],
        }
    ]


async def test_a_failed_put_is_logged_and_never_raised(caplog: pytest.LogCaptureFixture) -> None:
    client = RecordingCloudWatch(RuntimeError("AccessDenied"))
    with caplog.at_level(logging.WARNING):
        await _counter(client, {}).increment()
    assert "QuestionScreenFailures" in caplog.text
