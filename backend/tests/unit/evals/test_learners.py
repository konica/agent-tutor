"""Loading the eval learners' libraries (issue #222): which documents each learner holds, signing in, the API."""

from pathlib import Path

import pytest

from evals.corpus import load_manifest
from evals.learners import LEARNERS, LoadError, Tutor, load_learners
from fakes.evals_stack import FakeStack


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
