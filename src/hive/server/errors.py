"""Map Hive domain errors to HTTP responses."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hive.errors import AgentNotFoundError, HiveError, ProfileNotFoundError

if TYPE_CHECKING:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse


def register_error_handlers(app: FastAPI) -> None:
    from fastapi.responses import JSONResponse

    async def not_found(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    async def bad_request(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    app.add_exception_handler(AgentNotFoundError, not_found)
    app.add_exception_handler(ProfileNotFoundError, not_found)
    app.add_exception_handler(HiveError, bad_request)
