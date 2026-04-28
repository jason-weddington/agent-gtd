"""Agent GTD FastAPI application."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent_gtd.auth import get_current_user, get_local_user
from agent_gtd.database import close_db, init_db, is_local_mode
from agent_gtd.event_bus import get_event_bus
from agent_gtd.mcp_server import mcp
from agent_gtd.routes.admin_routes import router as admin_router
from agent_gtd.routes.attachment_routes import router as attachment_router
from agent_gtd.routes.auth_routes import router as auth_router
from agent_gtd.routes.comment_routes import router as comment_router
from agent_gtd.routes.dispatch_routes import router as dispatch_router
from agent_gtd.routes.event_routes import router as event_router
from agent_gtd.routes.item_routes import router as item_router
from agent_gtd.routes.note_routes import router as note_router
from agent_gtd.routes.project_routes import router as project_router
from agent_gtd.routes.settings_routes import router as settings_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifecycle: init/close database."""
    import asyncio

    from agent_gtd.dispatch_worker import (
        dispatch_worker,
        reconcile_active_runs,
        shutdown_worker,
    )

    await init_db()
    if is_local_mode():
        _app.dependency_overrides[get_current_user] = get_local_user

    # Start background dispatch worker first (reconciliation may re-enqueue runs)
    worker_task = asyncio.create_task(dispatch_worker())

    # Reconcile runs that were active before the restart
    await reconcile_active_runs()

    yield

    # Shutdown
    worker_task.cancel()
    await shutdown_worker()
    await get_event_bus().drain()
    await close_db()


mcp_app = mcp.http_app(path="/")

app = FastAPI(title="Agent GTD", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://localhost",
        f"https://{os.environ.get('HOSTNAME', 'localhost')}",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_router)
app.include_router(attachment_router)
app.include_router(auth_router)
app.include_router(project_router)
app.include_router(item_router)
app.include_router(note_router)
app.include_router(comment_router)
app.include_router(dispatch_router)
app.include_router(event_router)
app.include_router(settings_router)

app.mount("/mcp", mcp_app)


@app.get("/api/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/api/config")
async def config() -> dict[str, object]:
    """Return app configuration (unauthenticated)."""
    from importlib.metadata import version

    return {"local_mode": is_local_mode(), "version": version("agent_gtd")}
