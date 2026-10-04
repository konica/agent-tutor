"""The web client is generated from web/src/api/openapi.json; it must match the API. Fix: make api-client."""

import json
from pathlib import Path

from smart_tutor.apps.api.openapi_export import openapi_json

SNAPSHOT = Path(__file__).parents[5] / "web" / "src" / "api" / "openapi.json"


def test_web_openapi_snapshot_is_current() -> None:
    assert SNAPSHOT.exists(), "run `make api-client`"
    assert json.loads(SNAPSHOT.read_text(encoding="utf-8")) == json.loads(openapi_json()), "run `make api-client`"
