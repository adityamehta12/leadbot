"""Address, timezone, business hours, service config, service areas

Revision ID: 004
Revises: 003
Create Date: 2026-03-17
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── leads: address fields ────────────────────────────────
    op.add_column("leads", sa.Column("address", sa.Text, nullable=True))
    op.add_column("leads", sa.Column("zip_code", sa.String(10), nullable=True))

    # ── businesses: operations config ────────────────────────
    op.add_column("businesses", sa.Column("timezone", sa.String(50), server_default="America/New_York"))
    op.add_column("businesses", sa.Column("business_hours", postgresql.JSONB, server_default='{"start":"09:00","end":"17:00","days":[0,1,2,3,4]}'))
    op.add_column("businesses", sa.Column("service_config", postgresql.JSONB, nullable=True))
    op.add_column("businesses", sa.Column("service_areas", postgresql.JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("businesses", "service_areas")
    op.drop_column("businesses", "service_config")
    op.drop_column("businesses", "business_hours")
    op.drop_column("businesses", "timezone")
    op.drop_column("leads", "zip_code")
    op.drop_column("leads", "address")
