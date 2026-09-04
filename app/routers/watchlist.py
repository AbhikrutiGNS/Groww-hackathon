# app/routers/watchlist.py
"""
Watchlist router: add/reactivate a ticker, remove (soft delete), the
Attention Feed with a null-safe baseline, and the acknowledge endpoint that
advances the baseline.
"""
from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import text, DateTime, bindparam, String, Numeric
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import WatchlistItem, CompanyFundamental
from app.auth import get_current_user_id
from app.services.ticker_registry import UnresolvableTickerError, ensure_ticker_exists
from app.services.fundamentals import fetch_and_store_fundamentals_for_symbol
from app.services.technicals import get_technicals

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class AddWatchlistItemRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    notes: Optional[str] = None


class WatchlistItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    symbol: str
    added_at: datetime
    is_active: bool
    notes: Optional[str] = None


class AttentionFeedItem(BaseModel):
    symbol: str
    current_price: Optional[Decimal] = None  # null when no snapshot has landed yet (see LEFT JOIN below)
    baseline_price: Optional[Decimal]
    percent_change: Optional[Decimal]
    is_new_addition: bool  # True when no baseline exists yet — see below
    is_stale: bool
    hit_52w_high: bool = False
    hit_52w_low: bool = False
    hit_week_high: bool = False
    hit_week_low: bool = False
    trend_signal: Optional[str] = None  # "golden_cross" | "death_cross" | None


# ---------------------------------------------------------------------------
# Add-or-reactivate as a single atomic UPSERT.
# Never a plain INSERT — the unique constraint on (user_id, symbol) will
# reject a re-add after a soft delete, and a "check-then-insert" pattern is
# a race condition under concurrent requests anyway.
#
# Before the upsert: ensure_ticker_exists() resolves the symbol against
# yfinance and creates the `tickers` master row on first sight if it's a
# real instrument. This is what makes "add any ticker", not just the
# handful someone manually seeded, actually work. Both writes happen in
# the same transaction — either the ticker+watchlist-item both land, or
# neither does.
# ---------------------------------------------------------------------------
@router.post("", response_model=WatchlistItemResponse, status_code=200)
async def add_or_reactivate_watchlist_item(
    payload: AddWatchlistItemRequest,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> WatchlistItemResponse:
    symbol = payload.symbol.upper().strip()

    try:
        await ensure_ticker_exists(db, symbol)
    except UnresolvableTickerError:
        await db.rollback()
        raise HTTPException(
            status_code=422,
            detail=f"'{symbol}' doesn't look like a valid ticker symbol.",
        )

    stmt = (
        pg_insert(WatchlistItem)
        .values(
            user_id=user_id,
            symbol=symbol,
            is_active=True,
            notes=payload.notes,
        )
        .on_conflict_do_update(
            constraint="uq_watchlist_user_symbol",
            set_={
                "is_active": True,
                "added_at": text("now()"),
                "removed_at": None,   # clear the removal marker on reactivation
                "notes": payload.notes,
            },
        )
        .returning(WatchlistItem)
    )
    result = await db.execute(stmt)
    await db.commit()
    row = result.scalars().first()
    if row is None:
        # Unreachable in practice now that ensure_ticker_exists() guarantees
        # the FK target exists, but fail loudly rather than return a null
        # body if some other constraint trips.
        raise HTTPException(status_code=500, detail=f"Could not add {symbol}")

    # Best-effort, on-demand fundamentals fetch so this symbol's dashboard
    # row isn't empty until the next periodic cycle (default every 6h).
    # fetch_and_store_fundamentals_for_symbol never raises — a fundamentals
    # miss must not fail "add ticker".
    await fetch_and_store_fundamentals_for_symbol(db, symbol)

    return WatchlistItemResponse.model_validate(row)


class WatchlistListItem(BaseModel):
    symbol: str
    notes: Optional[str] = None
    added_at: datetime
    current_price: Optional[Decimal] = None
    is_stale: Optional[bool] = None
    day_high: Optional[Decimal] = None
    day_low: Optional[Decimal] = None
    # Fundamentals — nullable because they're best-effort and slower to
    # arrive than price (see fetch_and_store_fundamentals_for_symbol).
    # "just added — building history" applies here too, not just to the
    # attention feed's baseline.
    market_cap: Optional[Decimal] = None
    pe_ratio: Optional[Decimal] = None
    pb_ratio: Optional[Decimal] = None
    eps: Optional[Decimal] = None
    roe: Optional[Decimal] = None
    roce: Optional[Decimal] = None
    debt_to_equity: Optional[Decimal] = None
    dividend_yield: Optional[Decimal] = None
    fundamentals_updated_at: Optional[datetime] = None
    # Technicals — derived from stock_snapshots on read, not stored.
    # See app/services/technicals.py. Nullable for the same reason as
    # fundamentals: not enough snapshot history yet for a fresh ticker.
    week_high: Optional[Decimal] = None
    week_low: Optional[Decimal] = None
    sma_20: Optional[Decimal] = None
    sma_50: Optional[Decimal] = None
    ema_20: Optional[Decimal] = None
    ema_50: Optional[Decimal] = None


# ---------------------------------------------------------------------------
# Plain list of everything the user is tracking, with the latest known price
# regardless of whether it's "meaningful" — the Attention Feed answers "what
# changed", this answers "what am I tracking". A stock that hasn't moved
# still needs to be visible somewhere; it just shouldn't clutter the feed.
# Symbols with no snapshot yet (freshly tracked, ingestion hasn't run) come
# back with current_price = null rather than being silently dropped.
# ---------------------------------------------------------------------------
_WATCHLIST_SQL = text(
    """
    SELECT
        w.symbol,
        w.notes,
        w.added_at,
        latest.price    AS current_price,
        latest.is_stale AS is_stale,
        latest.day_high AS day_high,
        latest.day_low  AS day_low,
        cf.market_cap        AS market_cap,
        cf.pe_ratio          AS pe_ratio,
        cf.pb_ratio          AS pb_ratio,
        cf.eps               AS eps,
        cf.roe                AS roe,
        cf.roce               AS roce,
        cf.debt_to_equity     AS debt_to_equity,
        cf.dividend_yield     AS dividend_yield,
        cf.updated_at         AS fundamentals_updated_at
    FROM watchlist_items w
    LEFT JOIN LATERAL (
        SELECT price, is_stale, day_high, day_low
        FROM stock_snapshots s
        WHERE s.symbol = w.symbol
        ORDER BY s.captured_at DESC
        LIMIT 1
    ) latest ON true
    LEFT JOIN company_fundamentals cf ON cf.symbol = w.symbol
    WHERE w.user_id = :user_id AND w.is_active = true
    ORDER BY w.added_at DESC
    """
)


@router.get("", response_model=list[WatchlistListItem])
async def list_watchlist(
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> list[WatchlistListItem]:
    rows = (await db.execute(_WATCHLIST_SQL, {"user_id": user_id})).mappings().all()

    items: list[WatchlistListItem] = []
    for row in rows:
        # Sequential, not gathered concurrently — AsyncSession is not safe
        # for concurrent use across coroutines (see market_data.py).
        technicals = await get_technicals(db, row["symbol"])
        items.append(WatchlistListItem(**row, **technicals))
    return items


@router.delete("/{symbol}", status_code=204)
async def remove_watchlist_item(
    symbol: str,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    await db.execute(
        text(
            """
            UPDATE watchlist_items
               SET is_active = false, removed_at = now()
             WHERE user_id = :user_id AND symbol = :symbol AND is_active = true
            """
        ),
        {"user_id": user_id, "symbol": symbol.upper().strip()},
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Demo-only: force a synthetic snapshot so the Attention Feed has something
# to show without waiting on real market movement during a live demo.
# Gated behind DEMO_MODE so it can never accidentally ship as a real
# endpoint against production data.
# ---------------------------------------------------------------------------
class DemoSeedRequest(BaseModel):
    symbol: str
    percent_change: Decimal = Decimal("5.0")  # e.g. 5.0 = simulate a +5% move


@router.post("/demo/simulate-move", status_code=201, include_in_schema=os.getenv("DEMO_MODE") == "1")
async def simulate_price_move(
    payload: DemoSeedRequest,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if os.getenv("DEMO_MODE") != "1":
        raise HTTPException(status_code=404, detail="Not found")

    symbol = payload.symbol.upper().strip()
    latest = (
        await db.execute(
            text(
                """
                SELECT price FROM stock_snapshots
                WHERE symbol = :symbol
                ORDER BY captured_at DESC LIMIT 1
                """
            ),
            {"symbol": symbol},
        )
    ).scalar_one_or_none()
    if latest is None:
        raise HTTPException(status_code=404, detail=f"No snapshot yet for {symbol}")

    new_price = latest * (1 + payload.percent_change / 100)
    await db.execute(
        text(
            """
            INSERT INTO stock_snapshots
                (symbol, captured_at, price, day_high, day_low, volume,
                 week_52_high, week_52_low, source, is_stale)
            SELECT :symbol, now(), :price, day_high, day_low, volume,
                   week_52_high, week_52_low, 'demo-simulated', false
            FROM stock_snapshots WHERE symbol = :symbol
            ORDER BY captured_at DESC LIMIT 1
            """
        ).bindparams(
            bindparam("symbol", type_=String),
            bindparam("price", type_=Numeric),
        ),
        {"symbol": symbol, "price": new_price},
    )
    await db.commit()
    return {"symbol": symbol, "old_price": latest, "new_price": new_price}


class DemoSeedFundamentalsRequest(BaseModel):
    symbol: str
    market_cap: Optional[Decimal] = None
    pe_ratio: Optional[Decimal] = None
    pb_ratio: Optional[Decimal] = None
    eps: Optional[Decimal] = None
    roe: Optional[Decimal] = None
    roce: Optional[Decimal] = None
    debt_to_equity: Optional[Decimal] = None
    dividend_yield: Optional[Decimal] = None


@router.post(
    "/demo/seed-fundamentals",
    status_code=201,
    include_in_schema=os.getenv("DEMO_MODE") == "1",
)
async def seed_fundamentals(
    payload: DemoSeedFundamentalsRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Demo-only: manually set fundamentals for a symbol so the dashboard has
    something to show without depending on a live yfinance call (rate
    limits, network access, or a symbol Yahoo doesn't cover well — e.g.
    thinly-traded NSE/BSE tickers). Gated behind DEMO_MODE exactly like
    /demo/simulate-move.
    """
    if os.getenv("DEMO_MODE") != "1":
        raise HTTPException(status_code=404, detail="Not found")

    symbol = payload.symbol.upper().strip()
    exists = (
        await db.execute(text("SELECT 1 FROM tickers WHERE symbol = :symbol"), {"symbol": symbol})
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail=f"{symbol} is not a known ticker yet — add it to a watchlist first.")

    stmt = (
        pg_insert(__import__("app.models", fromlist=["CompanyFundamental"]).CompanyFundamental)
        .values(symbol=symbol, **payload.model_dump(exclude={"symbol"}))
        .on_conflict_do_update(
            index_elements=["symbol"],
            set_=payload.model_dump(exclude={"symbol"}),
        )
    )
    await db.execute(stmt)
    await db.commit()
    return {"symbol": symbol, "seeded": True}


@router.post("/acknowledge", status_code=204)
async def acknowledge_watchlist(
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Advances the user's baseline. Deliberately a separate, explicit action —
    NOT called on every GET of the attention feed. The frontend calls this
    on an explicit "mark as reviewed" action, tab close, or after a
    debounce — never on page load.
    """
    result = await db.execute(
        text("UPDATE users SET last_viewed_at = now(), updated_at = now() WHERE id = :user_id"),
        {"user_id": user_id},
    )
    if result.rowcount == 0:
        await db.rollback()
        raise HTTPException(status_code=404, detail="User not found")
    await db.commit()


# ---------------------------------------------------------------------------
# No baseline is a first-class state, not a math error to paper over.
#
# We deliberately do NOT do:
#     COALESCE(last_viewed_at, added_at - interval '24 hours')
# because that fabricates a comparison point that may not correspond to any
# real trade (weekends, holidays, or a ticker nobody has ever tracked before
# on this platform). Showing a user "+3.2% since you last checked" against
# a timestamp where no market data exists is a worse failure than showing
# "just added — building history."
#
# Instead: LEFT JOIN LATERAL for the latest snapshot, and a SEPARATE
# LEFT JOIN LATERAL for a real baseline snapshot IF one exists at or before
# last_viewed_at. If last_viewed_at IS NULL, or no snapshot exists at or
# before it, baseline is NULL and the API returns is_new_addition=true with
# no percent_change — an honest state, not a guessed one.
#
# Both LATERALs run once per watchlist item inside a single query — no
# per-symbol round trip, no N+1.
# ---------------------------------------------------------------------------
_ATTENTION_FEED_SQL = text(
    """
    SELECT
        w.symbol,
        latest.price               AS current_price,
        latest.is_stale            AS is_stale,
        COALESCE(latest.price >= latest.week_52_high, false) AS hit_52w_high,
        COALESCE(latest.price <= latest.week_52_low, false)  AS hit_52w_low,
        baseline.price             AS baseline_price
    FROM watchlist_items w
    LEFT JOIN LATERAL (
        SELECT price, is_stale, week_52_high, week_52_low
        FROM stock_snapshots s
        WHERE s.symbol = w.symbol
        ORDER BY s.captured_at DESC
        LIMIT 1
    ) latest ON true
    LEFT JOIN LATERAL (
        SELECT price
        FROM stock_snapshots s
        WHERE s.symbol = w.symbol
          AND CAST(:last_viewed_at AS timestamptz) IS NOT NULL
          AND s.captured_at <= CAST(:last_viewed_at AS timestamptz)
        ORDER BY s.captured_at DESC
        LIMIT 1
    ) baseline ON true
    WHERE w.user_id = :user_id AND w.is_active = true
    """
).bindparams(
    bindparam("last_viewed_at", type_=DateTime(timezone=True)),
)


@router.get("/attention-feed", response_model=list[AttentionFeedItem])
async def get_attention_feed(
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> list[AttentionFeedItem]:
    # Read last_viewed_at once, not inside the loop / not inside the SQL as
    # a fabricated fallback — NULL is passed through as NULL on purpose.
    user_row = await db.execute(
        text("SELECT last_viewed_at FROM users WHERE id = :user_id"),
        {"user_id": user_id},
    )
    last_viewed_at = user_row.scalar_one_or_none()

    rows = (
        await db.execute(_ATTENTION_FEED_SQL, {"user_id": user_id, "last_viewed_at": last_viewed_at})
    ).mappings().all()

    feed: list[AttentionFeedItem] = []
    for row in rows:
        baseline = row["baseline_price"]
        current = row["current_price"]

        if current is None:
            # No snapshot has landed yet (ticker was just added, ingestion
            # hasn't run) — this is unambiguously "new", not a math problem.
            percent_change = None
            is_new = True
        elif baseline is None:
            percent_change = None
            is_new = True
        else:
            percent_change = (
                ((current - baseline) / baseline) * 100 if baseline != 0 else None
            )
            is_new = False

        # Technicals are per-symbol, computed on read from stock_snapshots
        # (see app/services/technicals.py) — not part of _ATTENTION_FEED_SQL
        # above, which only covers the price/baseline/52w columns already
        # on that query.
        technicals = await get_technicals(db, row["symbol"])
        hit_week_high = (
            current is not None
            and technicals["week_high"] is not None
            and current >= technicals["week_high"]
        )
        hit_week_low = (
            current is not None
            and technicals["week_low"] is not None
            and current <= technicals["week_low"]
        )
        trend_signal = technicals["trend_signal"]

        meaningful = (
            is_new
            or (percent_change is not None and abs(percent_change) >= 3)
            or row["hit_52w_high"]
            or row["hit_52w_low"]
            or hit_week_high
            or hit_week_low
            or trend_signal is not None
        )

        if meaningful:
            feed.append(
                AttentionFeedItem(
                    symbol=row["symbol"],
                    current_price=current,
                    baseline_price=baseline,
                    percent_change=percent_change,
                    is_new_addition=is_new,
                    is_stale=row["is_stale"],
                    hit_52w_high=row["hit_52w_high"],
                    hit_52w_low=row["hit_52w_low"],
                    hit_week_high=hit_week_high,
                    hit_week_low=hit_week_low,
                    trend_signal=trend_signal,
                )
            )
    return feed