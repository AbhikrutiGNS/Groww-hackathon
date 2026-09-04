# app/services/ticker_registry.py
"""
Resolves a raw ticker symbol against yfinance and lazily creates the
`tickers` master row on first sight, so the app supports "add any real
ticker" rather than only a hand-seeded list.

Call this BEFORE inserting a row that FKs to tickers.symbol (watchlist_items,
holding_transactions) and do it in the same transaction as that insert:
either both land or neither does.

Concurrency note: this module never calls db.commit(). The caller commits
once, after its own dependent insert, inside the same transaction. Two
concurrent requests racing to create the same new ticker are resolved by
ON CONFLICT DO NOTHING below, not by a check-then-insert race.
"""
from __future__ import annotations

import asyncio
import logging

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticker

logger = logging.getLogger("ticker_registry")


class UnresolvableTickerError(Exception):
    """Raised when a symbol doesn't correspond to a real, tradeable
    instrument yfinance can return data for."""


def _blocking_resolve(symbol: str) -> tuple[str, str] | None:
    """Fully synchronous — must only ever be called via asyncio.to_thread.

    Returns (company_name, exchange) or None if the symbol can't be
    resolved. Mirrors the fast_info-then-history fallback pattern used in
    market_data.py: fast_info is a lazy proxy that can itself raise on a
    symbol Yahoo doesn't recognize, so we don't let that exception alone
    decide validity — we also check that a price actually comes back.
    """
    ticker = yf.Ticker(symbol)

    try:
        info = ticker.fast_info
        last_price = getattr(info, "last_price", None)
        has_price = last_price is not None and last_price == last_price and last_price > 0
    except Exception:
        has_price = False

    if not has_price:
        try:
            hist = ticker.history(period="5d")
            has_price = not hist.empty
        except Exception:
            has_price = False

    if not has_price:
        return None

    company_name = symbol
    exchange = "UNKNOWN"
    try:
        meta = ticker.get_info() if hasattr(ticker, "get_info") else ticker.info
        company_name = meta.get("longName") or meta.get("shortName") or symbol
        exchange = meta.get("exchange") or exchange
    except Exception:
        # Fine to proceed with placeholders — a resolvable price is what
        # actually matters for "can this be tracked"; display metadata is
        # best-effort and gets filled in properly by the fundamentals job.
        logger.info("Could not fetch metadata for %s; using placeholders", symbol)

    return company_name, exchange


async def ensure_ticker_exists(db: AsyncSession, symbol: str) -> None:
    existing = await db.execute(select(Ticker.symbol).where(Ticker.symbol == symbol))
    if existing.scalar_one_or_none() is not None:
        return

    resolved = await asyncio.to_thread(_blocking_resolve, symbol)
    if resolved is None:
        raise UnresolvableTickerError(symbol)

    company_name, exchange = resolved
    stmt = (
        pg_insert(Ticker)
        .values(symbol=symbol, company_name=company_name, exchange=exchange)
        .on_conflict_do_nothing(index_elements=["symbol"])
    )
    await db.execute(stmt)