import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr


class SlotResponse(BaseModel):
    start: str
    end: str


class BookingRequest(BaseModel):
    lead_id: uuid.UUID
    start_time: datetime
    end_time: datetime
    attendee_email: EmailStr


class BookingResponse(BaseModel):
    id: uuid.UUID
    start_time: datetime
    end_time: datetime
    attendee_email: str | None
    status: str
    google_event_id: str | None
