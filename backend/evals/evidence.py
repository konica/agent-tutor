"""Gold evidence for the `ask` dataset (sdd/specs/2026-10-28-ask-gold-evidence-design.md): quote matching, the gold-row
rules, and the checker that proves every quote is in its paper.

Usage: uv run --extra eval --extra ingest python -m evals.evidence
Loads ask.yaml, downloads the seed PDFs its gold rows name, and checks each quote against its page and the worker's
chunks, and that no distractor shares a chunk with the row's evidence. Prints the category x difficulty mix and each
question's word overlap with its quotes. Exits 1 on any failure.
The pure functions need no PDF (the ingest extra is imported only by `main`).
"""

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from typing import Any

from evals.dataset import Example, load_dataset
from evals.publish import TYPES

CATEGORIES = ("single_hop", "multi_hop", "unanswerable", "conflicting", "time_sensitive", "near_miss")
DIFFICULTIES = ("easy", "medium", "hard")
QUESTION_TYPES = (*TYPES, "false_premise")
MAX_QUOTE = 200  # the worker's chunks are 1,000 characters with 200 of overlap: a quote this short fits in one
MAX_SINGLE_HOP = 0.4  # "about a third" with some slack
MIN_DIFFICULTY_SHARE = 0.2
ALWAYS_HARD = ("multi_hop", "conflicting", "near_miss")
NEW_FIELDS = ("answer", "nuggets", "evidence", "distractors")
STOPWORDS = frozenset(
    re.findall(
        r"\w+",
        "the and for are was were with that this these those from what which who whom when where why how does did "
        "has have had can could would should will not but its their them they you your our his her than then into "
        "about over out any all each both too very",
    )
)


def normalize(text: str) -> str:
    """Quote matching form: NFKC, lower case, only [0-9a-z]. Absorbs pypdf's lost spaces, line-break hyphens,
    small-caps splits, ligatures, and math-italic letters."""
    return re.sub(r"[^0-9a-z]", "", unicodedata.normalize("NFKC", text).lower())


def contains(haystack: str, quote: str) -> bool:
    needle = normalize(quote)
    return bool(needle) and needle in normalize(haystack)


def is_gold(example: Example) -> bool:
    return bool(example.metadata.get("category"))


def _quote_problems(kind: str, quotes: Any) -> list[str]:
    problems: list[str] = []
    for i, item in enumerate(quotes):
        quote = str(item.get("quote", ""))
        if not normalize(quote):
            problems.append(f"{kind}[{i}]: quote is empty")
        if len(quote) > MAX_QUOTE:
            problems.append(f"{kind}[{i}]: quote has {len(quote)} characters, over the {MAX_QUOTE} limit")
        if not isinstance(item.get("page"), int) or item["page"] < 1:
            problems.append(f"{kind}[{i}]: page must be a 1-based integer")
    return problems


def row_problems(example: Example) -> list[str]:
    """What is wrong with one row's labels (design §5.1, §5.3); [] for a row that carries none."""
    out, meta = example.outputs, example.metadata
    if not is_gold(example):
        used = [f for f in NEW_FIELDS if f in out] + (["difficulty"] if "difficulty" in meta else [])
        return [f"has {', '.join(used)} but no metadata.category"] if used else []
    problems: list[str] = []
    category, qtype, difficulty = meta["category"], meta.get("type"), meta.get("difficulty")
    if category not in CATEGORIES:
        problems.append(f"unknown category {category!r} (one of {', '.join(CATEGORIES)})")
    if qtype not in QUESTION_TYPES:
        problems.append(f"unknown type {qtype!r} (one of {', '.join(QUESTION_TYPES)})")
    if difficulty not in DIFFICULTIES:
        problems.append(f"unknown difficulty {difficulty!r} (one of {', '.join(DIFFICULTIES)})")
    elif category in ALWAYS_HARD and difficulty != "hard":
        problems.append(f"{category} rows are always hard, not {difficulty}")
    elif category == "time_sensitive" and difficulty == "easy":
        problems.append("time_sensitive rows are at least medium, not easy")

    evidence_items: list[dict[str, Any]] = list(out.get("evidence") or [])
    distractors: list[dict[str, Any]] = list(out.get("distractors") or [])
    sources = list(out.get("sources") or [])
    problems += _quote_problems("evidence", evidence_items) + _quote_problems("distractors", distractors)
    for i, item in enumerate(evidence_items):
        if item.get("source") not in sources:
            problems.append(f"evidence[{i}]: source {item.get('source')!r} is not in the row's sources {sources}")
    gold_quotes = [normalize(str(item.get("quote", ""))) for item in evidence_items]
    for i, item in enumerate(distractors):
        text = normalize(str(item.get("quote", "")))
        if any(q and q in text for q in gold_quotes):
            problems.append(f"distractors[{i}]: quote contains a gold evidence quote")
    if category == "near_miss" and not distractors:
        problems.append("near_miss rows need distractors")

    if "nuggets" in out:
        problems.append("nuggets are deferred (#362); answer_correctness judges the reference answer")
    if "off_topic" in out:
        problems.append("off-topic questions belong to the topic check eval (#363)")

    if not out.get("covered"):
        if sources:
            problems.append("uncovered rows have sources: []")
        present = [f for f in ("answer", "evidence") if f in out]
        if present:
            problems.append(f"uncovered rows carry no {', '.join(present)}")
        return problems
    if category == "unanswerable":  # covered: false by nature, so it carries no evidence
        problems.append("unanswerable rows are covered: false")
    else:
        for field in ("evidence", "answer"):
            if not out.get(field):
                problems.append(f"covered gold rows need {field}")
    return problems


def mix_problems(examples: Sequence[Example]) -> list[str]:
    """The set-level rules over gold rows only (design §5.2, §5.3)."""
    gold = [e for e in examples if is_gold(e)]
    if not gold:
        return []
    problems: list[str] = []
    single = sum(e.metadata["category"] == "single_hop" for e in gold)
    if single / len(gold) > MAX_SINGLE_HOP:
        problems.append(f"single_hop is {single} of {len(gold)} gold rows, over {MAX_SINGLE_HOP:.0%}")
    levels = Counter(e.metadata.get("difficulty") for e in gold)
    for level in DIFFICULTIES:
        if levels[level] / len(gold) < MIN_DIFFICULTY_SHARE:
            problems.append(f"{level} is {levels[level]} of {len(gold)} gold rows, under {MIN_DIFFICULTY_SHARE:.0%}")
    return problems


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3 and w not in STOPWORDS}


def word_overlap(question: str, quotes: Sequence[str]) -> float:
    """The share of the question's content words that also occur in the quotes (high means a copied question)."""
    wanted = _words(question)
    if not wanted:
        return 0.0
    return len(wanted & _words(" ".join(quotes))) / len(wanted)


def distractor_overlaps(
    evidence_chunks: Sequence[Sequence[str]], distractor_chunks: Sequence[Sequence[str]]
) -> list[str]:
    """Distractors that sit in a worker chunk holding one of the row's evidence quotes, given each quote's chunk ids.
    A cited chunk counts as noise only when it holds a distractor quote and no gold quote (design §7.4), so such a
    distractor could never score, and the passage it shares a chunk with supports the answer."""
    problems: list[str] = []
    for i, held in enumerate(distractor_chunks):
        for j, gold in enumerate(evidence_chunks):
            if set(held) & set(gold):
                problems.append(
                    f"distractors[{i}] (chunks {' '.join(held)}) shares a chunk"
                    f" with evidence[{j}] (chunks {' '.join(gold)})"
                )
    return problems


def _quote_lines(
    number: int, kind: str, items: Sequence[dict[str, Any]], pages: dict[str, list[str]], chunks: dict[str, Any]
) -> list[tuple[str, bool, list[str]]]:
    """One (line, ok, chunk ids) per quote: on its page, and whole inside at least one worker chunk."""
    lines: list[tuple[str, bool, list[str]]] = []
    for item in items:
        source, page, quote = item["source"], item["page"], str(item["quote"])
        head = f"{number} {kind} {source} p{page}"
        texts = pages.get(source, [])
        if not 1 <= page <= len(texts) or not contains(texts[page - 1], quote):
            lines.append((f"{head} FAIL quote not on page {page}: {quote[:60]!r}", False, []))
            continue
        holding = [c.id for c in chunks.get(source, []) if contains(c.text, quote)]
        if not holding:
            lines.append((f"{head} FAIL quote on page {page} but in no single chunk: {quote[:60]!r}", False, []))
        else:
            lines.append((f"{head} OK {' '.join(holding)}", True, holding))
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    from evals.chunks import chunks_of_pdf
    from evals.corpus import download, load_manifest
    from evals.highlight_fixture import MAX_PAGES
    from smart_tutor.knowledge.adapters.pypdf_extractor import PypdfExtractor

    examples = load_dataset("ask").examples
    gold_rows = [(n, e) for n, e in enumerate(examples, start=1) if is_gold(e)]
    if not gold_rows:
        print("no gold rows in ask.yaml")
        return 0
    failed = False
    manifest = load_manifest()
    named = sorted(
        {i["source"] for _, e in gold_rows for k in ("evidence", "distractors") for i in e.outputs.get(k) or []}
    )
    paths = download([manifest[s] for s in named])
    pages: dict[str, list[str]] = {}
    chunks: dict[str, Any] = {}
    for source, path in paths.items():
        data = path.read_bytes()
        pages[source] = PypdfExtractor().extract_pages(data, MAX_PAGES)
        chunks[source] = chunks_of_pdf(source, data)

    for number, example in gold_rows:
        held: dict[str, list[list[str]]] = {}
        for kind in ("evidence", "distractors"):
            held[kind] = []
            for line, ok, ids in _quote_lines(number, kind, example.outputs.get(kind) or [], pages, chunks):
                print(line)
                failed |= not ok
                held[kind].append(ids)
        for problem in row_problems(example) + distractor_overlaps(held["evidence"], held["distractors"]):
            print(f"{number} FAIL {problem}")
            failed = True

    gold = [e for _, e in gold_rows]
    print(f"\nmix: {len(gold)} gold rows")
    mix = Counter((e.metadata["category"], e.metadata.get("difficulty")) for e in gold)
    for category in CATEGORIES:
        counts = {d: mix[(category, d)] for d in DIFFICULTIES}
        total = sum(counts.values())
        cells = "  ".join(f"{d} {n}" for d, n in counts.items())
        print(f"  {category:<15} {total:>3} ({total / len(gold):.0%})  {cells}")
    levels = Counter(e.metadata.get("difficulty") for e in gold)
    print("  " + "  ".join(f"{d} {levels[d]} ({levels[d] / len(gold):.0%})" for d in DIFFICULTIES))
    for problem in mix_problems(examples):
        print(f"FAIL mix: {problem}")
        failed = True

    print("\nword overlap (question vs its evidence quotes):")
    for number, example in gold_rows:
        quotes = [str(i["quote"]) for i in example.outputs.get("evidence") or []]
        if quotes:
            print(f"  {number} {word_overlap(str(example.inputs['question']), quotes):.2f}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
