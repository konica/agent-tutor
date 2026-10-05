from typing import Any

import pytest

from smart_tutor.apps.mcp_server import server


def test_listens_on_the_configured_port(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(server.mcp, "run", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setenv("SMART_TUTOR_MCP_PORT", "10452")

    server.main()

    assert calls == [{"transport": "streamable-http", "host": "0.0.0.0", "port": 10452}]
