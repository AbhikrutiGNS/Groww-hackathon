# app/services/market_data.py
"""
Market data ingestion worker.

Two rules that are load-bearing, not stylistic:

1. Bounded concurrency on the yfinance fetch. Yahoo rate-limits / blocks
   cloud IPs under burst load. An unbounded asyncio.gather across every
   tracked ticker is the fastest way to get this app's outbound IP banned
   mid-demo. _MAX_CONCURRENT_FETCHES caps how many blocking yfinance calls
   run at once via asyncio.to_thread.

2. AsyncSession is NOT safe for concurrent use across coroutines. All DB
   reads/writes in this module happen sequentially, strictly AFTER the
   concurrent network-fetch phase completes. The gathered coroutines touch
   only the network (via to_thread) and never `db`.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import StockSnapshot, Ticker

logger = logging.getLogger("market_data")

_MAX_CONCURRENT_FETCHES = 5
_fetch_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_FETCHES)


class FetchedQuote:
    __slots__ = ("price", "volume", "day_high", "day_low", "week_52_high", "week_52_low")

    def __init__(self, price, volume, day_high, day_low, week_52_high, week_52_low):
        self.price = price
        self.volume = volume
        self.day_high = day_high
        self.day_low = day_low
        self.week_52_high = week_52_high
        self.week_52_low = week_52_low


def _is_valid_price(price) -> bool:
    """A try/except around the network call does not catch this: yfinance
    frequently returns without raising for a halted, delisted, or
    momentarily-unavailable ticker, but with price as None or NaN. Validate
    the payload, not just the call."""
    if price is None:
        return False
    if price != price:  # NaN != NaN is True; cheapest NaN check with no numpy import
        return False
    return price > 0


def _blocking_fetch_quote(symbol: str) -> Optional[FetchedQuote]:
    """Fully synchronous — must only ever be called via asyncio.to_thread.

    fast_info is a lazy proxy: accessing `.last_price` can itself raise
    (e.g. Yahoo omitting 'currentTradingPeriod' from chart metadata — a
    known upstream yfinance issue independent of network failure). We
    isolate that access so one broken field can't be mistaken for a
    connectivity problem, and we fall back to a slower but more robust
    `.history()` call before giving up on this cycle for this symbol.
    """
    ticker = yf.Ticker(symbol)

    try:
        info = ticker.fast_info
        price = getattr(info, "last_price", None)
        if _is_valid_price(price):
            return FetchedQuote(
                price=price,
                volume=getattr(info, "last_volume", None),
                day_high=getattr(info, "day_high", None),
                day_low=getattr(info, "day_low", None),
                week_52_high=getattr(info, "year_high", None),
                week_52_low=getattr(info, "year_low", None),
            )
    except Exception:
        logger.warning("fast_info failed for %s, falling back to history()", symbol)

    # Fallback: plain OHLCV history doesn't touch the metadata field that's
    # been flaky, at the cost of one extra request.
    try:
        hist = ticker.history(period="5d", interval="1d", auto_adjust=False)
        if hist.empty:
            return None
        last = hist.iloc[-1]
        price = float(last["Close"])
        if not _is_valid_price(price):
            return None
        return FetchedQuote(
            price=price,
            volume=float(last["Volume"]) if "Volume" in last else None,
            day_high=float(last["High"]) if "High" in last else None,
            day_low=float(last["Low"]) if "Low" in last else None,
            week_52_high=None,  # not available from this fallback; next successful fast_info call will fill it in
            week_52_low=None,
        )
    except Exception:
        logger.exception("history() fallback also failed for %s", symbol)
        return None


async def _fetch_one(symbol: str) -> tuple[str, Optional[FetchedQuote]]:
    """Network-only. No `db` access here — see module docstring rule 2."""
    async with _fetch_semaphore:
        try:
            quote = await asyncio.to_thread(_blocking_fetch_quote, symbol)
        except Exception:
            logger.exception("yfinance fetch failed for %s", symbol)
            quote = None
    return symbol, quote


async def fetch_and_store_snapshots(db: AsyncSession) -> None:
    """
    One ingestion cycle: fetch live quotes for every tracked ticker,
    concurrently and rate-limit-safely, then fall back to a stale-flagged
    copy of the last known snapshot for any ticker whose fetch failed or
    returned invalid data.
    """
    tickers = (
        (await db.execute(select(Ticker).where(Ticker.is_tracked.is_(True))))
        .scalars()
        .all()
    )
    if not tickers:
        return

    # --- Phase 1: concurrent, bounded, DB-free network fetch ---
    fetch_results = await asyncio.gather(*(_fetch_one(t.symbol) for t in tickers))
    quotes_by_symbol = dict(fetch_results)

    # --- Phase 2: sequential DB work on the single session ---
    now = datetime.now(timezone.utc)
    new_snapshots: list[StockSnapshot] = []

    for ticker in tickers:
        quote = quotes_by_symbol.get(ticker.symbol)

        if quote is not None:
            new_snapshots.append(
                StockSnapshot(
                    symbol=ticker.symbol,
                    captured_at=now,
                    price=quote.price,
                    day_high=quote.day_high,
                    day_low=quote.day_low,
                    volume=quote.volume,
                    week_52_high=quote.week_52_high,
                    week_52_low=quote.week_52_low,
                    source="yfinance",
                    is_stale=False,
                )
            )
            ticker.fetch_failure_count = 0
            ticker.last_fetch_attempt_at = now
            continue

        # --- Fault-tolerance path: fetch failed or returned invalid data ---
        ticker.fetch_failure_count += 1
        ticker.last_fetch_attempt_at = now

        latest = (
            (
                await db.execute(
                    select(StockSnapshot)
                    .where(StockSnapshot.symbol == ticker.symbol)
                    .order_by(StockSnapshot.captured_at.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )

        if latest is None:
            logger.warning(
                "No fallback snapshot available for %s (failure #%d); skipping cycle",
                ticker.symbol,
                ticker.fetch_failure_count,
            )
            continue

        new_snapshots.append(
            StockSnapshot(
                symbol=ticker.symbol,
                captured_at=now,
                price=latest.price,
                day_high=latest.day_high,
                day_low=latest.day_low,
                volume=latest.volume,
                week_52_high=latest.week_52_high,
                week_52_low=latest.week_52_low,
                source=latest.source,
                is_stale=True,
            )
        )

    db.add_all(new_snapshots)
    await db.commit()