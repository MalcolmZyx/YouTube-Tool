"""Request-level protections for an API that runs on the same machine as a web browser.

A local server is still reachable by every web page the user opens. Two attacks matter:

* Cross-site requests (CSRF). A page on another site can make the browser send a form-style
  POST to http://localhost:5000 without any CORS preflight. CORS only stops the page from
  *reading* the answer; the request is still processed. The origin guard below rejects
  state-changing requests whose Origin header is not one of ours.
* DNS rebinding. A hostile domain can be pointed at 127.0.0.1 so the browser treats our API as
  "same site". Those requests still carry the hostile host name, so only known hosts are served.
"""
import logging
import re

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from config import settings

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Room for multipart framing around the file itself.
_MULTIPART_OVERHEAD = 64 * 1024


def register_security(app: FastAPI) -> None:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)

    @app.middleware("http")
    async def origin_guard(request: Request, call_next):
        origin = request.headers.get("origin")
        # Non-browser clients (curl, tests, scripts) send no Origin and are not affected.
        if request.method not in _SAFE_METHODS and origin and origin not in settings.cors_origin_list:
            return JSONResponse({"error": "Origin not allowed"}, status_code=403)
        return await call_next(request)

    @app.middleware("http")
    async def reject_oversized_bodies(request: Request, call_next):
        # Cheap early refusal based on the declared size. The upload route enforces the same
        # limit again while copying, because a client can lie about or omit Content-Length.
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > settings.max_upload_bytes + _MULTIPART_OVERHEAD:
            return JSONResponse(
                {"error": f"Request too large. Maximum upload is {settings.max_upload_mb} MB."}, status_code=413
            )
        return await call_next(request)


class RedactingFormatter(logging.Formatter):
    """Log formatter that hides API keys.

    Google's APIs take the key as a `key=...` URL parameter, so any logged request URL or
    traceback from an HTTP library can contain it.
    """

    _KEY_PARAM = re.compile(r"(\bkey=)[^&\s'\"]+")

    def format(self, record: logging.LogRecord) -> str:
        return self._KEY_PARAM.sub(r"\1<redacted>", super().format(record))


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
