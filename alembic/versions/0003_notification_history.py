# alembic/versions/0003_notification_history.py
"""add notification_history: append-only log of acknowledged attention-feed
items, used to power "view last 5 notifications" once the feed goes quiet.

Revision ID: 0003_notification_history
Revises: 0002_holding_transactions
Create Date: 2026-09-05

Design notes (read before modifying):
- This is a log, not a mutable "last 5" cache. Every acknowledge() call
  appends one row per meaningful item that was on the feed at that moment;
  trimming to "last 5" happens at READ time (ORDER BY occurred_at DESC
  LIMIT 5), same philosophy as holding_transactions being replayed rather
  than storing a running balance.
- symbol has NO foreign key to tickers. A ticker can be removed from the
  watchlist (and, in principle, from `tickers`) long after its
  notification history was written; history must survive that, so it's a
  plain string snapshot of what the symbol was at the time, not a live
  reference.
- occurred_at is when the notification was captured (acknowledge time),
  not when the underlying price move happened — this is a log of "what we
  told the user", not a re-derivation of market events.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_notification_history"
down_revision = "0002_holding_transactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_history",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                   sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("current_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("percent_change", sa.Numeric(10, 4), nullable=True),
        sa.Column("is_new_addition", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("hit_52w_high", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("hit_52w_low", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("hit_week_high", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("hit_week_low", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("trend_signal", sa.String(20), nullable=True),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False,
                   server_default=sa.text("now()")),
    )
    # Powers "give me this user's most recent notifications" without a scan.
    op.create_index(
        "ix_notification_history_user_occurred_at",
        "notification_history", ["user_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notification_history_user_occurred_at", table_name="notification_history")
    op.drop_table("notification_history")
