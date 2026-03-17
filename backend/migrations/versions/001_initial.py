"""Initial schema: businesses, business_users, leads

Revision ID: 001
Revises:
Create Date: 2026-03-16
"""

import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── businesses ───────────────────────────────────────────────
    op.create_table(
        "businesses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("slug", sa.String(63), unique=True, nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("color", sa.String(7), nullable=False, server_default="#2563eb"),
        sa.Column("greeting", sa.Text, nullable=True),
        sa.Column("system_prompt", sa.Text, nullable=True),
        sa.Column("webhook_url", sa.Text, nullable=True),
        sa.Column("google_calendar_id", sa.Text, nullable=True),
        sa.Column("google_oauth_token", postgresql.JSONB, nullable=True),
        sa.Column("notification_config", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── business_users ───────────────────────────────────────────
    op.create_table(
        "business_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("businesses.id"), nullable=False, index=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_owner", sa.Boolean, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── leads ────────────────────────────────────────────────────
    op.create_table(
        "leads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("businesses.id"), nullable=False, index=True),
        sa.Column("session_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("contact", sa.String(255), nullable=True),
        sa.Column("cleaning_type", sa.String(255), nullable=True),
        sa.Column("property_size", sa.String(255), nullable=True),
        sa.Column("preferred_date", sa.String(255), nullable=True),
        sa.Column("special_requests", sa.Text, nullable=True),
        sa.Column("estimated_price_range", sa.String(255), nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("raw_json", postgresql.JSONB, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="new"),
        sa.Column("conversation_transcript", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── Seed default business from env vars ──────────────────────
    business_name = os.getenv("BUSINESS_NAME", "Sparkle Cleaning Co.")
    business_color = os.getenv("BUSINESS_COLOR", "#2563eb")
    greeting = os.getenv(
        "GREETING",
        "Hi! I'm Sarah from Sparkle Cleaning. I can help you get a quick estimate. What kind of cleaning are you looking for?",
    )
    webhook_url = os.getenv("WEBHOOK_URL", "")

    op.execute(
        sa.text(
            """INSERT INTO businesses (slug, name, color, greeting, webhook_url)
               VALUES ('default', :name, :color, :greeting, :webhook)
               ON CONFLICT (slug) DO NOTHING"""
        ).bindparams(name=business_name, color=business_color, greeting=greeting, webhook=webhook_url or None)
    )


def downgrade() -> None:
    op.drop_table("leads")
    op.drop_table("business_users")
    op.drop_table("businesses")
