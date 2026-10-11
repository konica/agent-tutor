"""The Bedrock model IDs that IAM grants match the ones the backend calls."""

from pathlib import Path

from smart_tutor_infra.models import AGENT_PROFILE, EMBEDDING_MODEL, JUDGE_MODEL

CONFIG = Path(__file__).parents[2] / "backend/src/smart_tutor/shared/config.py"


def test_iam_models_match_the_backend_config() -> None:
    text = CONFIG.read_text(encoding="utf-8")
    assert f'"{AGENT_PROFILE}"' in text
    assert f'"{EMBEDDING_MODEL}"' in text
    assert f'"{JUDGE_MODEL}"' in text
