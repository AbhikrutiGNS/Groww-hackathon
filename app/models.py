# app/models.py
"""
Declarative ORM models — must stay byte-for-byte consistent with
0001_initial_schema.py / 0002_holding_transactions.py. If you add a column
in one, add it in the other; nothing here should ever be relied on to
auto-generate the schema in production (Alembic migrations are the source
of truth).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    BigInteger,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    last_viewed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    watchlist_items: Mapped[list["WatchlistItem"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Ticker(Base):
    """Shared master data — one row per instrument, referenced by every user
    who tracks it. Never duplicate this per-user."""

    __tablename__ = "tickers"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    isin: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)
    is_tracked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    last_fetch_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    fetch_failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    watchlist_items: Mapped[list["WatchlistItem"]] = relationship(back_populates="ticker")
    snapshots: Mapped[list["StockSnapshot"]] = relationship(back_populates="ticker")
    fundamentals: Mapped[Optional["CompanyFundamental"]] = relationship(
        back_populates="ticker", uselist=False
    )


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("user_id", "symbol", name="uq_watchlist_user_symbol"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(
        String(20), ForeignKey("tickers.symbol", ondelete="RESTRICT"), nullable=False
    )
    added_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    removed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship(back_populates="watchlist_items")
    ticker: Mapped["Ticker"] = relationship(back_populates="watchlist_items")


class HoldingTransaction(Base):
    """
    Append-only trade ledger — a BUY or SELL fill, one row each. This is the
    source of truth for what a user owns; current position (quantity, avg
    cost, realized P&L) is DERIVED by replaying these rows in order, never
    stored as a mutable running balance. See app/services/holdings.py.

    Scope note: this is moving-average cost accounting (one blended cost
    basis per symbol), not FIFO/LIFO tax-lot tracking.
    """

    __tablename__ = "holding_transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(
        String(20), ForeignKey("tickers.symbol", ondelete="RESTRICT"), nullable=False
    )
    side: Mapped[str] = mapped_column(String(4), nullable=False)  # 'BUY' | 'SELL'
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_voided: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    voided_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    user: Mapped["User"] = relationship()
    ticker: Mapped["Ticker"] = relationship()


class NotificationHistory(Base):
    """
    Append-only log of what was on the Attention Feed each time the user
    acknowledged it. Written by /watchlist/acknowledge, read by
    /watchlist/notification-history (last 5, newest first) so the "you're
    caught up" state can still answer "what did I just review?" instead of
    just going blank.

    No FK on symbol deliberately — see migration 0003 docstring: this is a
    snapshot of what happened, not a live reference, so it must outlive the
    watchlist item (or even the ticker) it was about.
    """

    __tablename__ = "notification_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    current_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4), nullable=True)
    percent_change: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    is_new_addition: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    hit_52w_high: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    hit_52w_low: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    hit_week_high: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    hit_week_low: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    trend_signal: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    user: Mapped["User"] = relationship()


class StockSnapshot(Base):
    """Append-only, high-frequency time series. Shared across all users
    tracking the symbol — never write one per (user, symbol, time)."""

    __tablename__ = "stock_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(
        String(20), ForeignKey("tickers.symbol", ondelete="CASCADE"), nullable=False
    )
    captured_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    day_high: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4), nullable=True)
    day_low: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4), nullable=True)
    volume: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    avg_volume_30d: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    week_52_high: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4), nullable=True)
    week_52_low: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4), nullable=True)
    source: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="yfinance"
    )
    is_stale: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    ticker: Mapped["Ticker"] = relationship(back_populates="snapshots")


class CompanyFundamental(Base):
    """Low-frequency data (quarterly-ish). One row per ticker, upserted on
    each refresh — separate from stock_snapshots so a fast price poll
    never rewrites slow-changing fundamentals."""

    __tablename__ = "company_fundamentals"

    symbol: Mapped[str] = mapped_column(
        String(20), ForeignKey("tickers.symbol", ondelete="CASCADE"), primary_key=True
    )
    market_cap: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    pe_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    pb_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    eps: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    roe: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    roce: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    debt_to_equity: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    dividend_yield: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    ticker: Mapped["Ticker"] = relationship(back_populates="fundamentals")