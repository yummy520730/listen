import os
import subprocess
import sys
import textwrap


PROBE = textwrap.dedent(
    """
    import asyncio
    import httpx

    from lingyin_server.app import OAUTH_PAGE_CSP, app, starlette_app

    async def main():
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "auth-mode-test", "version": "1"},
            },
        }
        async with starlette_app.router.lifespan_context(starlette_app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="https://listen.example") as client:
                response = await client.post(
                    "/mcp",
                    json=request,
                    headers={"Accept": "application/json, text/event-stream"},
                )
                print(response.status_code)
                print(OAUTH_PAGE_CSP)

    asyncio.run(main())
    """
)


def _probe(tmp_path, mode: str) -> tuple[int, str]:
    env = os.environ.copy()
    env.update(
        {
            "LINGYIN_MCP_AUTH_MODE": mode,
            "LINGYIN_ACCESS_TOKEN": "test-owner-password",
            "LINGYIN_PUBLIC_BASE_URL": "https://listen.example",
            "LINGYIN_DATA_DIR": str(tmp_path / mode),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    lines = result.stdout.strip().splitlines()
    return int(lines[-2]), lines[-1]


def test_none_mode_accepts_mcp_without_bearer_token(tmp_path):
    status, _ = _probe(tmp_path, "none")
    assert status == 200


def test_oauth_mode_requires_bearer_token(tmp_path):
    status, csp = _probe(tmp_path, "oauth")
    assert status == 401
    assert "form-action 'self' https://claude.ai https://claude.com" in csp
