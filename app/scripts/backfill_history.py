# app/scripts/backfill_history.py
"""
One-time backfill: pulls REAL historical daily OHLC from yfinance and
inserts one stock_snapshots row per trading day for the last ~90 days.

This works even while the market is closed — .history() returns past
trading days regardless of today's session state, unlike fast_info which
only reflects the current/last quote. This is what gives SMA(20)/SMA(50)/
EMA and the 1-week high/low real numbers immediately, instead of waiting
for the market to reopen and 50+ daily live-ingestion cycles to pass.

Usage (run from the repo root, with your venv + .env active):
    python -m app.scripts.backfill_history AAPL MSFT TSLA
    python -m app.scripts.backfill_history            # backfills every symbol already in `tickers`

Safe to re-run: it just inserts more rows (stock_snapshots is append-only
by design), so running it twice adds duplicate-ish daily points rather
than corrupting anything — fine for a demo, not something to leave in a
cron job.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import timezone

import yfinance as yf
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models import StockSnapshot, Ticker
from app.services.ticker_registry import UnresolvableTickerError, ensure_ticker_exists


async def _symbols_from_db() -> list[str]:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Ticker.symbol))).scalars().all()
        return list(rows)


def _blocking_fetch_daily(symbol: str):
    return yf.Ticker(symbol).history(period="150d", interval="1d", auto_adjust=False)


def _blocking_fetch_year(symbol: str):
    return yf.Ticker(symbol).history(period="1y", interval="1d", auto_adjust=False)


async def backfill_symbol(symbol: str) -> int:
    hist = await asyncio.to_thread(_blocking_fetch_daily, symbol)
    if hist.empty:
        print(f"  {symbol}: no history returned, skipping")
        return 0

    # Real 52-week high/low too, so the existing hit_52w_high/low fields
    # are meaningful in the demo, not just the new 1-week/SMA fields.
    year_hist = await asyncio.to_thread(_blocking_fetch_year, symbol)
    week_52_high = float(year_hist["High"].max()) if not year_hist.empty else None
    week_52_low = float(year_hist["Low"].min()) if not year_hist.empty else None

    inserted = 0
    async with AsyncSessionLocal() as db:
        # stock_snapshots.symbol FKs to tickers.symbol — must exist first,
        # same resolve-then-create the add-ticker endpoint already does.
        try:
            await ensure_ticker_exists(db, symbol)
            await db.commit()
        except UnresolvableTickerError:
            await db.rollback()
            print(f"  {symbol}: not a resolvable ticker, skipping")
            return 0

        for idx, row in hist.iterrows():
            captured_at = idx.to_pydatetime()
            if captured_at.tzinfo is None:
                captured_at = captured_at.replace(tzinfo=timezone.utc)
            volume = row["Volume"]
            db.add(
                StockSnapshot(
                    symbol=symbol,
                    captured_at=captured_at,
                    price=float(row["Close"]),
                    day_high=float(row["High"]),
                    day_low=float(row["Low"]),
                    volume=int(volume) if volume == volume else None,  # NaN check
                    week_52_high=week_52_high,
                    week_52_low=week_52_low,
                    source="backfill-history",
                    is_stale=False,
                )
            )
            inserted += 1
        await db.commit()
    print(f"  {symbol}: inserted {inserted} daily snapshots")
    return inserted


async def main(symbols: list[str]) -> None:
    if not symbols:
        symbols = await _symbols_from_db()
    if not symbols:
        print(
            "No symbols given and no tickers in DB yet. Add tickers to a watchlist "
            "first, or pass symbols explicitly:\n"
            "  python -m app.scripts.backfill_history AAPL MSFT"
        )
        return

    print(f"Backfilling {len(symbols)} symbol(s): {', '.join(symbols)}")
    for symbol in symbols:
        try:
            await backfill_symbol(symbol.upper().strip())
        except Exception as exc:
            print(f"  {symbol}: FAILED — {exc}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))