"""deploy/on-premise/check-egress.py: the deploy-time proof of the worker's egress block (#153)."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).parents[2] / "deploy/on-premise/check-egress.py"


@pytest.fixture
def check(monkeypatch) -> ModuleType:
    # No .pyc next to the script: test_host.py reads every file under deploy/on-premise as UTF-8 text.
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    spec = importlib.util.spec_from_file_location("check_egress", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_passes_when_blocked_and_the_needed_destinations_answer(check: ModuleType, monkeypatch) -> None:
    monkeypatch.setattr(check, "leaks", lambda: [])
    monkeypatch.setattr(check, "unreachable", lambda: [])
    assert check.main() == 0


def test_a_leak_exits_1_even_when_aws_is_unreachable(check: ModuleType, monkeypatch, capsys) -> None:
    monkeypatch.setattr(check, "leaks", lambda: ["direct 1.1.1.1:443 connected"])
    monkeypatch.setattr(check, "unreachable", lambda: ["sqs: timed out"])
    assert check.main() == 1
    err = capsys.readouterr().err
    assert "direct 1.1.1.1:443 connected" in err and "sqs: timed out" in err


def test_an_unreachable_destination_exits_2(check: ModuleType, monkeypatch, capsys) -> None:
    monkeypatch.setattr(check, "leaks", lambda: [])
    monkeypatch.setattr(check, "unreachable", lambda: ["postgres:5432: refused"])
    assert check.main() == 2
    assert "postgres:5432: refused" in capsys.readouterr().err


def test_leaks_reports_a_direct_connection_and_a_proxy_that_lets_any_host_through(
    check: ModuleType, monkeypatch
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://egress-proxy:3128")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(check, "_connects", lambda host, port: host == "1.1.1.1")
    monkeypatch.setattr(check, "_tunnel_status", lambda host: 200)
    problems = check.leaks()
    assert any("1.1.1.1" in p for p in problems)
    assert any("example.com" in p and "200" in p for p in problems)
    assert not any("sqs.us-east-1.amazonaws.com" in p for p in problems)


def test_leaks_is_empty_when_every_probe_is_refused(check: ModuleType, monkeypatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://egress-proxy:3128")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(check, "_connects", lambda host, port: False)
    monkeypatch.setattr(check, "_tunnel_status", lambda host: 403)
    assert check.leaks() == []


def test_a_crash_is_not_exit_code_2(check: ModuleType, monkeypatch) -> None:
    # deploy.sh keeps the worker running only on 2; a crash must look like a leak (fail closed).
    def boom() -> list[str]:
        raise KeyError("SMART_TUTOR_INGEST_QUEUE_URL")

    monkeypatch.setattr(check, "leaks", lambda: [])
    monkeypatch.setattr(check, "unreachable", boom)
    with pytest.raises(KeyError):
        check.main()  # an uncaught exception exits Python with status 1
