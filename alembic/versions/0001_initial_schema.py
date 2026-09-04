# alembic/versions/0001_initial_schema.py
"""initial schema: users, tickers, watchlist_items, stock_snapshots, company_fundamentals

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-04

Design notes (read before modifying):
- Market data (tickers, stock_snapshots, company_fundamentals) is GLOBAL, not
  per-user. Multiple users watching AAPL share one row stream. This is what
  prevents N-user * N-ticker redundant fetches/storage.
- All timestamps are TIMESTAMPTZ, written in UTC. Never store naive timestamps.
- watchlist_items uses soft delete (is_active) — never DELETE a row, for audit trail.
- stock_snapshots is an append-only time series. It WILL grow unbounded; this
  migration adds a covering index and leaves a note for future partitioning
  (see bottom of file) rather than over-engineering it for a 72-hour hackathon.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # USERS
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                   server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        # NULL until the user's first session ends — a brand new user should
        # see everything in their (empty) watchlist as "new", not as a change.
        sa.Column("last_viewed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                   server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                   server_default=sa.text("now()")),
    )

    # ------------------------------------------------------------------
    # TICKERS (shared master data — one row per instrument, ever)
    # ------------------------------------------------------------------
    op.create_table(
        "tickers",
        sa.Column("symbol", sa.String(20), primary_key=True),  # e.g. "AAPL", "RELIANCE.NS"
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("isin", sa.String(12), nullable=True),
        sa.Column("exchange", sa.String(20), nullable=False),
        sa.Column("is_tracked", sa.Boolean, nullable=False, server_default=sa.text("true")),
        # Circuit-breaker groundwork (costs nothing now, saves a migration later)
        sa.Column("last_fetch_attempt_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("fetch_failure_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                   server_default=sa.text("now()")),
    )

    # ------------------------------------------------------------------
    # WATCHLIST_ITEMS (user <-> ticker, soft-deletable)
    # ------------------------------------------------------------------
    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                   sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(20),
                   sa.ForeignKey("tickers.symbol", ondelete="RESTRICT"), nullable=False),
        sa.Column("added_at", sa.TIMESTAMP(timezone=True), nullable=False,
                   server_default=sa.text("now()")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        # Preserves the audit trail across a remove -> re-add cycle. Without this,
        # reactivating a row (see ON CONFLICT DO UPDATE below) silently erases the
        # only record that a removal ever happened.
        sa.Column("removed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        # One logical row per (user, symbol) forever — re-adding a removed
        # stock flips is_active back to true (UPSERT) instead of inserting a
        # duplicate row. Preserves audit history without row explosion.
        sa.UniqueConstraint("user_id", "symbol", name="uq_watchlist_user_symbol"),
    )
    op.create_index(
        "ix_watchlist_items_user_active",
        "watchlist_items", ["user_id", "is_active"],
    )

    # ------------------------------------------------------------------
    # STOCK_SNAPSHOTS (high-frequency time series, shared across users)
    # ------------------------------------------------------------------
    op.create_table(
        "stock_snapshots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(20),
                   sa.ForeignKey("tickers.symbol", ondelete="CASCADE"), nullable=False),
        sa.Column("captured_at", sa.TIMESTAMP(timezone=True), nullable=False,
                   server_default=sa.text("now()")),
        sa.Column("price", sa.Numeric(14, 4), nullable=False),
        sa.Column("day_high", sa.Numeric(14, 4), nullable=True),
        sa.Column("day_low", sa.Numeric(14, 4), nullable=True),
        sa.Column("volume", sa.BigInteger, nullable=True),
        sa.Column("avg_volume_30d", sa.BigInteger, nullable=True),
        sa.Column("week_52_high", sa.Numeric(14, 4), nullable=True),
        sa.Column("week_52_low", sa.Numeric(14, 4), nullable=True),
        sa.Column("source", sa.String(30), nullable=False, server_default="yfinance"),
        # True when this row is a *carried-forward* last-known-good snapshot
        # because the live fetch failed — never silently pretend fresh data.
        sa.Column("is_stale", sa.Boolean, nullable=False, server_default=sa.text("false")),
    )
    # Powers "give me the latest row per symbol" and "nearest row <= last_viewed_at"
    # without a per-symbol query in a loop (see FastAPI LATERAL join in watchlist.py).
    op.create_index(
        "ix_snapshots_symbol_captured_at",
        "stock_snapshots", ["symbol", sa.text("captured_at DESC")],
    )

    # ------------------------------------------------------------------
    # COMPANY_FUNDAMENTALS (low-frequency, one row per ticker, upserted)
    # ------------------------------------------------------------------
    op.create_table(
        "company_fundamentals",
        sa.Column("symbol", sa.String(20),
                   sa.ForeignKey("tickers.symbol", ondelete="CASCADE"), primary_key=True),
        sa.Column("market_cap", sa.Numeric(20, 2), nullable=True),
        sa.Column("pe_ratio", sa.Numeric(10, 2), nullable=True),
        sa.Column("pb_ratio", sa.Numeric(10, 2), nullable=True),
        sa.Column("eps", sa.Numeric(10, 4), nullable=True),
        sa.Column("roe", sa.Numeric(6, 2), nullable=True),
        sa.Column("roce", sa.Numeric(6, 2), nullable=True),
        sa.Column("debt_to_equity", sa.Numeric(10, 4), nullable=True),
        sa.Column("dividend_yield", sa.Numeric(6, 2), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                   server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("company_fundamentals")
    op.drop_index("ix_snapshots_symbol_captured_at", table_name="stock_snapshots")
    op.drop_table("stock_snapshots")
    op.drop_index("ix_watchlist_items_user_active", table_name="watchlist_items")
    op.drop_table("watchlist_items")
    op.drop_table("tickers")
    op.drop_table("users")


# ---------------------------------------------------------------------------
# FUTURE (do NOT build this in the hackathon — documented for the README):
#
# stock_snapshots will grow at (num_tracked_tickers * polls_per_day) rows/day.
# At scale, convert to a native Postgres partitioned table (PARTITION BY RANGE
# on captured_at, monthly) and drop/archive old partitions instead of DELETE.
# This migration deliberately ships an unpartitioned table + covering index,
# which is correct for a 72-hour build and a real limitation to name in your
# "Production Fault-Tolerance Architecture" section.
# ---------------------------------------------------------------------------