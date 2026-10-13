"""A Phoenix REST API in memory for the rating adapter (Phoenix 20.16's span-annotation endpoints, as probed for #290):
POST /v1/span_annotations?sync=true upserts by (span, name, identifier) and answers 404 for a span it doesn't have yet;
DELETE /v1/projects/{project}/span_annotations deletes by name, identifier, and kind, needs delete_all (or a time
window), and answers 404 for an unknown project."""

import json
from collections.abc import Callable, Iterable
from concurrent.futures import Executor, Future
from typing import Any

import httpx


class InlineExecutor(Executor):
    """Runs each submitted call at once on the caller's thread, so a test sees its effect when send returns."""

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> "Future[Any]":
        future: Future[Any] = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as e:  # handed to the future, as a real executor does
            future.set_exception(e)
        return future


class FakePhoenix:
    def __init__(
        self,
        spans: Iterable[str] = (),
        late: dict[str, int] | None = None,
        down: bool = False,
        projects: Iterable[str] = ("smart-tutor-test",),
    ) -> None:
        self.spans = set(spans)  # span ids (16 hex digits) Phoenix has
        self.late = dict(late or {})  # span id -> how many more annotation POSTs find it missing before it arrives
        self.down = down
        self.projects = set(projects)
        self.annotations: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self._handle)

    def client(self, key: str = "test-key") -> httpx.Client:
        return httpx.Client(
            base_url="http://phoenix.test", transport=self.transport, headers={"authorization": f"Bearer {key}"}
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        path = request.url.path
        if request.method == "POST" and path == "/v1/span_annotations":
            return self._annotate(request)
        if request.method == "DELETE" and path.startswith("/v1/projects/") and path.endswith("/span_annotations"):
            return self._delete(request, path.removeprefix("/v1/projects/").removesuffix("/span_annotations"))
        return httpx.Response(405)

    def _annotate(self, request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("sync") == "true", "an async insert is dropped when the span isn't there yet"
        data = json.loads(request.content)["data"]
        missing = [a["span_id"] for a in data if not self._has(a["span_id"])]
        if missing:
            return httpx.Response(404, text=f"Spans with IDs {', '.join(missing)} do not exist.")
        for a in data:
            self.annotations[(a["span_id"], a["name"], a.get("identifier", ""))] = a
        return httpx.Response(200, json={"data": [{"id": str(i)} for i, _ in enumerate(data)]})

    def _has(self, span_id: str) -> bool:
        if self.late.get(span_id, 0) > 0:
            self.late[span_id] -= 1
            if self.late[span_id] == 0:
                self.spans.add(span_id)
            return False
        return span_id in self.spans

    def _delete(self, request: httpx.Request, project: str) -> httpx.Response:
        params = request.url.params
        if params.get("delete_all") != "true" and not (params.get("start_time") and params.get("end_time")):
            return httpx.Response(422, text="bound the delete or set delete_all")
        if project not in self.projects:
            return httpx.Response(404, text=f"Project with name {project} not found")
        for key, a in list(self.annotations.items()):
            if all(params.get(field) in (None, a.get(field)) for field in ("name", "identifier", "annotator_kind")):
                del self.annotations[key]
        return httpx.Response(204)
