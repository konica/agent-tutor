from collections.abc import Callable
from concurrent.futures import Executor, Future
from typing import Any


class InlineExecutor(Executor):
    """Runs each submitted call at once on the caller's thread, so a test sees its effect when send returns."""

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> "Future[Any]":
        future: Future[Any] = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as e:  # handed to the future, as a real executor does
            future.set_exception(e)
        return future
