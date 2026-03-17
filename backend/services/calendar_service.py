"""Google Calendar integration: OAuth2, FreeBusy, event creation."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from models.business import Business
from models.calendar_event import CalendarBooking

# Google API imports — optional, gracefully degrade if not installed
try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    GCAL_AVAILABLE = True
except ImportError:
    GCAL_AVAILABLE = False


def _get_calendar_service(oauth_token: dict):
    if not GCAL_AVAILABLE:
        raise RuntimeError("Google Calendar libraries not installed")
    creds = Credentials(
        token=oauth_token.get("access_token"),
        refresh_token=oauth_token.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=oauth_token.get("client_id"),
        client_secret=oauth_token.get("client_secret"),
    )
    return build("calendar", "v3", credentials=creds)


async def get_available_slots(
    business: Business,
    date: str,  # YYYY-MM-DD
    duration_minutes: int = 60,
) -> list[dict]:
    """Query Google Calendar FreeBusy and return available slots."""
    if not business.google_oauth_token or not business.google_calendar_id:
        return []

    service = _get_calendar_service(business.google_oauth_token)
    calendar_id = business.google_calendar_id

    day_start = datetime.fromisoformat(f"{date}T09:00:00").replace(tzinfo=timezone.utc)
    day_end = datetime.fromisoformat(f"{date}T17:00:00").replace(tzinfo=timezone.utc)

    body = {
        "timeMin": day_start.isoformat(),
        "timeMax": day_end.isoformat(),
        "items": [{"id": calendar_id}],
    }
    freebusy = service.freebusy().query(body=body).execute()
    busy_periods = freebusy["calendars"][calendar_id]["busy"]

    # Build list of available slots
    slots = []
    current = day_start
    while current + timedelta(minutes=duration_minutes) <= day_end:
        slot_end = current + timedelta(minutes=duration_minutes)
        is_busy = any(
            datetime.fromisoformat(b["start"]) < slot_end
            and datetime.fromisoformat(b["end"]) > current
            for b in busy_periods
        )
        if not is_busy:
            slots.append({
                "start": current.isoformat(),
                "end": slot_end.isoformat(),
            })
        current += timedelta(minutes=30)  # 30-min increments

    return slots


async def book_slot(
    db: AsyncSession,
    business: Business,
    lead_id: uuid.UUID,
    start_time: datetime,
    end_time: datetime,
    attendee_email: str,
    summary: str = "Cleaning Service Appointment",
) -> CalendarBooking:
    """Create a Google Calendar event and record the booking."""
    google_event_id = None

    if business.google_oauth_token and business.google_calendar_id:
        service = _get_calendar_service(business.google_oauth_token)
        event = {
            "summary": summary,
            "start": {"dateTime": start_time.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end_time.isoformat(), "timeZone": "UTC"},
            "attendees": [{"email": attendee_email}],
        }
        created = service.events().insert(
            calendarId=business.google_calendar_id, body=event, sendUpdates="all"
        ).execute()
        google_event_id = created.get("id")

    booking = CalendarBooking(
        business_id=business.id,
        lead_id=lead_id,
        start_time=start_time,
        end_time=end_time,
        google_event_id=google_event_id,
        attendee_email=attendee_email,
        status="confirmed",
    )
    db.add(booking)
    await db.commit()
    await db.refresh(booking)
    return booking
