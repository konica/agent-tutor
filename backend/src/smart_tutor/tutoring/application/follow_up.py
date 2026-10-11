"""The search query of a question (PRD §9.2 step 1). One small function, so a model-written standalone query can
replace it later."""

from collections.abc import Sequence

from smart_tutor.knowledge.application import MAX_QUERY_CHARS
from smart_tutor.tutoring.domain.turn import HistoryTurn


def search_query(question: str, history: Sequence[HistoryTurn]) -> str:
    """A follow-up searches with the previous question before the current one, so "what are its limitations?" still
    finds the document the conversation is about; built in code, no model call. The current question stays whole and
    the previous one is cut to keep the query within the search limit."""
    if not history:
        return question
    room = MAX_QUERY_CHARS - len(question) - 1
    previous = history[-1].question[:room].rstrip() if room > 0 else ""
    return f"{previous}\n{question}" if previous else question
