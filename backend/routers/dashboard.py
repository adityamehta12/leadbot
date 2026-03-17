"""Server-rendered dashboard with Jinja2 + HTMX."""

import uuid

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from config import GOOGLE_CLIENT_ID
from db import get_session
from models.webhook_log import WebhookDelivery
from services.auth_service import decode_token, get_user_by_id
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

    templates = request.app.state.templates
    return templates.TemplateResponse("lead_detail.html", {
        "request": request,
        "user": user,
        "business": business,
        "lead": lead,
        "transcript": lead.conversation_transcript or [],
    })


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
    )

    return RedirectResponse("/dashboard/settings?saved=1", status_code=303)


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
