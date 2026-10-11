"""Loading the eval learners' libraries (issue #222): which documents each learner holds, signing in, the API."""

from pathlib import Path

import httpx
import pytest

from evals import learners
from evals.corpus import CorpusError, SeedDocument, load_manifest, sha256_of
from evals.learners import (
    API,
    APP,
    ISSUER,
    LEARNERS,
    Learner,
    LoadError,
    Tutor,
    load_all,
    load_learners,
    load_library,
)
from fakes.evals_stack import FakeDocument, FakeStack


def test_the_eval_learners_hold_different_seed_documents() -> None:
    learners = load_learners(LEARNERS, load_manifest())
    assert [learner.username for learner in learners] == ["learner@example.com", "learner2@example.com"]
    first, second = (set(learner.documents) for learner in learners)
    assert first and second - first, "learner 2 needs documents learner 1 must never see"


def test_a_document_missing_from_the_manifest_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "learners.yaml"
    path.write_text("learners:\n  - {username: a, password: b, documents: [react-2022, nope]}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="nope"):
        load_learners(path, load_manifest())


def test_a_learner_signs_in_through_the_login_form_with_pkce() -> None:
    stack = FakeStack()
    tutor = Tutor(stack.client(), "learner@example.com", "learner")
    tutor.sign_in()  # the fake checks the PKCE verifier against the challenge
    assert tutor.call("POST", "/documents/duplicate-check", {"sha256": "0" * 64}) == {"document_id": None}


def test_a_wrong_password_is_reported() -> None:
    with pytest.raises(LoadError, match="learner@example.com"):
        Tutor(FakeStack().client(), "learner@example.com", "wrong").sign_in()


def test_an_expired_token_signs_in_again() -> None:
    stack = FakeStack()
    tutor = Tutor(stack.client(), "learner@example.com", "learner")
    tutor.call("POST", "/documents/duplicate-check", {"sha256": "0" * 64})
    stack.expire_tokens()
    assert tutor.call("POST", "/documents/duplicate-check", {"sha256": "0" * 64}) == {"document_id": None}
    assert stack.sign_ins == 2


def test_a_second_unauthorized_answer_is_a_load_error() -> None:
    stack = FakeStack()
    stack.always_unauthorized = True
    tutor = Tutor(stack.client(), "learner@example.com", "learner")
    with pytest.raises(LoadError, match="401"):
        tutor.call("POST", "/documents/duplicate-check", {"sha256": "0" * 64})
    assert stack.sign_ins == 2  # the first sign-in, one more after the first 401, then it gives up


def test_an_unexpected_status_is_a_load_error() -> None:
    tutor = Tutor(FakeStack().client(), "learner@example.com", "learner")
    with pytest.raises(LoadError, match="404"):
        tutor.call("GET", "/documents/00000000-0000-0000-0000-000000000999")


def test_an_upload_posts_the_file_to_the_presigned_url() -> None:
    stack = FakeStack()
    tutor = Tutor(stack.client(), "learner@example.com", "learner")
    upload_id = tutor.upload("2210.03629v3.pdf", b"%PDF-1.7 react")
    status = tutor.call("GET", f"/uploads/{upload_id}")
    assert status["outcome"] == "stored"
    assert stack.documents[status["document_id"]].state == "awaiting_subjects"


REACT, COT = b"%PDF-1.7 react", b"%PDF-1.7 cot"


def _seeds(tmp_path: Path) -> tuple[list[SeedDocument], dict[str, Path]]:
    seeds = [
        SeedDocument("react-2022", "u", sha256_of(REACT), ("LLM agents",), "2210.03629v3.pdf"),
        SeedDocument("cot-2022", "u", sha256_of(COT), ("Prompting", "Reasoning"), "2201.11903v6.pdf"),
    ]
    paths = {"react-2022": tmp_path / "react.pdf", "cot-2022": tmp_path / "cot.pdf"}
    paths["react-2022"].write_bytes(REACT)
    paths["cot-2022"].write_bytes(COT)
    return seeds, paths


def _load(stack: FakeStack, tmp_path: Path, timeout: float = 5) -> list[str]:
    seeds, paths = _seeds(tmp_path)
    tutor = Tutor(stack.client(), "learner@example.com", "learner")
    return load_library(tutor, seeds, paths, timeout=timeout, interval=0, log=lambda line: None)


def test_a_new_library_is_uploaded_and_gets_its_labeled_subjects(tmp_path: Path) -> None:
    stack = FakeStack()
    assert _load(stack, tmp_path) == []
    library = stack.library("learner@example.com")
    assert sorted((d.state, tuple(d.subjects)) for d in library) == [
        ("ready", ("LLM agents",)),
        ("ready", ("Prompting", "Reasoning")),
    ]


def test_a_second_run_uploads_nothing(tmp_path: Path) -> None:
    stack = FakeStack()
    _load(stack, tmp_path)
    before = (stack.uploads_started, {d.document_id: d.subjects for d in stack.documents.values()})
    assert _load(stack, tmp_path) == []
    assert (stack.uploads_started, {d.document_id: d.subjects for d in stack.documents.values()}) == before


def test_a_document_that_fails_is_reported(tmp_path: Path) -> None:
    stack = FakeStack()

    def fail(doc: FakeDocument) -> None:
        doc.state, doc.failure_reason = "failed", "The PDF has no text"

    stack.process = fail
    problems = _load(stack, tmp_path)
    assert len(problems) == 2 and all("The PDF has no text" in p for p in problems)
    assert stack.retries == 0  # a document that failed in this run is not retried


def test_a_document_still_processing_times_out(tmp_path: Path) -> None:
    stack = FakeStack()
    stack.process = lambda doc: None  # the worker never finishes
    problems = _load(stack, tmp_path, timeout=0.05)
    assert len(problems) == 2 and all("timed out" in p and "processing" in p for p in problems)


def test_a_document_that_failed_in_an_earlier_run_is_retried(tmp_path: Path) -> None:
    stack = FakeStack()
    stack.add("learner@example.com", REACT, state="failed", failure_reason="Bedrock throttled")
    assert _load(stack, tmp_path) == []
    assert stack.retries == 1
    assert all(d.state == "ready" for d in stack.library("learner@example.com"))


def test_an_archived_document_is_uploaded_once_more_found_as_a_duplicate_and_restored(tmp_path: Path) -> None:
    stack = FakeStack()
    archived = stack.add("learner@example.com", REACT, state="awaiting_subjects", archived=True)
    assert _load(stack, tmp_path) == []
    assert stack.uploads_started == 2  # react again (the duplicate check skips archived documents) and cot
    react = [d for d in stack.library("learner@example.com") if d.sha256 == sha256_of(REACT)]
    assert [d.document_id for d in react] == [archived.document_id]  # no new document
    assert not archived.archived and archived.state == "ready"


def test_an_archived_and_failed_document_is_retried_once_and_restored(tmp_path: Path) -> None:
    stack = FakeStack()
    doc = stack.add("learner@example.com", REACT, state="failed", archived=True, failure_reason="Bedrock throttled")
    assert _load(stack, tmp_path) == []
    assert stack.retries == 1
    assert not doc.archived and doc.state == "ready"


def test_the_duplicate_check_skips_archived_documents() -> None:
    stack = FakeStack()
    stack.add("learner@example.com", REACT, archived=True)
    tutor = Tutor(stack.client(), "learner@example.com", "learner")
    assert tutor.call("POST", "/documents/duplicate-check", {"sha256": sha256_of(REACT)}) == {"document_id": None}


def test_the_redirect_error_does_not_print_the_authorization_code() -> None:
    stack = FakeStack()
    stack.redirect_to = "http://localhost:9/other"
    tutor = Tutor(stack.client(), "learner@example.com", "learner")
    with pytest.raises(LoadError, match="redirected to http://localhost:9/other,") as error:
        tutor.sign_in()
    assert "code=" not in str(error.value)


def _main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, problems: list[str]) -> int:
    monkeypatch.setattr(learners, "download", lambda wanted, directory: {})
    monkeypatch.setattr(learners, "load_all", lambda *args, **kwargs: problems)
    return learners.main(["--downloads", str(tmp_path)])


def test_main_exits_1_when_a_library_has_problems(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert _main(monkeypatch, tmp_path, ["x"]) == 1


def test_main_exits_0_when_every_library_is_ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert _main(monkeypatch, tmp_path, []) == 0


def test_main_exits_1_when_the_corpus_cannot_be_downloaded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def refuse(wanted: object, directory: object) -> dict[str, Path]:
        raise CorpusError("hash mismatch")

    monkeypatch.setattr(learners, "download", refuse)
    assert learners.main(["--downloads", str(tmp_path)]) == 1


def test_a_ready_document_keeps_its_subjects(tmp_path: Path) -> None:
    stack = FakeStack()
    stack.add("learner@example.com", REACT, state="ready", subjects=["Agents I chose"])
    _load(stack, tmp_path)
    react = next(d for d in stack.library("learner@example.com") if d.sha256 == sha256_of(REACT))
    assert react.subjects == ["Agents I chose"]


def test_a_dropped_connection_while_polling_is_retried(tmp_path: Path) -> None:
    stack = FakeStack()
    stack.process = lambda doc: None  # stays processing until the first poll

    def finish(request: httpx.Request) -> bool:
        for doc in stack.documents.values():
            doc.state = "awaiting_subjects" if doc.state == "processing" else doc.state
        return request.method == "GET"

    stack.disconnects, stack.disconnect_if = 3, finish
    assert _load(stack, tmp_path) == []
    assert all(d.state == "ready" for d in stack.library("learner@example.com"))


def test_a_connection_that_stays_down_while_polling_times_out_naming_the_error(tmp_path: Path) -> None:
    stack = FakeStack()
    stack.disconnects, stack.disconnect_if = 10**9, lambda request: request.url.path.startswith("/uploads/")
    problems = _load(stack, tmp_path, timeout=0.05)
    assert len(problems) == 2
    assert all("timed out" in p and "Server disconnected without sending a response." in p for p in problems)


def test_a_dropped_connection_starting_one_document_is_a_problem_for_that_document_only(tmp_path: Path) -> None:
    stack = FakeStack()
    cot = sha256_of(COT).encode()
    stack.disconnects = 1
    stack.disconnect_if = lambda request: request.url.path == "/documents/duplicate-check" and cot in request.content
    problems = _load(stack, tmp_path)
    assert len(problems) == 1 and problems[0].startswith("cot-2022: ")
    assert [d.state for d in stack.library("learner@example.com")] == ["ready"]
    assert stack.uploads_started == 1


def _load_all(stack: FakeStack, tmp_path: Path, learners: list[Learner]) -> list[str]:
    seeds, paths = _seeds(tmp_path)
    return load_all(
        learners,
        {s.id: s for s in seeds},
        paths,
        connect=stack.client,
        api=API,
        issuer=ISSUER,
        app=APP,
        timeout=5,
        interval=0,
        log=lambda line: None,
    )


def test_each_learner_signs_in_as_themselves(tmp_path: Path) -> None:
    stack = FakeStack()
    learners = [
        Learner("learner@example.com", "learner", ("react-2022",)),
        Learner("learner2@example.com", "learner2", ("cot-2022",)),
    ]
    assert _load_all(stack, tmp_path, learners) == []
    assert [d.sha256 for d in stack.library("learner@example.com")] == [sha256_of(REACT)]
    assert [d.sha256 for d in stack.library("learner2@example.com")] == [sha256_of(COT)]


def test_a_learner_who_cannot_sign_in_is_a_problem_for_that_learner_only(tmp_path: Path) -> None:
    stack = FakeStack()
    learners = [
        Learner("learner@example.com", "wrong", ("react-2022",)),
        Learner("learner2@example.com", "learner2", ("cot-2022",)),
    ]
    problems = _load_all(stack, tmp_path, learners)
    assert len(problems) == 1 and problems[0].startswith("learner@example.com")
    assert [d.state for d in stack.library("learner2@example.com")] == ["ready"]
