import pytest

from smart_tutor.shared.domain.token_usage import TokenUsage


def test_usage_adds_up() -> None:
    total = TokenUsage(input_tokens=100, output_tokens=20) + TokenUsage(input_tokens=5, output_tokens=1)

    assert total == TokenUsage(input_tokens=105, output_tokens=21)
    assert total.total_tokens == 126


def test_negative_counts_are_rejected() -> None:
    with pytest.raises(ValueError):
        TokenUsage(input_tokens=-1)


def test_usage_from_langchain_metadata() -> None:
    metadata = {"input_tokens": 2054, "output_tokens": 20, "total_tokens": 2074, "input_token_details": {}}

    assert TokenUsage.from_usage_metadata(metadata) == TokenUsage(input_tokens=2054, output_tokens=20)
    assert TokenUsage.from_usage_metadata(None) == TokenUsage()
