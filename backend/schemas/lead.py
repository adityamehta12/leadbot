import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class LeadResponse(BaseModel):
    id: uuid.UUID
    name: str | None
    contact: str | None
    cleaning_type: str | None
    property_size: str | None
    preferred_date: str | None
    special_requests: str | None
    estimated_price_range: str | None
    summary: str | None
    address: str | None
    zip_code: str | None
    status: str
    source: str | None = None
    score: int | None = None
    follow_up_at: datetime | None = None
    actual_value: Decimal | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class LeadListResponse(BaseModel):
    leads: list[LeadResponse]
    total: int
    offset: int
    limit: int


class LeadStatusUpdate(BaseModel):
    status: str  # new/contacted/qualified/converted/lost


class LeadNoteRequest(BaseModel):
    text: str


class LeadFollowUpRequest(BaseModel):
    follow_up_at: datetime | None = None


class LeadValueRequest(BaseModel):
    actual_value: Decimal


class LeadBulkStatusRequest(BaseModel):
    lead_ids: list[uuid.UUID]
    status: str


class LeadMessageRequest(BaseModel):
    channel: str  # email/sms
    content: str
