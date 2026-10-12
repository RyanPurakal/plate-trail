"""FastAPI application.

Endpoints for cameras, simulation, and runs are added in step 8. Heavy work
will later move behind a job queue; the API itself stays thin.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from platetrail.config import get_settings
from platetrail.db import apply_migrations, get_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    apply_migrations(get_engine())
    yield


app = FastAPI(title="Plate Trail API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    with get_engine().connect() as conn:
        postgis = conn.execute(text("SELECT postgis_lib_version()")).scalar_one()
    return {"status": "ok", "postgis": postgis}
