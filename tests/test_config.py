from lingyin_server.config import Settings


def test_mcp_auth_mode_defaults_to_oauth(monkeypatch):
    monkeypatch.delenv("LINGYIN_MCP_AUTH_MODE", raising=False)
    assert Settings.from_env().mcp_auth_mode == "oauth"


def test_mcp_auth_mode_accepts_none(monkeypatch):
    monkeypatch.setenv("LINGYIN_MCP_AUTH_MODE", "none")
    assert Settings.from_env().mcp_auth_mode == "none"


def test_mcp_auth_mode_rejects_unknown_value(monkeypatch):
    monkeypatch.setenv("LINGYIN_MCP_AUTH_MODE", "passwordish")
    try:
        Settings.from_env()
        raise AssertionError("unknown auth mode should fail")
    except ValueError as exc:
        assert "LINGYIN_MCP_AUTH_MODE" in str(exc)
