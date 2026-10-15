"""YT Analytics Studio API (FastAPI).

Run from apps/api:
    python app.py                                  # honours DEBUG / PORT from the environment
    uvicorn app:app --reload --port 5000           # equivalent, explicit

Interactive API docs are served at /docs while the server runs (unless DOCS_ENABLED=false).
"""
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from errors import register_error_handlers
from routers import analysis, client_data, clients, dashboard, portal, researcher, system, youtube_status
from security import configure_logging, register_security

configure_logging()

app = FastAPI(
    title="YT Analytics Studio API",
    version="0.2.0",
    description="Analyse YouTube Studio exports and research YouTube search results.",
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)

register_security(app)

# The browser normally reaches the API through the Vite dev-server proxy (same origin), so CORS
# only matters for direct calls, and only the configured origins are allowed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

register_error_handlers(app)

for module in (system, dashboard, analysis, researcher, clients, client_data, youtube_status, portal):
    app.include_router(module.router, prefix="/api")
app.include_router(portal.requests_router, prefix="/api")


if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=settings.port, reload=settings.debug)
