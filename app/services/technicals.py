# app/services/technicals.py
"""
Derived technical indicators — 1-week high/low, SMA(20/50), EMA(20/50), and
SMA20/50 crossover ("golden"/"death" cross) detection.

Deliberately NOT a new data source: everything here is computed from
stock_snapshots, which market_data.py already populates every ingestion
cycle. No migration, no new external calls, no new failure domain.

Two design choices worth calling out:

1. SMA/EMA are computed over one price PER CALENDAR DAY, not over raw
   snapshot rows. Snapshots are captured every INGESTION_INTERVAL_SECONDS
   (default 60s), so a naive average over all rows in a date range would
   heavily overweight days with more market-open minutes / more successful
   fetches — that's not a 20-day average, it's an average dominated by
   whichever days happened to have the most samples. We take the last
   snapshot of each day (a "close" proxy) and average across days instead.

2. Same AsyncSession-concurrency rule as the rest of this codebase: this
   module issues one query per symbol, sequentially. It does not run
   concurrently across symbols, because AsyncSession is not safe for
   concurrent use across coroutines (see market_data.py's module docstring).
   Fine for a personal watchlist's symbol count; if this ever needs to
   scale to hundreds of symbols per request, batch it into a single
   query keyed by symbol instead of calling this per-symbol in a loop.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, TypedDict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SMA_PERIODS = (20, 50)
# Trading days are ~5/7 of calendar days (weekends), plus holidays on top.
# SMA50 needs 50 trading days, and _detect_cross needs 51 — at 5/7, 50
# trading days alone need ~70 calendar days minimum. 60 was undersized: it
# only ever yields ~43 trading days, so sma_50 (and therefore Trend, which
# requires both sma_20 AND sma_50) was permanently null regardless of how
# much history existed. 120 gives real headroom for holidays too.
_LOOKBACK_DAYS = 120

_WEEK_RANGE_SQL = text(
    """
    SELECT MIN(price) AS week_low, MAX(price) AS week_high
    FROM stock_snapshots
    WHERE symbol = :symbol AND captured_at >= :since
    """
)

# One row per calendar day: the last snapshot captured that day, used as a
# "close" proxy. DISTINCT ON + ORDER BY (day, captured_at DESC) picks the
# latest row per day; the outer ORDER BY day keeps the result oldest-first.
_DAILY_CLOSES_SQL = text(
    """
    SELECT day, price FROM (
        SELECT DISTINCT ON (captured_at::date)
            captured_at::date AS day, price
        FROM stock_snapshots
        WHERE symbol = :symbol AND captured_at >= :since
        ORDER BY captured_at::date, captured_at DESC
    ) daily
    ORDER BY day ASC
    """
)


class Technicals(TypedDict):
    week_high: Optional[Decimal]
    week_low: Optional[Decimal]
    sma_20: Optional[Decimal]
    sma_50: Optional[Decimal]
    ema_20: Optional[Decimal]
    ema_50: Optional[Decimal]
    trend_signal: Optional[str]  # "golden_cross" | "death_cross" | None


def _sma(closes: list[Decimal], period: int) -> Optional[Decimal]:
    if len(closes) < period:
        return None
    window = closes[-period:]
    return sum(window) / Decimal(period)


def _ema(closes: list[Decimal], period: int) -> Optional[Decimal]:
    """Standard EMA: seed with the SMA of the first `period` points, then
    apply the smoothing multiplier to every point after that."""
    if len(closes) < period:
        return None
    k = Decimal(2) / Decimal(period + 1)
    ema = sum(closes[:period]) / Decimal(period)
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return ema


def _detect_cross(closes: list[Decimal]) -> Optional[str]:
    """A golden/death cross is a CHANGE in which SMA is on top, not just
    "20 > 50 today" (that's true on most days and isn't news). We compare
    today's SMA20-vs-SMA50 ordering against the same comparison computed
    one day earlier (i.e. with the most recent close dropped) — only the
    day the ordering actually flips counts as a cross."""
    if len(closes) < 51:
        return None
    sma20_now, sma50_now = _sma(closes, 20), _sma(closes, 50)
    sma20_prev, sma50_prev = _sma(closes[:-1], 20), _sma(closes[:-1], 50)
    if None in (sma20_now, sma50_now, sma20_prev, sma50_prev):
        return None
    now_diff = sma20_now - sma50_now
    prev_diff = sma20_prev - sma50_prev
    if prev_diff <= 0 and now_diff > 0:
        return "golden_cross"
    if prev_diff >= 0 and now_diff < 0:
        return "death_cross"
    return None


async def get_technicals(db: AsyncSession, symbol: str) -> Technicals:
    now = datetime.now(timezone.utc)

    week_row = (
        await db.execute(_WEEK_RANGE_SQL, {"symbol": symbol, "since": now - timedelta(days=7)})
    ).mappings().first()

    daily_rows = (
        await db.execute(
            _DAILY_CLOSES_SQL, {"symbol": symbol, "since": now - timedelta(days=_LOOKBACK_DAYS)}
        )
    ).mappings().all()
    closes = [row["price"] for row in daily_rows]  # oldest -> newest

    return Technicals(
        week_high=week_row["week_high"] if week_row else None,
        week_low=week_row["week_low"] if week_row else None,
        sma_20=_sma(closes, 20),
        sma_50=_sma(closes, 50),
        ema_20=_ema(closes, 20),
        ema_50=_ema(closes, 50),
        trend_signal=_detect_cross(closes),
    )