"""YT Analytics Studio API (FastAPI).

Run from apps/api:
    python app.py                                  # honours DEBUG / PORT from the environment
    uvicorn app:app --reload --port 5000           # equivalent, explicit

Interactive API docs are served at /docs while the server runs.
"""
import logging

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from errors import register_error_handlers
from routers import analysis, dashboard, researcher, system

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="YT Analytics Studio API",
    version="0.2.0",
    description="Analyse YouTube Studio exports and research YouTube search results.",
)

# The browser normally reaches the API through the Vite dev-server proxy (same origin), so CORS
# only matters for direct calls, and only the configured origins are allowed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

register_error_handlers(app)

for module in (system, dashboard, analysis, researcher):
    app.include_router(module.router, prefix="/api")


if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=settings.port, reload=settings.debug)
