# app/routers/watchlist.py
"""
Watchlist router: add/reactivate a ticker, remove (soft delete), the
Attention Feed with a null-safe baseline, and the acknowledge endpoint that
advances the baseline.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import WatchlistItem
from app.auth import get_current_user_id

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
    current_price: Decimal
    baseline_price: Optional[Decimal]
    percent_change: Optional[Decimal]
    is_new_addition: bool  # True when no baseline exists yet — see below
    is_stale: bool
    hit_52w_high: bool
    hit_52w_low: bool


# ---------------------------------------------------------------------------
# Add-or-reactivate as a single atomic UPSERT.
# Never a plain INSERT — the unique constraint on (user_id, symbol) will
# reject a re-add after a soft delete, and a "check-then-insert" pattern is
# a race condition under concurrent requests anyway.
# ---------------------------------------------------------------------------
@router.post("", response_model=WatchlistItemResponse, status_code=200)
async def add_or_reactivate_watchlist_item(
    payload: AddWatchlistItemRequest,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> WatchlistItemResponse:
    symbol = payload.symbol.upper().strip()

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
    row = result.fetchone()
    if row is None:
        # symbol not present in `tickers` -> FK violation was caught upstream,
        # or the ticker genuinely doesn't exist on our platform yet.
        raise HTTPException(status_code=404, detail=f"Unknown ticker: {symbol}")
    return WatchlistItemResponse.model_validate(row)


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
        latest.price >= latest.week_52_high AS hit_52w_high,
        latest.price <= latest.week_52_low  AS hit_52w_low,
        baseline.price             AS baseline_price
    FROM watchlist_items w
    JOIN LATERAL (
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
          AND :last_viewed_at IS NOT NULL
          AND s.captured_at <= :last_viewed_at
        ORDER BY s.captured_at DESC
        LIMIT 1
    ) baseline ON true
    WHERE w.user_id = :user_id AND w.is_active = true
    """
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

        if baseline is None:
            percent_change = None
            is_new = True
        else:
            percent_change = (
                ((current - baseline) / baseline) * 100 if baseline != 0 else None
            )
            is_new = False

        meaningful = is_new or (
            percent_change is not None and abs(percent_change) >= 3
        ) or row["hit_52w_high"] or row["hit_52w_low"]

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
                )
            )
    return feed