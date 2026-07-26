from __future__ import annotations

import asyncio
from importlib.resources import files

from persona_dock.web import create_app
from persona_dock.web.capabilities import capability_summary
from persona_dock.web.parity import parity_report, validate_cli_web_parity
from persona_dock.web.security import (
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from persona_dock.web.version import WEB_REFACTOR_PHASE


def _run_asgi(app, scope, incoming):
    sent = []
    values = list(incoming)

    async def receive():
        if values:
            return values.pop(0)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return sent


def test_security_headers_are_added_to_api_responses() -> None:
    async def endpoint(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b"{}"})

    sent = _run_asgi(
        SecurityHeadersMiddleware(endpoint),
        {"type": "http", "method": "GET", "path": "/api/v1/meta", "headers": []},
        [],
    )
    headers = dict(sent[0]["headers"])
    assert b"default-src 'self'" in headers[b"content-security-policy"]
    assert headers[b"x-frame-options"] == b"DENY"
    assert headers[b"x-content-type-options"] == b"nosniff"
    assert headers[b"cache-control"] == b"no-store"
    assert b"camera=()" in headers[b"permissions-policy"]


def test_request_size_limit_rejects_content_length_and_streamed_body() -> None:
    called = []

    async def endpoint(scope, receive, send):
        called.append(True)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = RequestSizeLimitMiddleware(endpoint, max_body_bytes=8)
    sent = _run_asgi(
        middleware,
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/test",
            "headers": [(b"content-length", b"9")],
        },
        [],
    )
    assert sent[0]["status"] == 413
    assert called == []

    sent = _run_asgi(
        middleware,
        {"type": "http", "method": "POST", "path": "/api/v1/test", "headers": []},
        [
            {"type": "http.request", "body": b"12345", "more_body": True},
            {"type": "http.request", "body": b"6789", "more_body": False},
        ],
    )
    assert sent[0]["status"] == 413
    assert called == []


def test_request_size_limit_replays_allowed_body() -> None:
    received = []

    async def endpoint(scope, receive, send):
        while True:
            message = await receive()
            received.append(message)
            if message.get("type") != "http.request" or not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    sent = _run_asgi(
        RequestSizeLimitMiddleware(endpoint, max_body_bytes=8),
        {"type": "http", "method": "POST", "path": "/api/v1/test", "headers": []},
        [{"type": "http.request", "body": b"12345678", "more_body": False}],
    )
    assert sent[0]["status"] == 200
    assert received[0]["body"] == b"12345678"


def test_cli_web_parity_is_complete_and_no_capability_is_planned() -> None:
    assert validate_cli_web_parity() == []
    report = parity_report()
    assert report["complete"] is True
    assert report["commands"] == report["mapped_commands"]
    assert capability_summary()["planned"] == 0


def test_phase_eight_routes_version_and_security_sources() -> None:
    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/api/v1/parity" in paths
    assert WEB_REFACTOR_PHASE == 8

    root = files("persona_dock")
    app_source = root.joinpath("web/app.py").read_text(encoding="utf-8")
    wrapper_source = root.joinpath("web/__init__.py").read_text(encoding="utf-8")
    security_source = root.joinpath("web/security.py").read_text(encoding="utf-8")
    parity_source = root.joinpath("web/parity.py").read_text(encoding="utf-8")

    assert "hmac.compare_digest" in app_source
    assert "hmac.compare_digest" in wrapper_source
    assert "content-security-policy" in security_source
    assert "PERSONADOCK_WEB_MAX_BODY_BYTES" in security_source
    assert "stable_cli.build_parser()" in parity_source
