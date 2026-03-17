import uuid

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, new_uuid


class Business(TimestampMixin, Base):
    __tablename__ = "businesses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    slug: Mapped[str] = mapped_column(String(63), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    color: Mapped[str] = mapped_column(String(7), default="#2563eb")
    greeting: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    google_calendar_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    google_oauth_token: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    notification_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    timezone: Mapped[str] = mapped_column(String(50), default="America/New_York")
    business_hours: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    service_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    service_areas: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    users = relationship("BusinessUser", back_populates="business", cascade="all, delete-orphan")
    leads = relationship("Lead", back_populates="business", cascade="all, delete-orphan")
