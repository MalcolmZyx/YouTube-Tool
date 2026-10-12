"""Error handling.

The frontend reads `response.data.error` (see apps/web/src/hooks/useApi.js), so every failure
is returned as {"error": "<message>"}, whether it came from our code, from request
validation or from an unexpected crash. FastAPI's default {"detail": ...} shape is replaced.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


def _validation_message(exc: RequestValidationError) -> str:
    parts = []
    for err in exc.errors():
        # Skip the leading "body"/"query" marker so the message reads "max_results: ...".
        location = ".".join(str(p) for p in err["loc"] if p not in ("body", "query", "form"))
        parts.append(f"{location}: {err['msg']}" if location else err["msg"])
    return "; ".join(parts) or "Invalid request"


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Only field names and messages are returned, never the submitted values.
        return JSONResponse({"error": _validation_message(exc)}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Full details go to the log; the client gets a generic message so internals
        # (paths, request URLs that may embed an API key) never reach the browser.
        logger.exception("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
        return JSONResponse({"error": "Internal server error"}, status_code=500)
