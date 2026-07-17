from __future__ import annotations

import secrets
from urllib.parse import parse_qs


class TokenAuthMiddleware:
    """Small ASGI auth layer for both REST and MCP endpoints."""

    def __init__(self, app, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") in {"/", "/healthz"}:
            await self.app(scope, receive, send)
            return

        if not self.token:
            await self._reject(send, 503, b"LINGYIN_ACCESS_TOKEN is not configured")
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        header_token = headers.get(b"x-api-key", b"").decode("latin-1")
        if authorization.lower().startswith("bearer "):
            header_token = authorization[7:].strip()
        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        query_token = (query.get("token") or [""])[0]
        supplied = header_token or query_token

        if not supplied or not secrets.compare_digest(supplied, self.token):
            await self._reject(send, 401, b"Unauthorized")
            return
        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(send, status: int, body: bytes):
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"cache-control", b"no-store"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

