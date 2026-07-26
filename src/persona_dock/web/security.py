from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from typing import Any

ASGIApp = Callable[[dict[str, Any], Callable[[], Awaitable[dict[str, Any]]], Callable[[dict[str, Any]], Awaitable[None]]], Awaitable[None]]


SECURITY_HEADERS = (
    (b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; frame-src 'none'; base-uri 'self'; form-action 'self'"),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=(), usb=()"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"x-permitted-cross-domain-policies", b"none"),
)


def configured_body_limit() -> int:
    raw = os.environ.get("PERSONADOCK_WEB_MAX_BODY_BYTES", "25165824")
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError("PERSONADOCK_WEB_MAX_BODY_BYTES must be an integer") from error
    if not 1024 * 1024 <= value <= 128 * 1024 * 1024:
        raise ValueError("PERSONADOCK_WEB_MAX_BODY_BYTES must be between 1 MiB and 128 MiB")
    return value


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path") or "")

        async def secure_send(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers") or [])
                existing = {key.lower() for key, _ in headers}
                for key, value in SECURITY_HEADERS:
                    if key not in existing:
                        headers.append((key, value))
                if path.startswith("/api/") and b"cache-control" not in existing:
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, secure_send)


class RequestSizeLimitMiddleware:
    METHODS_WITH_BODY = {"POST", "PUT", "PATCH"}

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = int(max_body_bytes)

    @staticmethod
    async def _reject(send, limit: int) -> None:
        body = json.dumps(
            {
                "detail": f"request body exceeds PersonaDock Web limit of {limit} bytes"
            },
            separators=(",", ":"),
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http" or scope.get("method") not in self.METHODS_WITH_BODY:
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers") or []}
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                if int(content_length) > self.max_body_bytes:
                    await self._reject(send, self.max_body_bytes)
                    return
            except ValueError:
                await self._reject(send, self.max_body_bytes)
                return

        buffered: list[dict[str, Any]] = []
        size = 0
        while True:
            message = await receive()
            buffered.append(message)
            if message.get("type") == "http.request":
                size += len(message.get("body") or b"")
                if size > self.max_body_bytes:
                    await self._reject(send, self.max_body_bytes)
                    return
                if not message.get("more_body", False):
                    break
            else:
                break
        cursor = 0

        async def replay_receive() -> dict[str, Any]:
            nonlocal cursor
            if cursor < len(buffered):
                message = buffered[cursor]
                cursor += 1
                return message
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)


__all__ = [
    "RequestSizeLimitMiddleware",
    "SECURITY_HEADERS",
    "SecurityHeadersMiddleware",
    "configured_body_limit",
]
