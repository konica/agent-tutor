"""topic_check candidates (spec 2026-10-13 §3, §6.1): the judge model writes learner messages of each kind, labeled
on-topic or off-topic by the kind; a human accepts or rejects each in the annotation queue (evals.review).

Usage: make evals-generate DATASET=topic_check (python -m evals.generate topic_check --per-type N)
"""

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from evals.review import Candidate

LOG = logging.getLogger(__name__)
MAX_QUESTION_CHARS = 4000  # the API's question limit (routes/threads.py)
FOLLOW_UP_SEPARATOR = " || "


@dataclass(frozen=True)
class Kind:
    off_topic: bool
    description: str
    examples: tuple[str, ...]


KINDS: dict[str, Kind] = {
    "subject_concept": Kind(
        False,
        "a question asking to explain or understand a concept in any school, university, or professional subject; vary "
        "the subjects widely, including cooking, sports, finance, security, art, music, law, and medicine",
        ("Explain photosynthesis in simple terms.", "How do I calculate the derivative of x squared times sine x?"),
    ),
    "document_question": Kind(
        False,
        "a question about a paper, book, chapter, magazine article, or news article the learner uploaded",
        ("How does the author define inflation in chapter 3?", "What does the sports article say about the final?"),
    ),
    "follow_up": Kind(
        False,
        f"a short follow-up to an earlier study question, written as `earlier question{FOLLOW_UP_SEPARATOR}follow-up`",
        (
            f"What is gradient descent?{FOLLOW_UP_SEPARATOR}Explain that more simply.",
            f"How does the cookbook make sourdough starter?{FOLLOW_UP_SEPARATOR}Why does it need to be fed every day?",
        ),
    ),
    "study_task": Kind(
        False,
        "a request for help studying the learner's own material: quizzes, flashcards, summaries, study plans, practice "
        "questions",
        ("Make me a quiz on the uploaded chemistry chapter.", "Help me plan my study week for the biology exam."),
    ),
    "borderline_study_task": Kind(
        False,
        "a study request that sounds like a personal errand or planning task but is about learning the learner's own "
        "material: timetables, flashcards to print, reading schedules, revision plans built from their documents",
        (
            "Make a revision timetable for my three exams from my lecture notes.",
            "Turn chapter 2 of my economics book into flashcards I can print.",
        ),
    ),
    "library_news": Kind(
        False,
        "a question about a news or magazine article the learner uploaded, even when the topic is current events",
        (
            "What does the news article I uploaded say caused the strike?",
            "According to the magazine piece in my library, why did the startup fail?",
        ),
    ),
    "greeting": Kind(
        True,
        "a greeting, small talk, thanks with no question, or a question about the assistant itself",
        ("hi, how are you today?", "What can you do?"),
    ),
    "entertainment": Kind(
        True,
        "a request for jokes, stories, poems, songs, games, or role-play",
        ("Tell me a joke about cats.", "Let's role-play: you are a pirate captain."),
    ),
    "personal_task": Kind(
        True,
        "a personal errand or task that is not studying: emails, messages, trip plans, bookings, shopping, "
        "recommendations, fixing the learner's own code or devices",
        ("Write an email to my landlord asking to fix the heater.", "Can you help me fix the bug in my React app?"),
    ),
    "borderline_personal_task": Kind(
        True,
        "a personal task that mentions school or study but is not about understanding material: cover letters, "
        "applications, schedules for the learner's week, homework written for them to hand in",
        (
            "Write my cover letter for a summer internship at a bank.",
            "Plan my week around classes, the gym, and groceries.",
        ),
    ),
    "live_news": Kind(
        True,
        "a request for current or breaking news that is not in any document the learner uploaded",
        ("What's in the news today?", "Who won the election last night?"),
    ),
    "live_information": Kind(
        True,
        "a request for live or real-time information: weather, prices, scores, traffic, opening hours, today's news",
        ("What's the weather in Hanoi tomorrow?", "What is the price of an iPhone 17 right now?"),
    ),
}

RUBRIC = """\
Each item is a learner message proposed for the topic_check dataset, with its kind (outputs.evidence) and the expected
label (outputs.expected.off_topic). On-topic: anything a learner asks in order to study, understand, or research, in any
subject; questions about their documents; follow-ups; study tasks on their material. Off-topic: greetings and questions
about the tutor itself, entertainment, personal tasks, live information (spec 2026-10-13 §3). Accept (1) only when the
message is realistic and the label is right by that policy. Reject (0) anything ambiguous or that you would need to
edit. The borderline kinds sit on the boundary: a study task is on-topic and a personal task that only mentions school
is off-topic; a news or magazine article the learner uploaded is on-topic and live or breaking news is off-topic. Check
those with particular care: accept one only when the policy settles it without doubt.
"""

WRITER = """You write test messages for an AI study tutor. Learners upload papers, books, magazines, and news articles \
and ask the tutor to help them study and understand them.

Write {count} different messages a learner might type, each of them {description}. Vary the wording, length, tone, \
and subject; make some casual or with small typos. Reply with one message per line and nothing else.

Examples:
{examples}"""

_NUMBERING = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s*")

Write = Callable[[str, Kind, int], Awaitable[list[str]]]


def message_writer(model: BaseChatModel) -> Write:
    """`count` messages of one kind by `model` (the judge model, never the tutor's): one per line of its reply."""

    async def messages(kind: str, spec: Kind, count: int) -> list[str]:
        prompt = WRITER.format(count=count, description=spec.description, examples="\n".join(spec.examples))
        reply = await model.ainvoke([HumanMessage(prompt)])
        lines = (_NUMBERING.sub("", line).strip() for line in reply.text.splitlines())
        return [line for line in lines if line][:count]

    return messages


def _candidate(kind: str, spec: Kind, line: str) -> Candidate | None:
    inputs: dict[str, object]
    if kind == "follow_up":
        earlier, _, question = line.partition(FOLLOW_UP_SEPARATOR.strip())
        earlier, question = earlier.strip(), question.strip()
        if not earlier or not question:
            return None
        inputs = {"question": question, "history": [{"question": earlier, "answer": ""}]}
    else:
        question = line.strip()
        if not question:
            return None
        inputs = {"question": question}
    if len(question) > MAX_QUESTION_CHARS:
        return None
    return Candidate(
        inputs=inputs,
        expected={"off_topic": spec.off_topic, "kind": kind},
        type=kind,
        evidence=({"chunk": f"kind:{kind}", "text": spec.description},),
    )


async def write_candidates(per_kind: int, write: Write) -> list[Candidate]:
    """`per_kind` messages of each kind as review candidates, without duplicates. A kind whose writing fails (a parse
    error or throttling) is dropped, not the batch."""

    async def one(kind: str, spec: Kind) -> list[Candidate]:
        try:
            lines = await write(kind, spec, per_kind)
        except Exception as error:
            LOG.warning("Dropped the %s messages: %s: %s", kind, type(error).__name__, error)
            return []
        seen: set[str] = set()
        out: list[Candidate] = []
        for line in lines:
            candidate = _candidate(kind, spec, line)
            if candidate is not None and (key := str(candidate.inputs)) not in seen:
                seen.add(key)
                out.append(candidate)
        return out

    batches = await asyncio.gather(*(one(kind, spec) for kind, spec in KINDS.items()))
    return [candidate for batch in batches for candidate in batch]
