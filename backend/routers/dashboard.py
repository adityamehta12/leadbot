"""Server-rendered dashboard with Jinja2 + HTMX."""

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from config import GOOGLE_CLIENT_ID
from db import get_session
from models.calendar_event import CalendarBooking
from models.lead import Lead
from models.lead_activity import LeadActivity
from models.lead_message import LeadMessage
from models.user import BusinessUser
from models.webhook_log import WebhookDelivery
from services.auth_service import decode_token, get_user_by_id, hash_password
from services.business_service import get_business_by_id, update_business
from services.lead_service import get_lead_by_id, get_lead_stats, get_leads

router = APIRouter(tags=["dashboard"])


async def _get_current_user(token: str | None = Cookie(None), db: AsyncSession = Depends(get_session)):
    if not token:
        return None
    payload = decode_token(token)
    if payload is None:
        return None
    user = await get_user_by_id(db, payload["sub"])
    return user


async def _require_user(token: str | None, db: AsyncSession):
    """Helper: decode token and return user or None."""
    if not token:
        return None
    payload = decode_token(token)
    if payload is None:
        return None
    return await get_user_by_id(db, payload["sub"])


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    status: str | None = None,
    page: int = 1,
    token: str | None = Cookie(None),
    db: AsyncSession = Depends(get_session),
):
    if not token:
        return RedirectResponse("/login")
    payload = decode_token(token)
    if payload is None:
        return RedirectResponse("/login")

    user = await get_user_by_id(db, payload["sub"])
    if user is None:
        return RedirectResponse("/login")

    business = await get_business_by_id(db, user.business_id)
    limit = 20
    offset = (page - 1) * limit
    leads, total = await get_leads(db, user.business_id, status=status, offset=offset, limit=limit)
    stats = await get_lead_stats(db, user.business_id)

    templates = request.app.state.templates
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "business": business,
        "leads": leads,
        "total": total,
        "page": page,
        "pages": max(1, (total + limit - 1) // limit),
        "status_filter": status or "",
        "stats": stats,
    })


@router.get("/dashboard/leads/{lead_id}", response_class=HTMLResponse)
async def lead_detail_page(
    lead_id: uuid.UUID,
    request: Request,
    token: str | None = Cookie(None),
    db: AsyncSession = Depends(get_session),
):
    if not token:
        return RedirectResponse("/login")
    payload = decode_token(token)
    if payload is None:
        return RedirectResponse("/login")

    user = await get_user_by_id(db, payload["sub"])
    if user is None:
        return RedirectResponse("/login")

    business = await get_business_by_id(db, user.business_id)
    lead = await get_lead_by_id(db, lead_id, user.business_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Fetch notes, messages, activity, team_members
    notes = lead.notes or []

    messages_result = await db.execute(
        select(LeadMessage)
        .where(LeadMessage.lead_id == lead_id, LeadMessage.business_id == user.business_id)
        .order_by(LeadMessage.created_at.desc())
    )
    messages = messages_result.scalars().all()

    activity_result = await db.execute(
        select(LeadActivity)
        .where(LeadActivity.lead_id == lead_id, LeadActivity.business_id == user.business_id)
        .order_by(LeadActivity.created_at.desc())
    )
    activity = activity_result.scalars().all()

    team_result = await db.execute(
        select(BusinessUser).where(BusinessUser.business_id == user.business_id)
    )
    team_members = team_result.scalars().all()

    templates = request.app.state.templates
    return templates.TemplateResponse("lead_detail.html", {
        "request": request,
        "user": user,
        "business": business,
        "lead": lead,
        "transcript": lead.conversation_transcript or [],
        "notes": notes,
        "messages": messages,
        "activity": activity,
        "team_members": team_members,
    })


# ── Bookings page ─────────────────────────────────────────────


@router.get("/dashboard/bookings", response_class=HTMLResponse)
async def bookings_page(
    request: Request,
    filter: str | None = None,
    token: str | None = Cookie(None),
    db: AsyncSession = Depends(get_session),
):
    user = await _require_user(token, db)
    if user is None:
        return RedirectResponse("/login")

    business = await get_business_by_id(db, user.business_id)
    now = datetime.now(timezone.utc)

    # Base query with joined Lead data
    query = (
        select(CalendarBooking, Lead)
        .outerjoin(Lead, CalendarBooking.lead_id == Lead.id)
        .where(CalendarBooking.business_id == user.business_id)
    )

    if filter == "past":
        query = query.where(CalendarBooking.start_time < now, CalendarBooking.status != "cancelled")
        query = query.order_by(CalendarBooking.start_time.desc())
    elif filter == "cancelled":
        query = query.where(CalendarBooking.status == "cancelled")
        query = query.order_by(CalendarBooking.start_time.desc())
    else:
        # Default: upcoming
        query = query.where(CalendarBooking.start_time >= now, CalendarBooking.status != "cancelled")
        query = query.order_by(CalendarBooking.start_time.asc())

    result = await db.execute(query.limit(100))
    rows = result.all()
    bookings = [{"booking": row[0], "lead": row[1]} for row in rows]

    # Get team members for assignment dropdown
    team_result = await db.execute(
        select(BusinessUser).where(BusinessUser.business_id == user.business_id)
    )
    team_members = team_result.scalars().all()

    templates = request.app.state.templates
    return templates.TemplateResponse("bookings.html", {
        "request": request,
        "user": user,
        "business": business,
        "bookings": bookings,
        "team_members": team_members,
        "filter": filter or "upcoming",
    })


# ── Booking management APIs ───────────────────────────────────


@router.patch("/api/bookings/{booking_id}/cancel")
async def cancel_booking(
    booking_id: uuid.UUID,
    token: str | None = Cookie(None),
    db: AsyncSession = Depends(get_session),
):
    user = await _require_user(token, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    result = await db.execute(
        select(CalendarBooking).where(
            CalendarBooking.id == booking_id,
            CalendarBooking.business_id == user.business_id,
        )
    )
    booking = result.scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")

    booking.status = "cancelled"
    await db.commit()
    return {"status": "cancelled", "booking_id": str(booking_id)}


class AssignBookingRequest(BaseModel):
    user_id: uuid.UUID


@router.patch("/api/bookings/{booking_id}/assign")
async def assign_booking(
    booking_id: uuid.UUID,
    body: AssignBookingRequest,
    token: str | None = Cookie(None),
    db: AsyncSession = Depends(get_session),
):
    user = await _require_user(token, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    result = await db.execute(
        select(CalendarBooking).where(
            CalendarBooking.id == booking_id,
            CalendarBooking.business_id == user.business_id,
        )
    )
    booking = result.scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")

    booking.assigned_to = body.user_id
    await db.commit()
    return {"status": "assigned", "booking_id": str(booking_id), "assigned_to": str(body.user_id)}


# ── Team page ─────────────────────────────────────────────────


@router.get("/dashboard/team", response_class=HTMLResponse)
async def team_page(
    request: Request,
    token: str | None = Cookie(None),
    db: AsyncSession = Depends(get_session),
):
    user = await _require_user(token, db)
    if user is None:
        return RedirectResponse("/login")

    # Only owner/manager can access team page
    if user.role not in ("owner", "manager"):
        raise HTTPException(status_code=403, detail="Only owners and managers can manage the team")

    business = await get_business_by_id(db, user.business_id)

    result = await db.execute(
        select(BusinessUser).where(BusinessUser.business_id == user.business_id)
    )
    members = result.scalars().all()

    templates = request.app.state.templates
    return templates.TemplateResponse("team.html", {
        "request": request,
        "user": user,
        "business": business,
        "members": members,
    })


# ── Team management APIs ──────────────────────────────────────


class TeamInviteRequest(BaseModel):
    email: EmailStr
    name: str
    role: str = "crew"


@router.post("/api/team/invite")
async def invite_team_member(
    body: TeamInviteRequest,
    token: str | None = Cookie(None),
    db: AsyncSession = Depends(get_session),
):
    user = await _require_user(token, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if user.role not in ("owner", "manager"):
        raise HTTPException(status_code=403, detail="Only owners and managers can invite team members")

    if body.role not in ("owner", "manager", "crew"):
        raise HTTPException(status_code=400, detail="Role must be owner, manager, or crew")

    # Check unique email
    existing = await db.execute(
        select(BusinessUser).where(BusinessUser.email == body.email)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A user with this email already exists")

    # Create user with a temporary password (they should reset it)
    import secrets
    temp_password = secrets.token_urlsafe(12)

    new_user = BusinessUser(
        business_id=user.business_id,
        email=body.email,
        password_hash=hash_password(temp_password),
        name=body.name,
        is_owner=(body.role == "owner"),
        role=body.role,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    return {
        "status": "invited",
        "user_id": str(new_user.id),
        "email": new_user.email,
        "temp_password": temp_password,
    }


@router.delete("/api/team/{user_id}")
async def remove_team_member(
    user_id: uuid.UUID,
    token: str | None = Cookie(None),
    db: AsyncSession = Depends(get_session),
):
    user = await _require_user(token, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if user.role not in ("owner", "manager"):
        raise HTTPException(status_code=403, detail="Only owners and managers can remove team members")

    # Cannot remove yourself
    if str(user.id) == str(user_id):
        raise HTTPException(status_code=400, detail="Cannot remove yourself")

    result = await db.execute(
        select(BusinessUser).where(
            BusinessUser.id == user_id,
            BusinessUser.business_id == user.business_id,
        )
    )
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Managers cannot remove owners
    if user.role == "manager" and target.role == "owner":
        raise HTTPException(status_code=403, detail="Managers cannot remove owners")

    await db.delete(target)
    await db.commit()
    return {"status": "removed", "user_id": str(user_id)}


# ── Settings ──────────────────────────────────────────────────


@router.get("/dashboard/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    token: str | None = Cookie(None),
    db: AsyncSession = Depends(get_session),
):
    if not token:
        return RedirectResponse("/login")
    payload = decode_token(token)
    if payload is None:
        return RedirectResponse("/login")

    user = await get_user_by_id(db, payload["sub"])
    if user is None:
        return RedirectResponse("/login")

    business = await get_business_by_id(db, user.business_id)

    templates = request.app.state.templates
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "user": user,
        "business": business,
        "google_client_configured": bool(GOOGLE_CLIENT_ID),
    })


@router.post("/dashboard/settings")
async def update_settings(
    request: Request,
    token: str | None = Cookie(None),
    db: AsyncSession = Depends(get_session),
):
    if not token:
        return RedirectResponse("/login", status_code=303)
    payload = decode_token(token)
    if payload is None:
        return RedirectResponse("/login", status_code=303)

    user = await get_user_by_id(db, payload["sub"])
    if user is None:
        return RedirectResponse("/login", status_code=303)

    form = await request.form()
    business = await get_business_by_id(db, user.business_id)

    notification_config = business.notification_config or {}
    if form.get("notification_email"):
        notification_config["email"] = form["notification_email"]
    if form.get("notification_sms"):
        notification_config["sms"] = form["notification_sms"]

    # Auto-followup config
    if form.get("auto_followup_enabled"):
        notification_config["auto_followup"] = {
            "enabled": True,
            "delay_hours": int(form.get("auto_followup_hours") or 24),
            "channel": form.get("auto_followup_channel") or "email",
            "message": form.get("auto_followup_message") or "",
        }
    else:
        notification_config.pop("auto_followup", None)

    # Business hours
    hours_days = form.getlist("hours_days")
    business_hours = {
        "start": form.get("hours_start") or "09:00",
        "end": form.get("hours_end") or "17:00",
        "days": [int(d) for d in hours_days] if hours_days else [0, 1, 2, 3, 4],
    }

    # Service config
    service_config = {"services": {}, "buffer_minutes": int(form.get("buffer_minutes") or 30)}
    for key in ["regular", "deep_clean", "move_in_out", "office", "post_construction"]:
        dur = form.get(f"svc_{key}_duration")
        pmin = form.get(f"svc_{key}_min")
        pmax = form.get(f"svc_{key}_max")
        if dur or pmin or pmax:
            service_config["services"][key] = {
                "duration_minutes": int(dur) if dur else 120,
                "price_min": int(pmin) if pmin else 0,
                "price_max": int(pmax) if pmax else 0,
            }

    # Service areas
    zip_text = form.get("service_zips", "").strip()
    service_areas = None
    if zip_text:
        zips = [z.strip() for z in zip_text.split(",") if z.strip()]
        if zips:
            service_areas = {"zip_codes": zips}

    # FAQ entries (parse JSON from form)
    faq_entries = None
    faq_raw = form.get("faq_entries", "").strip()
    if faq_raw:
        try:
            faq_entries = json.loads(faq_raw)
        except json.JSONDecodeError:
            pass  # Ignore invalid JSON

    await update_business(
        db,
        business,
        name=form.get("name") or business.name,
        color=form.get("color") or business.color,
        greeting=form.get("greeting") or business.greeting,
        webhook_url=form.get("webhook_url") or business.webhook_url,
        system_prompt=form.get("system_prompt") or None,
        notification_config=notification_config,
        timezone=form.get("timezone") or business.timezone,
        business_hours=business_hours,
        service_config=service_config if service_config["services"] else None,
        service_areas=service_areas,
        after_hours_message=form.get("after_hours_message") or None,
        faq_entries=faq_entries,
        widget_language=form.get("widget_language") or business.widget_language,
    )

    return RedirectResponse("/dashboard/settings?saved=1", status_code=303)


# ── Webhooks ──────────────────────────────────────────────────


@router.get("/dashboard/webhooks", response_class=HTMLResponse)
async def webhooks_page(
    request: Request,
    token: str | None = Cookie(None),
    db: AsyncSession = Depends(get_session),
):
    if not token:
        return RedirectResponse("/login")
    payload = decode_token(token)
    if payload is None:
        return RedirectResponse("/login")

    user = await get_user_by_id(db, payload["sub"])
    if user is None:
        return RedirectResponse("/login")

    business = await get_business_by_id(db, user.business_id)

    result = await db.execute(
        select(WebhookDelivery)
        .where(WebhookDelivery.business_id == user.business_id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(100)
    )
    deliveries = result.scalars().all()

    templates = request.app.state.templates
    return templates.TemplateResponse("webhooks.html", {
        "request": request,
        "user": user,
        "business": business,
        "deliveries": deliveries,
    })


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse("login.html", {"request": request})
