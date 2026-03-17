"""Google Calendar integration: OAuth2, FreeBusy, event creation."""

import re
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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


def _normalize_cleaning_type(raw: str | None) -> str | None:
    """Normalize a cleaning type string to a snake_case service key."""
    if not raw:
        return None
    return re.sub(r"[\s\-]+", "_", raw.strip().lower())


def _lookup_duration(service_config: dict | None, cleaning_type: str | None) -> int:
    """Return duration_minutes for the given cleaning type, or 60 as fallback."""
    if not service_config:
        return 60
    services: dict = service_config.get("services", {})
    key = _normalize_cleaning_type(cleaning_type)
    if key and key in services:
        return services[key].get("duration_minutes", 60)
    # Try to find a loose match (e.g. "deep clean" -> "deep_clean")
    if key:
        for svc_key, svc_val in services.items():
            if _normalize_cleaning_type(svc_key) == key:
                return svc_val.get("duration_minutes", 60)
    return 60


async def get_available_slots(
    business: Business,
    date: str,  # YYYY-MM-DD
    cleaning_type: str | None = None,
) -> list[dict]:
    """Query Google Calendar FreeBusy and return available slots."""
    if not business.google_oauth_token or not business.google_calendar_id:
        return []

    # --- Resolve duration & buffer from service_config ---
    service_config = business.service_config or {}
    duration_minutes = _lookup_duration(service_config, cleaning_type)
    buffer_minutes = service_config.get("buffer_minutes", 0)
    step_minutes = duration_minutes + buffer_minutes

    # --- Timezone-aware business hours ---
    tz = ZoneInfo(getattr(business, "timezone", None) or "America/New_York")
    default_hours = {"start": "09:00", "end": "17:00", "days": [0, 1, 2, 3, 4]}
    business_hours = getattr(business, "business_hours", None) or default_hours

    # Check day-of-week (Monday=0)
    requested_date = datetime.strptime(date, "%Y-%m-%d").date()
    if requested_date.weekday() not in business_hours.get("days", default_hours["days"]):
        return []

    # Build local start/end then convert to UTC for the FreeBusy query
    start_local = datetime.combine(
        requested_date,
        datetime.strptime(business_hours.get("start", "09:00"), "%H:%M").time(),
        tzinfo=tz,
    )
    end_local = datetime.combine(
        requested_date,
        datetime.strptime(business_hours.get("end", "17:00"), "%H:%M").time(),
        tzinfo=tz,
    )
    day_start = start_local.astimezone(timezone.utc)
    day_end = end_local.astimezone(timezone.utc)

    # --- FreeBusy query ---
    service = _get_calendar_service(business.google_oauth_token)
    calendar_id = business.google_calendar_id

    body = {
        "timeMin": day_start.isoformat(),
        "timeMax": day_end.isoformat(),
        "items": [{"id": calendar_id}],
    }
    freebusy = service.freebusy().query(body=body).execute()
    busy_periods = freebusy["calendars"][calendar_id]["busy"]

    # --- Build list of available slots ---
    slots: list[dict] = []
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
            if len(slots) >= 8:
                break
        current += timedelta(minutes=step_minutes)

    return slots


async def book_slot(
    db: AsyncSession,
    business: Business,
    lead_id: uuid.UUID,
    start_time: datetime,
    end_time: datetime,
    attendee_email: str,
    cleaning_type: str | None = None,
) -> CalendarBooking:
    """Create a Google Calendar event and record the booking."""
    summary = f"{cleaning_type or 'Cleaning'} — {business.name}"
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
