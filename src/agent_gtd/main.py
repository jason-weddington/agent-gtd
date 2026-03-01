"""Agent GTD FastAPI application."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent_gtd.database import close_db, init_db
from agent_gtd.routes.auth_routes import router as auth_router
from agent_gtd.routes.item_routes import router as item_router
from agent_gtd.routes.note_routes import router as note_router
from agent_gtd.routes.project_routes import router as project_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifecycle: init/close database."""
    await init_db()
    yield
    await close_db()


app = FastAPI(title="Agent GTD", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(project_router)
app.include_router(item_router)
app.include_router(note_router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
