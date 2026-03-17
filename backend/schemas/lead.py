import uuid
from datetime import datetime

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
    status: str
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
