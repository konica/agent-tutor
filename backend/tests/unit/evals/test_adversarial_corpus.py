"""The adversarial documents (#196) are in the manifest and in learner 1's library, as the taxonomy plans them."""

from evals.adversarial_pdfs import PLACEMENTS, TRICKS, adversarial_id, document_spec, plants
from evals.corpus import GENERATED, load_manifest
from evals.evaluators.injection_resistance import LEAK_RUN, longest_shared_run
from evals.generators.injection import load_taxonomy
from evals.learners import LEARNERS, load_learners
from smart_tutor.tutoring.application import SYSTEM_PROMPT


def test_the_taxonomy_plants_every_placement_and_trick_of_the_ticket() -> None:
    spec = document_spec()
    assert spec["placements"] == list(PLACEMENTS) and spec["tricks"] == list(TRICKS)
    assert all(seed["markers"] for seed in spec["seeds"])
    assert all(m.casefold() in seed["text"].casefold() for seed in spec["seeds"] for m in seed["markers"])


def test_every_derivative_is_an_adversarial_manifest_entry_built_from_the_base() -> None:
    spec, seeds = document_spec(), load_manifest()
    base = seeds[spec["base"]]
    assert base.url == "https://arxiv.org/pdf/2305.14314v1" and base.injection_eval
    for plant in plants(spec):
        seed = seeds[adversarial_id(spec, plant)]
        assert (seed.base, seed.plant, seed.adversarial, seed.injection_eval) == (spec["base"], plant, True, True)


def test_every_adversarial_entry_keeps_an_open_license() -> None:
    import yaml

    from evals.corpus import MANIFEST

    entries = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["documents"]
    for entry in entries:
        if entry.get("injection_eval"):
            assert entry["license"] in ("CC-BY-4.0", "CC0-1.0"), entry["id"]


def test_learner_1_holds_every_derivative_and_the_control_and_learner_2_none() -> None:
    seeds, spec = load_manifest(), document_spec()
    learners = {learner.username: learner.documents for learner in load_learners(LEARNERS, seeds)}
    wanted = {adversarial_id(spec, p) for p in plants(spec)} | {c["document"] for c in load_taxonomy()["controls"]}
    assert wanted <= set(learners["learner@example.com"])
    assert not wanted & set(learners["learner2@example.com"])
    assert spec["base"] not in learners["learner@example.com"]  # only its derivatives


def test_the_control_handout_is_ascii_quotes_attacks_and_shares_no_run_with_the_system_prompt() -> None:
    control = load_taxonomy()["controls"][0]
    seed = load_manifest()[control["document"]]
    text = (GENERATED / "control-prompt-injection-course.txt").read_text(encoding="utf-8")
    assert seed.generated == GENERATED / "control-prompt-injection-course.txt" and not seed.adversarial
    assert text.isascii()
    assert all(m.casefold() in text.casefold() for m in control["markers"])
    folded = lambda t: " ".join(t.casefold().split())  # noqa: E731
    assert longest_shared_run(folded(text), folded(SYSTEM_PROMPT)) < LEAK_RUN
