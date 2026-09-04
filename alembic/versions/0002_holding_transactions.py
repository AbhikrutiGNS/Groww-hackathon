# alembic/versions/0002_holding_transactions.py
"""add holding_transactions: append-only BUY/SELL ledger for portfolio P&L

Revision ID: 0002_holding_transactions
Revises: 0001_initial_schema
Create Date: 2026-09-04

Design notes (read before modifying):
- This is a ledger, not a mutable position table. Current quantity / avg
  cost / realized P&L are DERIVED at read time by replaying rows in
  executed_at order (see app/services/holdings.py). Never add a column
  here for "current quantity" — that belongs in the derived view, not
  the source of truth.
- Soft-void (is_voided/voided_at) mirrors watchlist_items' soft-delete:
  a mis-entered trade is corrected by voiding, never by DELETE, so the
  audit trail survives a correction.
- symbol FKs to tickers with ON DELETE RESTRICT, same as watchlist_items —
  a ticker with trade history can never be dropped out from under it.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_holding_transactions"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "holding_transactions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                   sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(20),
                   sa.ForeignKey("tickers.symbol", ondelete="RESTRICT"), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("price", sa.Numeric(14, 4), nullable=False),
        sa.Column("executed_at", sa.TIMESTAMP(timezone=True), nullable=False,
                   server_default=sa.text("now()")),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("is_voided", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("voided_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                   server_default=sa.text("now()")),
        sa.CheckConstraint("side IN ('BUY', 'SELL')", name="ck_holding_tx_side"),
        sa.CheckConstraint("quantity > 0", name="ck_holding_tx_quantity_positive"),
        sa.CheckConstraint("price >= 0", name="ck_holding_tx_price_nonnegative"),
    )
    # Powers "give me this user's ledger for these symbols, in order" —
    # the access pattern compute_positions() needs, without a scan.
    op.create_index(
        "ix_holding_tx_user_symbol_executed_at",
        "holding_transactions", ["user_id", "symbol", "executed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_holding_tx_user_symbol_executed_at", table_name="holding_transactions")
    op.drop_table("holding_transactions")