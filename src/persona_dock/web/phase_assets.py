from __future__ import annotations

from importlib.resources import files

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

_ASSETS = {
    "editor.css": "text/css; charset=utf-8",
    "editor.js": "text/javascript; charset=utf-8",
}


def register_phase_asset_routes(app: FastAPI) -> None:
    @app.get("/assets/phase/{asset_name}", include_in_schema=False)
    def phase_asset(asset_name: str) -> Response:
        media_type = _ASSETS.get(asset_name)
        if media_type is None:
            raise HTTPException(status_code=404, detail="asset not found")
        content = files("persona_dock.web.static").joinpath(asset_name).read_text(encoding="utf-8")
        return Response(content, media_type=media_type, headers={"Cache-Control": "no-cache"})


__all__ = ["register_phase_asset_routes"]
