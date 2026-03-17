"""Chat router — multi-tenant version of the original chat endpoint."""

import json
import re
import uuid
from datetime import datetime

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from config import ANTHROPIC_API_KEY, ABUSE_LIMIT, SYSTEM_PROMPT
from db import get_session
from schemas.chat import ChatRequest, ResetRequest, TTSRequest
from services import session_service
from services.business_service import get_business_by_slug, get_business_config
from services.calendar_service import get_available_slots
from services.lead_service import save_lead
from services.notification_service import notify_new_lead
from services.webhook_service import dispatch_webhook

router = APIRouter(prefix="/api", tags=["chat"])

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── Input pre-screening ──────────────────────────────────────
_PROFANITY_PATTERNS = re.compile(
    r"\b("
    r"f+u+c+k+|s+h+i+t+|a+s+s+h+o+l+e|b+i+t+c+h|c+u+n+t|d+i+c+k|"
    r"n+i+g+g+|f+a+g+|r+e+t+a+r+d|w+h+o+r+e|s+l+u+t"
    r")\b",
    re.IGNORECASE,
)

_INJECTION_PATTERNS = re.compile(
    r"("
    r"ignore\s+(your|all|previous|above)\s+(instructions|rules|prompt)|"
    r"you\s+are\s+now|"
    r"pretend\s+(to\s+be|you\s+are)|"
    r"act\s+as\s+(if|a|an)|"
    r"(reveal|show|repeat|print)\s+(your|the)\s+(system\s+)?(prompt|instructions|rules)|"
    r"jailbreak|"
    r"DAN\s+mode|"
    r"do\s+anything\s+now|"
    r"override\s+(your|safety|content)"
    r")",
    re.IGNORECASE,
)


async def screen_message(message: str, session_id: str, business_name: str) -> str | None:
    text = message.strip()
    if not text:
        return None

    strikes = await session_service.get_abuse_strikes(session_id)
    if strikes >= ABUSE_LIMIT:
        return "This conversation has ended. Please visit our website or call us directly for assistance."

    if _PROFANITY_PATTERNS.search(text):
        new_strikes = await session_service.increment_abuse_strikes(session_id)
        if new_strikes >= ABUSE_LIMIT:
            return "I'm not able to continue this conversation. If you'd like help with cleaning services in the future, feel free to come back. Have a good day!"
        return "I want to make sure I can help you. Could we keep things professional? I'm happy to assist with any cleaning needs."

    if _INJECTION_PATTERNS.search(text):
        return f"I'm Sarah, the virtual assistant for {business_name}. How can I help you with our cleaning services?"

    return None


def _resolve_system_prompt(biz_config: dict | None) -> str:
    """Use business-specific system prompt if set, otherwise the default."""
    if biz_config and biz_config.get("system_prompt"):
        base = biz_config["system_prompt"]
    elif biz_config:
        base = SYSTEM_PROMPT.replace("Sparkle Cleaning Co.", biz_config["name"])
    else:
        base = SYSTEM_PROMPT

    # Inject dynamic pricing if configured
    if biz_config and biz_config.get("service_config"):
        sc = biz_config["service_config"]
        services = sc.get("services", {})
        if services:
            name_map = {
                "regular": "Regular cleaning",
                "deep_clean": "Deep clean",
                "move_in_out": "Move-in/move-out",
                "office": "Office cleaning",
                "post_construction": "Post-construction",
            }
            lines = [f"  - {name_map.get(k, k.replace('_',' ').title())}: ${v['price_min']}-${v['price_max']}" for k, v in services.items()]
            base += "\n\nPRICING OVERRIDE — Use these prices instead of any others:\n" + "\n".join(lines)

    # Inject service area validation if configured
    if biz_config and biz_config.get("service_areas"):
        areas = biz_config["service_areas"]
        zips = areas.get("zip_codes", [])
        if zips:
            base += f"\n\nSERVICE AREA: You ONLY serve these zip codes: {', '.join(zips)}. If the customer's zip code is not in this list, politely say: \"I'm sorry, we don't currently serve that area. We cover zip codes {', '.join(zips[:5])}{'...' if len(zips) > 5 else ''}.\" Do NOT capture a lead for out-of-area customers."

    # If calendar is connected, append booking instructions
    if biz_config and biz_config.get("google_calendar_id"):
        base += """

═══════════════════════════════════════════════
APPOINTMENT BOOKING
═══════════════════════════════════════════════
This business has online booking enabled. After you have captured the lead data (included the <lead_data> tag), ALWAYS follow up by asking:
"Would you like to book an appointment? I can show you available times."
If the customer says yes, reply with EXACTLY this tag (nothing else around it):
<offer_booking />
The system will then display available time slots to the customer automatically. Do NOT make up times yourself."""

    return base


@router.post("/chat")
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_session)):
    session_id = req.session_id or str(uuid.uuid4())
    tenant_id = req.tenant_id or "default"

    # Resolve business
    biz_config = await get_business_config(db, tenant_id)
    if biz_config is None:
        raise HTTPException(status_code=404, detail="Business not found")

    business_name = biz_config["name"]
    business_id = biz_config["id"]
    system_prompt = _resolve_system_prompt(biz_config)

    # Load session
    messages = await session_service.get_session(session_id)

    # Pre-screen
    blocked = await screen_message(req.message, session_id, business_name)
    if blocked:
        await session_service.append_message(session_id, "user", req.message)
        await session_service.append_message(session_id, "assistant", blocked)

        async def blocked_response():
            yield f"data: {json.dumps({'type': 'text', 'content': blocked, 'session_id': session_id})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"

        return StreamingResponse(blocked_response(), media_type="text/event-stream")

    messages.append({"role": "user", "content": req.message})
    await session_service.save_session(session_id, messages)

    async def generate():
        full_response = ""
        with client.messages.stream(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            system=system_prompt,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                full_response += text
                if "<lead_data>" not in full_response and "<offer_booking" not in full_response:
                    yield f"data: {json.dumps({'type': 'text', 'content': text, 'session_id': session_id})}\n\n"

        # Extract lead data and clean tags
        lead_match = re.search(r"<lead_data>\s*(\{.*?\})\s*</lead_data>", full_response, re.DOTALL)
        clean_response = re.sub(r"\s*<lead_data>.*?</lead_data>", "", full_response, flags=re.DOTALL)
        clean_response = re.sub(r"\s*<offer_booking\s*/?\s*>", "", clean_response).strip()

        if "<lead_data>" in full_response or "<offer_booking" in full_response:
            yield f"data: {json.dumps({'type': 'text', 'content': clean_response, 'session_id': session_id})}\n\n"

        # Save assistant message
        await session_service.append_message(session_id, "assistant", clean_response)

        if lead_match:
            try:
                lead_data = json.loads(lead_match.group(1))
                lead_data["session_id"] = session_id
                lead_data["business"] = business_name

                # Get full transcript for storage
                transcript = await session_service.get_session(session_id)

                # Save to database
                lead = await save_lead(
                    db,
                    business_id=uuid.UUID(business_id),
                    session_id=session_id,
                    lead_data=lead_data,
                    transcript=transcript,
                )

                print(f"\n{'='*60}")
                print(f"NEW LEAD CAPTURED — {business_name} — {lead.id}")
                print(json.dumps(lead_data, indent=2))
                print(f"{'='*60}\n")

                # Webhook
                webhook_url = biz_config.get("webhook_url")
                if webhook_url:
                    await dispatch_webhook(db, lead.id, uuid.UUID(business_id), webhook_url, lead_data)

                # Notifications
                await notify_new_lead(biz_config.get("notification_config"), lead_data, business_name)

                yield f"data: {json.dumps({'type': 'lead_captured', 'lead': lead_data, 'lead_id': str(lead.id), 'session_id': session_id})}\n\n"

                # If calendar is connected, auto-offer slots for the preferred date
                if biz_config.get("google_calendar_id"):
                    preferred = lead_data.get("preferred_date", "")
                    slots = await _fetch_slots_for_lead(db, tenant_id, preferred, cleaning_type=lead_data.get("cleaning_type", ""))
                    if slots:
                        yield f"data: {json.dumps({'type': 'calendar_slots', 'slots': slots, 'lead_id': str(lead.id), 'session_id': session_id})}\n\n"

            except json.JSONDecodeError:
                pass

        # Check if AI is requesting to show booking slots (post-lead-capture follow-up)
        if "<offer_booking" in clean_response:
            # Strip the tag from display
            display_text = re.sub(r"\s*<offer_booking\s*/?\s*>", "", clean_response).strip()
            if display_text:
                # Re-send the cleaned text (the original was already sent with the tag)
                pass
            # Fetch slots
            slots = await _fetch_slots_for_lead(db, tenant_id, "")
            if slots:
                yield f"data: {json.dumps({'type': 'calendar_slots', 'slots': slots, 'session_id': session_id})}\n\n"

        yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


async def _fetch_slots_for_lead(db: AsyncSession, tenant_id: str, preferred_date: str, cleaning_type: str = "") -> list[dict]:
    """Fetch available calendar slots. Tries the preferred date, falls back to next 3 business days."""
    from datetime import date, timedelta

    business = await get_business_by_slug(db, tenant_id)
    if not business or not business.google_calendar_id:
        return []

    # Try to parse preferred date, fall back to tomorrow
    target_dates = []
    if preferred_date:
        # Try common formats
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d", "%B %d", "%b %d"):
            try:
                parsed = datetime.strptime(preferred_date.strip(), fmt).date()
                if parsed.year < 2000:
                    parsed = parsed.replace(year=date.today().year)
                target_dates.append(parsed)
                break
            except ValueError:
                continue

    if not target_dates:
        # Fall back to next 3 business days
        d = date.today() + timedelta(days=1)
        while len(target_dates) < 3:
            if d.weekday() < 5:  # Mon-Fri
                target_dates.append(d)
            d += timedelta(days=1)

    all_slots = []
    for target in target_dates:
        try:
            slots = await get_available_slots(business, target.isoformat(), cleaning_type=cleaning_type)
            all_slots.extend(slots)
        except Exception as e:
            print(f"Calendar slot fetch error: {e}")
        if len(all_slots) >= 8:
            break

    return all_slots[:8]  # Cap at 8 slots to keep UI clean


class BookSlotRequest(BaseModel):
    tenant_id: str
    lead_id: str
    start_time: str  # ISO format
    end_time: str
    attendee_email: str


@router.post("/book")
async def book_appointment(req: BookSlotRequest, db: AsyncSession = Depends(get_session)):
    """Book a calendar slot for a lead."""
    from services.calendar_service import book_slot

    business = await get_business_by_slug(db, req.tenant_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    if not business.google_calendar_id:
        raise HTTPException(status_code=400, detail="Calendar not connected")

    start = datetime.fromisoformat(req.start_time)
    end = datetime.fromisoformat(req.end_time)

    booking = await book_slot(
        db,
        business=business,
        lead_id=uuid.UUID(req.lead_id),
        start_time=start,
        end_time=end,
        attendee_email=req.attendee_email,
        summary=f"Cleaning Service — {business.name}",
    )

    return {
        "status": "booked",
        "booking_id": str(booking.id),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "google_event_id": booking.google_event_id,
    }


@router.post("/tts")
async def text_to_speech(req: TTSRequest):
    import io

    import edge_tts

    communicate = edge_tts.Communicate(req.text, req.voice, rate="+5%")
    audio_buffer = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_buffer.write(chunk["data"])

    audio_buffer.seek(0)
    return StreamingResponse(audio_buffer, media_type="audio/mpeg")


@router.post("/reset")
async def reset_session(req: ResetRequest):
    await session_service.delete_session(req.session_id)
    return {"status": "ok"}
