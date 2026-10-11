"""The API's client for the agent's POST /ask: forwards the learner's token, streams the SSE body back."""

from collections.abc import AsyncIterator, Sequence

import httpx

from smart_tutor.shared.domain.errors import UnauthenticatedError


class AgentUnavailableError(Exception):
    """The agent couldn't be reached or failed before streaming."""


class AgentAnswer:
    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    async def chunks(self) -> AsyncIterator[bytes]:
        # Decoded bytes (not aiter_raw): the relayed response carries no Content-Encoding of its own.
        async for chunk in self._response.aiter_bytes():
            yield chunk

    async def aclose(self) -> None:
        await self._response.aclose()


class AgentClient:
    def __init__(self, base_url: str, http: httpx.AsyncClient) -> None:
        self._url = base_url.rstrip("/") + "/ask"
        self._http = http

    async def open_answer(
        self,
        access_token: str,
        question: str,
        document_ids: Sequence[str] | None = None,
        *,
        thread_id: str | None = None,
        run_id: str | None = None,
    ) -> AgentAnswer:
        """Ask the agent; it searches the learner's ready documents with their token, only `document_ids` of them
        when given (a conversation limited to its documents, US-4c). `thread_id` and `run_id` name the ask's trace
        (PRD §10.4); the run id is kept with the turn."""
        body: dict[str, object] = {"question": question}
        if document_ids is not None:
            body["document_ids"] = list(document_ids)
        if thread_id is not None:
            body["thread_id"] = thread_id
        if run_id is not None:
            body["run_id"] = run_id
        request = self._http.build_request(
            "POST", self._url, json=body, headers={"Authorization": f"Bearer {access_token}"}
        )
        try:
            response = await self._http.send(request, stream=True)
        except httpx.HTTPError as e:
            raise AgentUnavailableError(f"agent unreachable: {type(e).__name__}") from None
        if response.status_code == 200:
            return AgentAnswer(response)
        await response.aclose()
        if response.status_code == 401:
            raise UnauthenticatedError("the agent refused the token")
        raise AgentUnavailableError(f"agent answered {response.status_code}")
