"""
RecoverOS API.

Thin by design: every endpoint is a read or a trigger, and all the logic lives
in `app/core` and `app/analytics` where it can be tested without HTTP.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (audit, batch, cases, health, ingest, live, llm, metrics,
                     queue, timeline)
from app.db import Base, engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    """
    Create tables if they are missing.

    Render's free tier has an ephemeral filesystem, so the committed demo.db can
    disappear on a restart. Recreating the schema means the API comes back up
    with empty tables and a working /api/health instead of 500s on every route.
    """
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="RecoverOS",
    description=(
        "Failed-payment recovery with bounded, audited, measured interventions. "
        "The LLM never touches a rupee."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Set on day one rather than on deploy day. A CORS failure looks exactly like a
# dead backend from the browser, and debugging it against a cold free-tier
# instance an hour before a deadline is a bad way to spend that hour.
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",") if o.strip()
]
if os.environ.get("VERCEL_URL"):
    ALLOWED_ORIGINS.append(f"https://{os.environ['VERCEL_URL']}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(metrics.router)
app.include_router(timeline.router)
app.include_router(cases.router)
app.include_router(batch.router)
app.include_router(audit.router)
app.include_router(llm.router)
app.include_router(live.router)
app.include_router(ingest.router)
app.include_router(queue.router)


@app.get("/")
def root():
    return {
        "name": "RecoverOS",
        "thesis": "The LLM never touches a rupee.",
        "docs": "/docs",
        "start_here": ["/api/health", "/api/metrics/summary", "/api/audit/verify"],
    }
