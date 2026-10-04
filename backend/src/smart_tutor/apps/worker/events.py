"""S3 event notifications (via SQS) → upload keys."""

import json
import logging
from typing import Any
from urllib.parse import unquote_plus

logger = logging.getLogger(__name__)


def upload_keys(body: str) -> list[str]:
    """Keys of created objects. S3 test events and unreadable bodies give none (and are then deleted)."""
    try:
        event: Any = json.loads(body)
    except json.JSONDecodeError:
        logger.warning("dropping a message that isn't JSON")
        return []
    records = event.get("Records", []) if isinstance(event, dict) else []
    keys: list[str] = []
    for record in records:
        try:
            if not str(record.get("eventName", "")).startswith("ObjectCreated:"):
                continue
            keys.append(unquote_plus(record["s3"]["object"]["key"]))  # S3 URL-encodes keys in events
        except (AttributeError, KeyError, TypeError):
            logger.warning("skipping a malformed S3 event record")
    return keys
