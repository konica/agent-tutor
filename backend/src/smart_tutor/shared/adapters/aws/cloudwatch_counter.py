"""A counter as a CloudWatch metric: one data point of 1 per event, with fixed dimensions and nothing else."""

import asyncio
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING

from smart_tutor.shared.ports.counter import Counter

if TYPE_CHECKING:
    from mypy_boto3_cloudwatch import CloudWatchClient
    from mypy_boto3_cloudwatch.type_defs import DimensionTypeDef, MetricDatumTypeDef

logger = logging.getLogger(__name__)


class CloudWatchCounter(Counter):
    def __init__(self, client: "CloudWatchClient", namespace: str, metric: str, dimensions: Mapping[str, str]) -> None:
        self._client, self._namespace, self._metric = client, namespace, metric
        self._dimensions: list[DimensionTypeDef] = [{"Name": k, "Value": v} for k, v in dimensions.items()]

    async def increment(self) -> None:
        datum: MetricDatumTypeDef = {
            "MetricName": self._metric,
            "Dimensions": self._dimensions,
            "Value": 1,
            "Unit": "Count",
        }
        try:
            await asyncio.to_thread(self._client.put_metric_data, Namespace=self._namespace, MetricData=[datum])
        except Exception:
            logger.warning("could not count %s", self._metric, exc_info=True)
