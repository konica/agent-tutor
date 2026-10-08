import random
from pathlib import Path

import numpy as np
from langchain_core.messages import AIMessage

from evals.corpus_index import CorpusIndex, IndexedChunk
from evals.detection_dataset import dump_items, load_items
from evals.generators.subject_detection import (
    AMBIGUOUS_PROMPT,
    MULTI_PROMPT,
    SINGLE_PROMPT,
    generate,
    looks_like_references,
    make_learners,
)
from evals.seed_corpus.manifest import SeedDocument
from fakes import fake_chat_model

SUBJECTS = {
    "a": ("NLP",),
    "b": ("NLP", "Vision"),
    "c": ("Vision",),
    "d": ("RL",),
    "e": ("RL", "GNN"),
    "f": ("GNN",),
    "g": ("NLP", "GNN"),
}
DOCS = {k: SeedDocument(k, "arxiv", k, "CC-BY-4.0", "0" * 64, v, f"Title {k}") for k, v in SUBJECTS.items()}
LONG = "word " * 100


def make_index() -> CorpusIndex:
    chunks = [IndexedChunk(f"{k}:{i}", k, i + 1, LONG) for k in DOCS for i in range(2)]
    chunks.append(IndexedChunk("a:short", "a", 9, "References"))
    return CorpusIndex(DOCS, chunks, np.zeros((len(chunks), 2)))


def replies(n: int) -> list[AIMessage]:
    return [AIMessage(content=f'<think>x</think> "What is thing {i}?"\n') for i in range(n)]


def test_make_learners_have_enough_subjects_and_are_deterministic() -> None:
    docs = list(DOCS.values())
    learners = make_learners(docs, random.Random(1), 12)
    assert len(learners) == 12
    for learner in learners:
        subjects = {s for d in learner.documents for s in DOCS[d].subjects}
        assert len(subjects) >= 2
        assert len(set(learner.documents)) == len(learner.documents)
    assert learners == make_learners(docs, random.Random(1), 12)


def test_generate_counts_labels_and_validity(tmp_path: Path) -> None:
    index = make_index()
    learners = make_learners(list(DOCS.values()), random.Random(2), 6)
    counts = {"single": (2, 1), "multi": (1, 2), "ambiguous": (1, 1)}
    items = generate(index, learners, fake_chat_model(*replies(20)), random.Random(3), counts)

    by_kind = {k: [i for i in items if i.kind == k] for k in counts}
    for kind, (smoke, rest) in counts.items():
        assert len(by_kind[kind]) == smoke + rest
        assert sum(i.smoke for i in by_kind[kind]) == smoke
    assert by_kind["single"][0].id == "single-001"
    assert len({i.id for i in items}) == len(items)

    for i in items:
        assert i.question.startswith("What is thing")
        assert "think" not in i.question and '"' not in i.question
        assert all(not c.endswith(":short") for c in i.source_chunks)
        sources = {DOCS[c.split(":")[0]] for c in i.source_chunks}
        union = {s for d in sources for s in d.subjects}
        assert set(i.expected_subjects) == union
        if i.kind == "single":
            assert len(i.source_chunks) == 1
        else:
            assert len(sources) == 2 and len(union) <= 3
            d1, d2 = sources
            assert not set(d1.subjects) & set(d2.subjects)

    path = tmp_path / "d.yaml"
    dump_items(items, path)
    assert load_items("full", path, DOCS) == items


def test_generate_is_deterministic() -> None:
    index = make_index()
    learners = make_learners(list(DOCS.values()), random.Random(2), 6)
    counts = {"single": (1, 1), "multi": (1, 0), "ambiguous": (1, 0)}
    first = generate(index, learners, fake_chat_model(*replies(10)), random.Random(5), counts)
    second = generate(index, learners, fake_chat_model(*replies(10)), random.Random(5), counts)
    assert first == second


def test_prompt_quotes_passage_as_data() -> None:
    assert "<passage>" in SINGLE_PROMPT
    assert "Reply with the question only." in SINGLE_PROMPT


def test_empty_replies_are_retried_and_unclosed_think_is_stripped() -> None:
    index = make_index()
    learners = make_learners(list(DOCS.values()), random.Random(2), 6)
    model = fake_chat_model(
        AIMessage(content="<think>only thinking</think>"),
        AIMessage(content="<think>never closed"),
        AIMessage(content="What is a graph?"),
    )
    items = generate(index, learners, model, random.Random(3), {"single": (1, 0)})
    assert [i.question for i in items] == ["What is a graph?"]


REFS = (
    "[1] Vaswani, A., et al. Attention is all you need. In Proc. NeurIPS, 2017. pp. 5998-6008.\n"
    "[2] Devlin, J., et al. BERT. arXiv preprint arXiv:1810.04805, 2018.\n"
    "[3] He, K., et al. Deep residual learning. In Proceedings of CVPR, 2016. " + "x" * 200
)
PROSE_ONE_YEAR = (
    "Attention layers have replaced recurrence in most models since the transformer. " * 4 + "It appeared in 2017."
)


def test_reference_chunks_are_detected_and_prose_with_one_year_is_not() -> None:
    assert looks_like_references(REFS)
    assert looks_like_references("References\n[1] Some paper " + "x" * 300)
    assert not looks_like_references(PROSE_ONE_YEAR)


def test_generate_skips_reference_chunks() -> None:
    chunks = [IndexedChunk(f"{k}:0", k, 1, LONG) for k in DOCS] + [IndexedChunk(f"{k}:ref", k, 2, REFS) for k in DOCS]
    index = CorpusIndex(DOCS, chunks, np.zeros((len(chunks), 2)))
    learners = make_learners(list(DOCS.values()), random.Random(2), 6)
    counts = {"single": (5, 5), "multi": (3, 3)}
    items = generate(index, learners, fake_chat_model(*replies(20)), random.Random(3), counts)
    assert all(not c.endswith(":ref") for i in items for c in i.source_chunks)


def test_prompts_keep_passages_quoted_and_set_kind_specific_rules() -> None:
    for prompt in (SINGLE_PROMPT, MULTI_PROMPT, AMBIGUOUS_PROMPT):
        assert "{passages}" in prompt and "quoted data" in prompt and "Reply with the question only." in prompt
        assert "by number" in prompt
    assert "self-contained" in SINGLE_PROMPT and "names the specific concept" in SINGLE_PROMPT
    assert "names one concept from each" in MULTI_PROMPT and "comparison or contrast" in MULTI_PROMPT
    assert "Do not name any field" in AMBIGUOUS_PROMPT and "How was the model evaluated?" in AMBIGUOUS_PROMPT
