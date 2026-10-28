"""Langfuse 4.47's score endpoints in memory, for the rating adapter (as read from its source for #318, events_only
mode): POST /api/public/scores answers 200 with the id and queues the score, which shows in GET /api/public/v3/scores
only after `lag` more list calls; it never checks the trace. DELETE /api/public/scores/{id} answers 202 and removes
only a score that already shows: a delete that arrives first is lost, as in Langfuse. The v3 list is strict (an unknown
parameter is 400) and pages by cursor. GET /api/public/score-configs pages by page/limit. Every call needs the key
pair as Basic auth."""

import base64
import json
import uuid
from collections.abc import Iterable
from typing import Any

import httpx

PUBLIC_KEY = "pk-lf-test"
SECRET_KEY = "sk-lf-test"
V3_PARAMS = {"traceId", "name", "limit", "cursor", "fields", "id", "environment", "dataType"}


class FakeLangfuseScores:
    def __init__(
        self,
        configs: Iterable[dict[str, Any]] = (),
        lag: int = 0,
        down: bool = False,
        page_size: int = 100,
    ) -> None:
        self.configs = list(configs)  # {id, name, dataType, isArchived}
        self.lag = lag  # list calls a new score stays hidden for
        self.down = down
        self.page_size = page_size  # the v3 list's page size, whatever limit asks (to test paging)
        self.scores: dict[str, dict[str, Any]] = {}  # id -> score as listed (shown or not)
        self.hidden: dict[str, int] = {}  # id -> list calls left before it shows
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self._handle)

    def client(self) -> httpx.Client:
        return httpx.Client(base_url="http://langfuse.test", transport=self.transport, auth=(PUBLIC_KEY, SECRET_KEY))

    def config(self, name: str = "learner_rating", data_type: str = "BOOLEAN", archived: bool = False) -> str:
        config_id = str(uuid.uuid4())
        self.configs.append({"id": config_id, "name": name, "dataType": data_type, "isArchived": archived})
        return config_id

    def seed(self, trace_id: str, value: bool = True, name: str = "learner_rating") -> str:
        """A score that already shows, e.g. posted by an earlier API process."""
        score_id = str(uuid.uuid4())
        self.scores[score_id] = _listed(score_id, trace_id, name, value, "local")
        return score_id

    def shown(self, trace_id: str, name: str = "learner_rating") -> list[dict[str, Any]]:
        """The scores a reader sees now, oldest first; doesn't advance the lag."""
        return [
            s for i, s in self.scores.items() if i not in self.hidden and s["traceId"] == trace_id and s["name"] == name
        ]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        expected = "Basic " + base64.b64encode(f"{PUBLIC_KEY}:{SECRET_KEY}".encode()).decode()
        if request.headers.get("authorization") != expected:
            return httpx.Response(401, json={"message": "Invalid credentials"})
        path, method = request.url.path, request.method
        if method == "POST" and path == "/api/public/scores":
            return self._post(json.loads(request.content))
        if method == "DELETE" and path.startswith("/api/public/scores/"):
            score_id = path.removeprefix("/api/public/scores/")
            if score_id not in self.hidden:  # a delete before ingestion is lost
                self.scores.pop(score_id, None)
            return httpx.Response(202, json={"message": "Score deletion queued successfully"})
        if method == "GET" and path == "/api/public/v3/scores":
            return self._list(request.url.params)
        if method == "GET" and path == "/api/public/score-configs":
            return self._configs(request.url.params)
        return httpx.Response(404, json={"message": "not found"})

    def _post(self, body: dict[str, Any]) -> httpx.Response:
        value = body.get("value")
        if (
            body.get("dataType") != "BOOLEAN"
            or type(value) is not int
            or value not in (0, 1)
            or not body.get("traceId")
        ):
            return httpx.Response(400, json={"message": "invalid score"})
        score_id = body.get("id") or str(uuid.uuid4())
        score = _listed(score_id, body["traceId"], body["name"], body["value"] == 1, body.get("environment", "default"))
        score["configId"] = body.get("configId")
        self.scores[score_id] = score
        if self.lag:
            self.hidden[score_id] = self.lag
        return httpx.Response(200, json={"id": score_id})

    def _list(self, params: httpx.QueryParams) -> httpx.Response:
        if set(params) - V3_PARAMS or int(params.get("limit", "50")) > 100:
            return httpx.Response(400, json={"message": "invalid query"})
        for score_id in list(self.hidden):  # each list call brings queued scores one step closer to showing
            self.hidden[score_id] -= 1
            if self.hidden[score_id] <= 0:
                del self.hidden[score_id]
        matches = [
            s
            for i, s in self.scores.items()
            if i not in self.hidden
            and s["traceId"] == params.get("traceId", s["traceId"])
            and s["name"] == params.get("name", s["name"])
        ]
        start = int(params.get("cursor", "0"))
        page = matches[start : start + self.page_size]
        meta: dict[str, Any] = {"limit": int(params.get("limit", "50"))}
        if start + self.page_size < len(matches):
            meta["cursor"] = str(start + self.page_size)
        return httpx.Response(200, json={"data": page, "meta": meta})

    def _configs(self, params: httpx.QueryParams) -> httpx.Response:
        page, limit = int(params.get("page", "1")), int(params.get("limit", "50"))
        if limit > 100:
            return httpx.Response(400, json={"message": "invalid query"})
        size = min(limit, self.page_size)
        data = self.configs[(page - 1) * size : page * size]
        pages = max(1, -(-len(self.configs) // size))
        return httpx.Response(
            200,
            json={
                "data": data,
                "meta": {"page": page, "limit": limit, "totalItems": len(self.configs), "totalPages": pages},
            },
        )


def _listed(score_id: str, trace_id: str, name: str, value: bool, environment: str) -> dict[str, Any]:
    return {
        "id": score_id,
        "traceId": trace_id,
        "name": name,
        "value": value,
        "dataType": "BOOLEAN",
        "environment": environment,
    }
