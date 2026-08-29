"""FastAPI application. Serves the API and the read-only dashboard."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from natilah import __version__
from natilah.api.routes import analysis, dashboard, ingestion, opportunities
from natilah.config import settings
from natilah.models.database import init_db

logger = logging.getLogger("natilah")
ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "dashboard"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    await init_db()
    logger.info("Natilah V1 ready (safety_mode=%s)", settings.safety_mode)
    yield


app = FastAPI(
    title="Natilah",
    description=(
        "Read-only AI infrastructure intelligence. Observes existing GPU allocation "
        "decisions, reconstructs context, and quantifies the value of feasible "
        "counterfactual alternatives. Does not modify infrastructure."
    ),
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router)
app.include_router(opportunities.router)
app.include_router(ingestion.router)
app.include_router(analysis.router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "safety_mode": settings.safety_mode, "version": __version__}


if DASHBOARD.exists():
    app.mount("/", StaticFiles(directory=str(DASHBOARD), html=True), name="dashboard")
