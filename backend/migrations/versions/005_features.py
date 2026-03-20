"""Lead management, team, billing, widget features

Revision ID: 005
Revises: 004
Create Date: 2026-03-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── leads: new columns ────────────────────────────────────
    op.add_column("leads", sa.Column("source", sa.String(255), nullable=True))
    op.add_column("leads", sa.Column("notes", postgresql.JSONB, nullable=True))
    op.add_column("leads", sa.Column("follow_up_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("leads", sa.Column("score", sa.Integer, nullable=True))
    op.add_column("leads", sa.Column("actual_value", sa.Numeric(10, 2), nullable=True))

    # ── businesses: new columns ───────────────────────────────
    op.add_column("businesses", sa.Column("after_hours_message", sa.Text, nullable=True))
    op.add_column("businesses", sa.Column("faq_entries", postgresql.JSONB, nullable=True))
    op.add_column("businesses", sa.Column("stripe_customer_id", sa.String(255), nullable=True))
    op.add_column("businesses", sa.Column("stripe_subscription_id", sa.String(255), nullable=True))
    op.add_column("businesses", sa.Column("plan", sa.String(20), server_default="free"))
    op.add_column("businesses", sa.Column("widget_language", sa.String(5), server_default="en"))

    # ── business_users: role ──────────────────────────────────
    op.add_column("business_users", sa.Column("role", sa.String(20), server_default="owner"))

    # ── calendar_bookings: recurrence & crew ──────────────────
    op.add_column("calendar_bookings", sa.Column("recurrence", sa.String(20), nullable=True))
    op.add_column("calendar_bookings", sa.Column("assigned_to", sa.Uuid, nullable=True))

    # ── lead_messages table ───────────────────────────────────
    op.create_table(
        "lead_messages",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("lead_id", sa.Uuid, sa.ForeignKey("leads.id"), index=True, nullable=False),
        sa.Column("business_id", sa.Uuid, sa.ForeignKey("businesses.id"), index=True, nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("sent_by", sa.Uuid, sa.ForeignKey("business_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── lead_activity table ───────────────────────────────────
    op.create_table(
        "lead_activity",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("lead_id", sa.Uuid, sa.ForeignKey("leads.id"), index=True, nullable=False),
        sa.Column("business_id", sa.Uuid, sa.ForeignKey("businesses.id"), index=True, nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("detail", postgresql.JSONB, nullable=True),
        sa.Column("actor_id", sa.Uuid, sa.ForeignKey("business_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("lead_activity")
    op.drop_table("lead_messages")
    op.drop_column("calendar_bookings", "assigned_to")
    op.drop_column("calendar_bookings", "recurrence")
    op.drop_column("business_users", "role")
    op.drop_column("businesses", "widget_language")
    op.drop_column("businesses", "plan")
    op.drop_column("businesses", "stripe_subscription_id")
    op.drop_column("businesses", "stripe_customer_id")
    op.drop_column("businesses", "faq_entries")
    op.drop_column("businesses", "after_hours_message")
    op.drop_column("leads", "actual_value")
    op.drop_column("leads", "score")
    op.drop_column("leads", "follow_up_at")
    op.drop_column("leads", "notes")
    op.drop_column("leads", "source")
