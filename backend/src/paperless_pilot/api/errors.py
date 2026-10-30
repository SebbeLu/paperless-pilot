"""Übersetzt Domänenfehler in HTTP-Antworten mit verständlicher Meldung."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from paperless_pilot.domain.errors import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PilotError,
    ServiceUnavailableError,
)

_STATUS: list[tuple[type[PilotError], int]] = [
    (NotFoundError, 404),
    (ConflictError, 409),
    (AuthenticationError, 502),
    (ServiceUnavailableError, 503),
]


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(PilotError)
    async def _handle(_request: Request, exc: PilotError) -> JSONResponse:
        status = next((code for kind, code in _STATUS if isinstance(exc, kind)), 400)
        body: dict[str, object] = {"detail": str(exc)}
        if isinstance(exc, ConflictError):
            body["conflict"] = exc.fields
        return JSONResponse(status_code=status, content=body)
