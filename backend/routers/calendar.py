import json
import uuid
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
from db import get_session
from schemas.calendar import BookingRequest, BookingResponse, SlotResponse
from services.auth_service import decode_token, get_user_by_id
from services.business_service import get_business_by_id, get_business_by_slug
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


# ── Google Calendar OAuth ───────────────────────────────────


@router.get("/connect")
async def calendar_connect(
    request: Request,
    token: str | None = Cookie(None),
):
    """Initiate Google Calendar OAuth flow."""
    if not token:
        return RedirectResponse("/login")
    payload = decode_token(token)
    if payload is None:
        return RedirectResponse("/login")

    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")

    base = str(request.base_url).replace("http://", "https://")
    redirect_uri = base + "api/calendar/callback"

    params = urlencode({
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/calendar",
        "access_type": "offline",
        "prompt": "consent",
        "state": token,
    })

    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")


@router.get("/callback")
async def calendar_callback(
    request: Request,
    code: str,
    state: str,
    db: AsyncSession = Depends(get_session),
):
    """Handle Google OAuth callback — exchange code for tokens and save."""
    payload = decode_token(state)
    if payload is None:
        return RedirectResponse("/login")

    user = await get_user_by_id(db, payload["sub"])
    if user is None:
        return RedirectResponse("/login")

    business = await get_business_by_id(db, user.business_id)

    base = str(request.base_url).replace("http://", "https://")
    redirect_uri = base + "api/calendar/callback"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to exchange authorization code")

    token_data = resp.json()
    # Include client credentials so calendar_service can refresh the token
    token_data["client_id"] = GOOGLE_CLIENT_ID
    token_data["client_secret"] = GOOGLE_CLIENT_SECRET

    business.google_oauth_token = json.dumps(token_data)
    business.google_calendar_id = "primary"
    await db.commit()

    return RedirectResponse("/dashboard/settings?calendar=connected")
