# app/main.py
"""
FastAPI application entrypoint: CORS, router registration, and a background
ingestion loop started via the lifespan context manager.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import AsyncSessionLocal, engine
from app.routers import watchlist
from app.services.market_data import fetch_and_store_snapshots

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app.main")

INGESTION_INTERVAL_SECONDS = int(os.getenv("INGESTION_INTERVAL_SECONDS", "60"))

_raw_origins = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]


async def _ingestion_loop() -> None:
    """
    Runs fetch_and_store_snapshots on a fixed interval for the app's
    lifetime. Each cycle is wrapped in its own try/except: a single bad
    cycle must not kill this loop silently and stop ALL future ingestion.
    """
    while True:
        try:
            async with AsyncSessionLocal() as session:
                await fetch_and_store_snapshots(session)
            logger.info("Ingestion cycle completed")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ingestion cycle failed; will retry next interval")
        await asyncio.sleep(INGESTION_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_ingestion_loop())
    logger.info("Started market data ingestion loop (interval=%ss)", INGESTION_INTERVAL_SECONDS)
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await engine.dispose()
        logger.info("Ingestion loop stopped, engine disposed")


app = FastAPI(title="Smart Market Watchlist", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

app.include_router(watchlist.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}