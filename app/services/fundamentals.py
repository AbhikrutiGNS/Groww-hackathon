# app/services/fundamentals.py
"""
Fundamentals ingestion: market cap, PE, PB, EPS, ROE, ROCE, debt/equity,
dividend yield. Deliberately separate from market_data.py's price polling —

- Fundamentals change quarterly-ish, not every 60s. Polling them at the same
  cadence as price is wasted calls and needless yfinance load.
- company_fundamentals is a single upserted row per symbol, not an append-only
  series like stock_snapshots. Every refresh overwrites, it never accumulates.

Same two load-bearing rules as market_data.py, and for the same reasons:
1. Bounded concurrency on the blocking yfinance call (ticker.info / get_info
   is a much heavier request than fast_info — more reason to cap it).
2. AsyncSession is never touched inside the concurrent fetch phase; all
   network I/O happens first via asyncio.to_thread, DB writes happen after,
   sequentially, on the single session.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CompanyFundamental, Ticker

logger = logging.getLogger("fundamentals")

_MAX_CONCURRENT_FETCHES = 3  # ticker.info is heavier/slower than fast_info — stay conservative


class FetchedFundamentals:
    __slots__ = (
        "market_cap", "pe_ratio", "pb_ratio", "eps", "roe", "roce",
        "debt_to_equity", "dividend_yield",
    )

    def __init__(self, **kwargs):
        for slot in self.__slots__:
            setattr(self, slot, kwargs.get(slot))


def _to_decimal(value, max_digits: int, decimal_places: int) -> Optional[Decimal]:
    """yfinance returns plain floats/None/NaN; DB columns are fixed-precision
    Numeric. Silently drop anything that can't be represented rather than
    letting one bad field 500 the whole upsert — a missing metric is a
    normal state (see AttentionFeedItem's own null-handling philosophy),
    a crash on insert is not."""
    if value is None:
        return None
    try:
        if value != value:  # NaN
            return None
        d = Decimal(str(value)).quantize(Decimal(1).scaleb(-decimal_places))
        # reject if it wouldn't fit the column (max_digits total, decimal_places after point)
        int_digits = max_digits - decimal_places
        if abs(d) >= Decimal(10) ** int_digits:
            return None
        return d
    except (InvalidOperation, ValueError, OverflowError):
        return None


def _blocking_fetch_fundamentals(symbol: str) -> Optional[FetchedFundamentals]:
    """Fully synchronous — must only ever be called via asyncio.to_thread."""
    ticker = yf.Ticker(symbol)
    try:
        info = ticker.get_info() if hasattr(ticker, "get_info") else ticker.info
    except Exception:
        logger.warning("fundamentals fetch failed for %s", symbol)
        return None

    if not info:
        return None

    # ROCE isn't a standard yfinance field (it's an Indian-markets-style
    # metric); approximate as EBIT / (total assets - current liabilities)
    # when the raw pieces are available, otherwise leave it null rather
    # than guess.
    roce = None
    try:
        ebit = info.get("ebitda")  # yfinance doesn't expose EBIT directly; ebitda is the closest proxy
        total_assets = info.get("totalAssets")
        current_liabilities = info.get("totalCurrentLiabilities")
        if ebit and total_assets and current_liabilities and (total_assets - current_liabilities) > 0:
            roce = (ebit / (total_assets - current_liabilities)) * 100
    except Exception:
        roce = None

    dividend_yield = info.get("dividendYield")
    if dividend_yield is not None:
        dividend_yield = dividend_yield * 100 if dividend_yield < 1 else dividend_yield

    return FetchedFundamentals(
        market_cap=info.get("marketCap"),
        pe_ratio=info.get("trailingPE") or info.get("forwardPE"),
        pb_ratio=info.get("priceToBook"),
        eps=info.get("trailingEps"),
        roe=(info.get("returnOnEquity") * 100) if info.get("returnOnEquity") is not None else None,
        roce=roce,
        debt_to_equity=(info.get("debtToEquity") / 100) if info.get("debtToEquity") is not None else None,
        dividend_yield=dividend_yield,
    )


async def _fetch_one(symbol: str, semaphore: asyncio.Semaphore) -> tuple[str, Optional[FetchedFundamentals]]:
    async with semaphore:
        try:
            data = await asyncio.to_thread(_blocking_fetch_fundamentals, symbol)
        except Exception:
            logger.exception("fundamentals fetch raised for %s", symbol)
            data = None
    return symbol, data


async def _upsert(db: AsyncSession, symbol: str, data: FetchedFundamentals, now: datetime) -> None:
    stmt = (
        pg_insert(CompanyFundamental)
        .values(
            symbol=symbol,
            market_cap=_to_decimal(data.market_cap, 20, 2),
            pe_ratio=_to_decimal(data.pe_ratio, 10, 2),
            pb_ratio=_to_decimal(data.pb_ratio, 10, 2),
            eps=_to_decimal(data.eps, 10, 4),
            roe=_to_decimal(data.roe, 6, 2),
            roce=_to_decimal(data.roce, 6, 2),
            debt_to_equity=_to_decimal(data.debt_to_equity, 10, 4),
            dividend_yield=_to_decimal(data.dividend_yield, 6, 2),
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["symbol"],
            set_={
                "market_cap": _to_decimal(data.market_cap, 20, 2),
                "pe_ratio": _to_decimal(data.pe_ratio, 10, 2),
                "pb_ratio": _to_decimal(data.pb_ratio, 10, 2),
                "eps": _to_decimal(data.eps, 10, 4),
                "roe": _to_decimal(data.roe, 6, 2),
                "roce": _to_decimal(data.roce, 6, 2),
                "debt_to_equity": _to_decimal(data.debt_to_equity, 10, 4),
                "dividend_yield": _to_decimal(data.dividend_yield, 6, 2),
                "updated_at": now,
            },
        )
    )
    await db.execute(stmt)


async def fetch_and_store_fundamentals(db: AsyncSession, symbols: Optional[list[str]] = None) -> None:
    """
    Refresh fundamentals for every tracked ticker (or a specific subset,
    e.g. one symbol right after it's added to a watchlist). Failures are
    logged and skipped per-symbol — a bad fetch for one ticker must not
    abort the whole cycle, matching market_data.py's fault-tolerance style.
    """
    if symbols is None:
        tickers = (
            (await db.execute(select(Ticker.symbol).where(Ticker.is_tracked.is_(True))))
            .scalars()
            .all()
        )
    else:
        tickers = symbols

    if not tickers:
        return

    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_FETCHES)
    results = await asyncio.gather(*(_fetch_one(sym, semaphore) for sym in tickers))

    now = datetime.now(timezone.utc)
    for symbol, data in results:
        if data is None:
            logger.warning("No fundamentals available for %s this cycle", symbol)
            continue
        await _upsert(db, symbol, data, now)

    await db.commit()


async def fetch_and_store_fundamentals_for_symbol(db: AsyncSession, symbol: str) -> None:
    """Best-effort single-symbol refresh, used right after a ticker is
    newly added so its dashboard row isn't empty until the next periodic
    cycle. Never raises — a fundamentals miss must not block adding the
    ticker to the watchlist."""
    try:
        await fetch_and_store_fundamentals(db, symbols=[symbol])
    except Exception:
        logger.exception("On-demand fundamentals fetch failed for %s", symbol)