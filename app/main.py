"""
Main entry point for the Helix SROP (Stateful RAG Orchestration Pipeline) FastAPI application.
Handles application lifecycle, database initialization, and routing for Chat, Sessions, and Traces.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.api import routes_sessions, routes_chat, routes_traces, routes_rag
from app.db.session import init_db
from app.obs.logging import configure_logging
from app.settings import settings
from app.api.errors import HelixError, helix_error_handler
import os

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup and shutdown events.
    Initializes the database and configures logging.
    """
    # Ensure the Google API Key from settings is available in the environment
    os.environ["GOOGLE_API_KEY"] = settings.google_api_key
    configure_logging()
    await init_db()
    yield

app = FastAPI(title="Helix SROP", version="0.1.0", lifespan=lifespan)

# Static files for the frontend
static_dir = os.path.join(os.path.dirname(__file__), "static")

@app.get("/")
async def read_index():
    return FileResponse(os.path.join(static_dir, "index.html"))

app.include_router(routes_sessions.router, prefix="/v1")
app.include_router(routes_chat.router, prefix="/v1")
app.include_router(routes_traces.router, prefix="/v1")
app.include_router(routes_rag.router, prefix="/v1")

app.mount("/static", StaticFiles(directory=static_dir), name="static")

app.add_exception_handler(HelixError, helix_error_handler)

@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
