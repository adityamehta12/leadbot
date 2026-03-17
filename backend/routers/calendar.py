import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session
from schemas.calendar import BookingRequest, BookingResponse, SlotResponse
from services.business_service import get_business_by_slug
from services.calendar_service import book_slot, get_available_slots

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


@router.get("/{tenant_id}/slots")
async def available_slots(
    tenant_id: str,
    date: str,  # YYYY-MM-DD query param
    db: AsyncSession = Depends(get_session),
) -> list[SlotResponse]:
    business = await get_business_by_slug(db, tenant_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    slots = await get_available_slots(business, date)
    return [SlotResponse(**s) for s in slots]


@router.post("/{tenant_id}/book")
async def book_appointment(
    tenant_id: str,
    req: BookingRequest,
    db: AsyncSession = Depends(get_session),
) -> BookingResponse:
    business = await get_business_by_slug(db, tenant_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")

    booking = await book_slot(
        db,
        business=business,
        lead_id=req.lead_id,
        start_time=req.start_time,
        end_time=req.end_time,
        attendee_email=req.attendee_email,
    )

    return BookingResponse(
        id=booking.id,
        start_time=booking.start_time,
        end_time=booking.end_time,
        attendee_email=booking.attendee_email,
        status=booking.status,
        google_event_id=booking.google_event_id,
    )
