import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, new_uuid


class Lead(TimestampMixin, Base):
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("businesses.id"), index=True)
    session_id: Mapped[str] = mapped_column(String(255))
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cleaning_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    property_size: Mapped[str | None] = mapped_column(String(255), nullable=True)
    preferred_date: Mapped[str | None] = mapped_column(String(255), nullable=True)
    special_requests: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_price_range: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="new")
    conversation_transcript: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    business = relationship("Business", back_populates="leads")
