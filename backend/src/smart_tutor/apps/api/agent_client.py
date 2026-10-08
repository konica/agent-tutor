"""The API's client for the agent's POST /ask and /resume: forwards the learner's token, streams the SSE body back."""

from collections.abc import AsyncIterator

import httpx

from smart_tutor.shared.domain.errors import UnauthenticatedError


class AgentUnavailableError(Exception):
    """The agent couldn't be reached or failed before streaming."""


class AgentConflictError(Exception):
    """The agent has no paused question for this thread (it answered 409 to /resume)."""


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
        self._base = base_url.rstrip("/")
        self._http = http

    async def open_answer(
        self, access_token: str, thread_id: str, question: str, learner_subjects: list[tuple[str, str]]
    ) -> AgentAnswer:
        """Ask the agent; `learner_subjects` are (subject_id, name) of all the learner's subjects, to detect among."""
        return await self._open(
            "/ask",
            access_token,
            {
                "thread_id": thread_id,
                "question": question,
                "learner_subjects": [{"subject_id": s, "name": n} for s, n in learner_subjects],
            },
        )

    async def resume_answer(self, access_token: str, thread_id: str, subject_ids: list[str]) -> AgentAnswer:
        """Resume the thread the agent paused for the learner's pick; AgentConflictError when nothing waits."""
        return await self._open("/resume", access_token, {"thread_id": thread_id, "subject_ids": subject_ids})

    async def _open(self, path: str, access_token: str, body: dict[str, object]) -> AgentAnswer:
        request = self._http.build_request(
            "POST", self._base + path, json=body, headers={"Authorization": f"Bearer {access_token}"}
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
        if response.status_code == 409:
            raise AgentConflictError("the agent has nothing waiting for this thread")
        raise AgentUnavailableError(f"agent answered {response.status_code}")
