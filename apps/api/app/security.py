"""Bound actual request bytes, including chunked uploads, before body parsers run."""

from collections import deque
from fastapi.responses import JSONResponse
from rag_runtime.errors import Problem


class BoundedBody:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] not in {"POST", "PUT", "PATCH"}
            or not scope["path"].startswith("/api/")
        ):
            return await self.app(scope, receive, send)
        limit = 21 * 1024 * 1024 if scope["path"].endswith("/sources/upload") else 256 * 1024
        headers = dict(scope.get("headers", []))
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = limit + 1
        messages = deque()
        count = 0
        if declared <= limit:
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                count += len(message.get("body", b""))
                if count > limit:
                    break
                messages.append(message)
                if not message.get("more_body", False):

                    async def replay():
                        return messages.popleft() if messages else await receive()

                    return await self.app(scope, replay, send)
        response = JSONResponse(
            dict(
                error=Problem(
                    "REQUEST_TOO_LARGE", "This request exceeds the allowed body size.", 413
                ).public()
            ),
            413,
        )
        await response(scope, receive, send)
