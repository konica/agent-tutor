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


@pytest.fixture
def refused(check: ModuleType, monkeypatch) -> ModuleType:
    """Every probe refused, as on the VM; a test lets one through."""
    monkeypatch.setenv("HTTPS_PROXY", "http://egress-proxy:3128")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(check, "_connects", lambda host, port: False)
    monkeypatch.setattr(check, "_resolves", lambda name: False)
    monkeypatch.setattr(check, "_tunnel_status", lambda host, port=443: 403)
    monkeypatch.setattr(check, "_proxied_get_status", lambda url: 403)
    return check


def test_leaks_reports_a_direct_connection_and_a_proxy_that_lets_any_host_through(
    refused: ModuleType, monkeypatch
) -> None:
    monkeypatch.setattr(refused, "_connects", lambda host, port: host == "1.1.1.1")
    monkeypatch.setattr(refused, "_tunnel_status", lambda host, port=443: 200)
    problems = refused.leaks()
    assert any("1.1.1.1" in p for p in problems)
    assert any("example.com" in p and "200" in p for p in problems)
    assert not any("direct sqs.us-east-1.amazonaws.com" in p for p in problems)


def test_leaks_is_empty_when_every_probe_is_refused(refused: ModuleType) -> None:
    assert refused.leaks() == []


def test_leaks_reports_dns_that_resolves(refused: ModuleType, monkeypatch) -> None:
    # The internal network has no external DNS, so a name that resolves is a way out (DNS tunneling).
    monkeypatch.setattr(refused, "_resolves", lambda name: name == "example.com")
    assert refused.leaks() == ["DNS resolved example.com"]


def test_leaks_reports_a_proxy_that_forwards_plain_http(refused: ModuleType, monkeypatch) -> None:
    monkeypatch.setattr(refused, "_proxied_get_status", lambda url: 200 if url == "http://example.com/" else 403)
    assert refused.leaks() == ["the proxy answered 200 to GET http://example.com/, not 403"]


def test_leaks_reports_a_tunnel_to_an_allowed_host_on_another_port(refused: ModuleType, monkeypatch) -> None:
    monkeypatch.setattr(refused, "_tunnel_status", lambda host, port=443: 403 if port == 443 else 200)
    assert refused.leaks() == [
        "the proxy answered 200 to CONNECT sqs.us-east-1.amazonaws.com:80, not 403",
        "the proxy answered 200 to CONNECT api.smith.langchain.com:80, not 403",
    ]


class FakeConnection:
    """Records what a probe sends to the proxy and answers 403."""

    sent: list[tuple[str, int, str, str, dict[str, str]]] = []
    status = 403

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.address = (host, port)

    def request(self, method: str, target: str, headers: dict[str, str] | None = None) -> None:
        FakeConnection.sent.append((*self.address, method, target, headers or {}))

    def getresponse(self) -> "FakeConnection":
        return self

    def close(self) -> None:
        pass


def test_probes_ask_the_proxy_in_proxy_form(check: ModuleType, monkeypatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://egress-proxy:3128")
    monkeypatch.setattr(check.http.client, "HTTPConnection", FakeConnection)
    monkeypatch.setattr(FakeConnection, "sent", [])
    assert check._tunnel_status("sqs.us-east-1.amazonaws.com", 80) == 403
    assert check._proxied_get_status("http://example.com/") == 403
    sqs = "sqs.us-east-1.amazonaws.com:80"
    assert FakeConnection.sent == [
        ("egress-proxy", 3128, "CONNECT", sqs, {"Host": sqs}),
        ("egress-proxy", 3128, "GET", "http://example.com/", {}),  # an absolute URL: a forward-proxy request
    ]


def test_resolves_only_when_getaddrinfo_answers(check: ModuleType, monkeypatch) -> None:
    def no_dns(*args: object) -> None:
        raise check.socket.gaierror(-3, "Temporary failure in name resolution")

    monkeypatch.setattr(check.socket, "getaddrinfo", no_dns)
    assert check._resolves("example.com") is False
    monkeypatch.setattr(check.socket, "getaddrinfo", lambda *args: [("addr",)])
    assert check._resolves("example.com") is True


def test_a_crash_is_not_exit_code_2(check: ModuleType, monkeypatch) -> None:
    # check-worker.sh keeps the worker running only on 2; a crash must look like a leak (fail closed). leaks() lets
    # its errors through (unreachable() reports its own per call, as exit 2).
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(check, "_connects", lambda host, port: False)
    monkeypatch.setattr(check, "_resolves", lambda name: False)
    monkeypatch.setattr(check, "unreachable", lambda: [])
    with pytest.raises(KeyError, match="HTTPS_PROXY"):
        check.main()  # an uncaught exception exits Python with status 1


def test_leaks_reports_a_proxy_that_lets_another_langchain_host_or_port_through(
    refused: ModuleType, monkeypatch
) -> None:
    monkeypatch.setattr(refused, "_tunnel_status", lambda host, port=443: 200 if "langchain" in host else 403)
    problems = refused.leaks()
    assert any("to CONNECT smith.langchain.com:443," in p for p in problems)  # another name of the same service
    assert any("to CONNECT api.smith.langchain.com:80," in p for p in problems)  # the allowed name, wrong port


def test_unreachable_reports_langsmith(check: ModuleType, monkeypatch) -> None:
    def urlopen(url: str, timeout: float) -> None:
        if "smith.langchain.com" in url:
            raise OSError("Tunnel connection failed: 403 Forbidden")
        raise check.urllib.error.HTTPError(url, 404, "nf", {}, None)  # Bedrock answers

    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(check.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(check, "_connects", lambda host, port: True)
    monkeypatch.setattr(check, "_aws_problems", lambda region: [])
    monkeypatch.setenv("LANGSMITH_TRACING", "True")
    assert check.unreachable() == ["LangSmith: Tunnel connection failed: 403 Forbidden"]


@pytest.mark.parametrize("tracing", [None, "false", ""])
def test_unreachable_ignores_langsmith_while_tracing_is_off(check: ModuleType, monkeypatch, tracing) -> None:
    # Tracing is non-critical: a LangSmith outage, or a key not yet created, must not fail a deploy.
    def urlopen(url: str, timeout: float) -> None:
        if "smith.langchain.com" in url:
            raise OSError("unreachable")
        raise check.urllib.error.HTTPError(url, 404, "nf", {}, None)

    monkeypatch.setenv("AWS_REGION", "us-east-1")
    if tracing is None:
        monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    else:
        monkeypatch.setenv("LANGSMITH_TRACING", tracing)
    monkeypatch.setattr(check.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(check, "_connects", lambda host, port: True)
    monkeypatch.setattr(check, "_aws_problems", lambda region: [])
    assert check.unreachable() == []
