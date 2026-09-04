"""ASGI entrypoint."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.routes import router
from app.core.config import settings

app = FastAPI(title=settings.app_name, version=settings.version, docs_url="/docs")
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api")


@app.get("/")
async def root() -> dict:
    return {"service": settings.app_name, "docs": "/docs", "api": "/api/health"}
