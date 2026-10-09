"""PdfExtractor that runs another in a child process and kills it past a time limit (PRD §9.5, worker isolation).

A child process, not a signal: an alarm cannot interrupt a long C call (zlib inside pypdf). `spawn` behaves the same
on Linux and Windows and never forks a threaded process, so the inner extractor must be importable and picklable.
"""

import multiprocessing
from multiprocessing.connection import Connection

from smart_tutor.knowledge.ports.pdf_extractor import (
    ExtractionTimeoutError,
    PdfExtractor,
    TooManyPagesError,
    UnreadablePdfError,
)


def _extract(conn: Connection, inner: PdfExtractor, data: bytes, max_pages: int, first: int | None) -> None:
    """Child side: send ("pages", list) | ("too_many", pages) | ("unreadable", message).

    Tagged tuples, not pickled exceptions: TooManyPagesError(pages) does not survive pickling (args hold the message).
    """
    try:
        try:
            result: tuple[str, object] = ("pages", inner.extract_pages(data, max_pages, first))
        except TooManyPagesError as error:
            result = ("too_many", error.pages)
        except UnreadablePdfError as error:
            result = ("unreadable", str(error))
        conn.send(result)
    finally:
        conn.close()


class TimeLimitedExtractor(PdfExtractor):
    def __init__(self, inner: PdfExtractor, timeout_seconds: float) -> None:
        self._inner = inner
        self._timeout = timeout_seconds

    def extract_pages(self, data: bytes, max_pages: int, first: int | None = None) -> list[str]:
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        child = context.Process(target=_extract, args=(sender, self._inner, data, max_pages, first), daemon=True)
        child.start()
        sender.close()  # the child holds the only write end, so its death shows up as EOF
        try:
            if not receiver.poll(self._timeout):
                child.kill()
                raise ExtractionTimeoutError(f"no result after {self._timeout} seconds")
            try:
                tag, value = receiver.recv()
            except EOFError:
                child.join()
                raise UnreadablePdfError(f"the parser exited with code {child.exitcode}") from None
        finally:
            receiver.close()
            child.join()
        if tag == "too_many":
            raise TooManyPagesError(value)
        if tag == "unreadable":
            raise UnreadablePdfError(value)
        return value  # type: ignore[no-any-return]
