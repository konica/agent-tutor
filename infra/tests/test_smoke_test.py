"""The post-deploy smoke test (deploy/pilot/smoke_test.py) against a local fake of the public address."""

import importlib.util
import json
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).parents[2] / "deploy/pilot/smoke_test.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("smoke_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = load()

Route = tuple[int, dict[str, str], bytes]


def healthy(base: str) -> dict[str, Route]:
    issuer = f"{base}/auth/realms/smart-tutor"
    return {
        "/": (
            200,
            {"Content-Type": "text/html"},
            b'<html><body><div id="root"></div></body></html>',
        ),
        "/api/healthz": (200, {"Content-Type": "application/json"}, b'{"status":"ok"}'),
        "/api/me": (
            401,
            {"WWW-Authenticate": "Bearer", "Content-Type": "application/json"},
            b'{"detail":"x"}',
        ),
        "/auth/realms/smart-tutor/.well-known/openid-configuration": (
            200,
            {"Content-Type": "application/json"},
            json.dumps({"issuer": issuer}).encode(),
        ),
    }


@pytest.fixture
def site() -> Iterator[tuple[str, Callable[[dict[str, Route]], None], list[str]]]:
    """A local server whose routes the test sets; it records whether any request carried Authorization."""
    routes: dict[str, Route] = {}
    auth_seen: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.headers.get("Authorization"):
                auth_seen.append(self.path)
            status, headers, body = routes.get(self.path, (404, {}, b""))
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"

    def set_routes(new: dict[str, Route]) -> None:
        routes.clear()
        routes.update(new)

    yield base, set_routes, auth_seen
    server.shutdown()


def test_healthy_site_passes(site) -> None:
    base, set_routes, auth_seen = site
    set_routes(healthy(base))
    assert smoke.run_checks(base) == []
    assert auth_seen == []  # the smoke test never sends a token


def test_trailing_slash_in_url_is_ignored(site) -> None:
    base, set_routes, _ = site
    set_routes(healthy(base))
    assert smoke.run_checks(base + "/") == []


def test_wrong_issuer_fails(site) -> None:
    base, set_routes, _ = site
    routes = healthy(base)
    routes["/auth/realms/smart-tutor/.well-known/openid-configuration"] = (
        200,
        {"Content-Type": "application/json"},
        json.dumps({"issuer": "http://internal-alb/auth/realms/smart-tutor"}).encode(),
    )
    set_routes(routes)
    failures = smoke.run_checks(base)
    assert len(failures) == 1 and "issuer" in failures[0]


def test_api_me_must_challenge_with_bearer(site) -> None:
    base, set_routes, _ = site
    routes = healthy(base)
    routes["/api/me"] = (401, {}, b"")  # no WWW-Authenticate
    set_routes(routes)
    failures = smoke.run_checks(base)
    assert len(failures) == 1 and "/api/me" in failures[0]


def test_api_me_answering_200_without_token_fails(site) -> None:
    base, set_routes, _ = site
    routes = healthy(base)
    routes["/api/me"] = (200, {"Content-Type": "application/json"}, b"{}")
    set_routes(routes)
    assert any("/api/me" in f for f in smoke.run_checks(base))


def test_web_without_app_shell_fails(site) -> None:
    base, set_routes, _ = site
    routes = healthy(base)
    routes["/"] = (200, {"Content-Type": "text/html"}, b"<html>maintenance</html>")
    set_routes(routes)
    assert any(f.startswith("/ ") or "app shell" in f for f in smoke.run_checks(base))


def test_unreachable_site_reports_every_check() -> None:
    failures = smoke.run_checks(
        "http://127.0.0.1:9"
    )  # nothing listens on the discard port
    assert len(failures) == 4


def test_retries_until_the_site_settles(site) -> None:
    base, set_routes, _ = site
    set_routes({p: (502, {}, b"") for p in healthy(base)})
    timer = threading.Timer(0.5, lambda: set_routes(healthy(base)))
    timer.start()
    assert (
        smoke.main([base, "--deadline-seconds", "10", "--interval-seconds", "0.2"]) == 0
    )


def test_gives_up_with_the_failing_checks(site, capsys) -> None:
    base, set_routes, _ = site
    set_routes({p: (503, {}, b"") for p in healthy(base)})
    assert (
        smoke.main([base, "--deadline-seconds", "0.5", "--interval-seconds", "0.1"])
        == 1
    )
    out = capsys.readouterr().out
    assert "/api/me" in out and "openid-configuration" in out
