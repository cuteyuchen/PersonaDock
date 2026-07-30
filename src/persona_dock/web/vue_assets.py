from __future__ import annotations

import mimetypes
from importlib.resources import files
from pathlib import PurePosixPath

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response


_CACHE_HEADERS = {"Cache-Control": "no-cache"}


def _root():
    return files("persona_dock.web.static").joinpath("vue")


def _vue_index() -> HTMLResponse:
    index = _root().joinpath("index.html")
    if not index.is_file():
        raise HTTPException(status_code=503, detail="Vue frontend has not been built")
    return HTMLResponse(index.read_text(encoding="utf-8"), headers=_CACHE_HEADERS)


def _legacy_index() -> HTMLResponse:
    index = files("persona_dock.web.static").joinpath("index.html")
    if not index.is_file():
        raise HTTPException(status_code=404, detail="Legacy frontend is unavailable")
    return HTMLResponse(index.read_text(encoding="utf-8"), headers=_CACHE_HEADERS)


def _safe_parts(asset_path: str) -> tuple[str, ...]:
    path = PurePosixPath(asset_path)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise HTTPException(status_code=404, detail="Vue asset not found")
    return tuple(path.parts)


def register_vue_asset_routes(app: FastAPI) -> None:
    # The base application registers the former native frontend at /. Remove only
    # that GET route and keep all legacy API/static routes for one compatibility cycle.
    app.router.routes = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == "/"
            and "GET" in getattr(route, "methods", set())
        )
    ]

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def vue_root() -> HTMLResponse:
        return _vue_index()

    @app.get("/vue", response_class=HTMLResponse, include_in_schema=False)
    def vue_alias() -> HTMLResponse:
        return _vue_index()

    @app.get("/legacy", response_class=HTMLResponse, include_in_schema=False)
    def legacy_index() -> HTMLResponse:
        return _legacy_index()

    @app.get("/assets/vue/{asset_path:path}", include_in_schema=False)
    def vue_asset(asset_path: str) -> Response:
        candidate = _root().joinpath(*_safe_parts(asset_path))
        if not candidate.is_file():
            raise HTTPException(status_code=404, detail="Vue asset not found")
        media_type, _ = mimetypes.guess_type(asset_path)
        return Response(
            candidate.read_bytes(),
            media_type=media_type or "application/octet-stream",
            headers=_CACHE_HEADERS,
        )


__all__ = ["register_vue_asset_routes"]
