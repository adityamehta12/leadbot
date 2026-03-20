"""Billing router — Stripe checkout, webhooks, and portal."""

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from config import STRIPE_PRICE_ID, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET
from db import get_session
from services.auth_service import decode_token, get_user_by_id
from services.billing_service import (
    create_checkout_session,
    create_portal_session,
    handle_webhook_event,
)
from services.business_service import get_business_by_id

router = APIRouter(tags=["billing"])


async def _require_user(token, db):
    if not token:
        return None
    payload = decode_token(token)
    if payload is None:
        return None
    return await get_user_by_id(db, payload["sub"])


@router.get("/dashboard/billing", response_class=HTMLResponse)
async def billing_page(
    request: Request,
    token: str | None = Cookie(None),
    db: AsyncSession = Depends(get_session),
):
    user = await _require_user(token, db)
    if user is None:
        return RedirectResponse("/login")

    business = await get_business_by_id(db, user.business_id)

    templates = request.app.state.templates
    return templates.TemplateResponse("billing.html", {
        "request": request,
        "user": user,
        "business": business,
        "stripe_configured": bool(STRIPE_SECRET_KEY),
    })


@router.post("/api/billing/checkout")
async def create_checkout(
    request: Request,
    token: str | None = Cookie(None),
    db: AsyncSession = Depends(get_session),
):
    user = await _require_user(token, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Stripe billing is not configured")

    if not STRIPE_PRICE_ID:
        raise HTTPException(status_code=503, detail="Stripe price ID is not configured")

    business = await get_business_by_id(db, user.business_id)

    base = str(request.base_url).rstrip("/")
    success_url = f"{base}/dashboard/billing?session_id={{CHECKOUT_SESSION_ID}}&success=1"
    cancel_url = f"{base}/dashboard/billing?cancelled=1"

    try:
        checkout_url = await create_checkout_session(
            db=db,
            business=business,
            price_id=STRIPE_PRICE_ID,
            stripe_secret_key=STRIPE_SECRET_KEY,
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return {"url": checkout_url}


@router.post("/api/billing/webhook")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    """Handle Stripe webhook events. No auth — verified by webhook signature."""
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Stripe webhook secret not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event_type = await handle_webhook_event(
            db=db,
            payload=payload,
            sig_header=sig_header,
            webhook_secret=STRIPE_WEBHOOK_SECRET,
            stripe_secret_key=STRIPE_SECRET_KEY,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "ok", "event_type": event_type}


@router.post("/api/billing/portal")
async def billing_portal(
    request: Request,
    token: str | None = Cookie(None),
    db: AsyncSession = Depends(get_session),
):
    user = await _require_user(token, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Stripe billing is not configured")

    business = await get_business_by_id(db, user.business_id)

    base = str(request.base_url).rstrip("/")
    return_url = f"{base}/dashboard/billing"

    try:
        portal_url = await create_portal_session(
            business=business,
            stripe_secret_key=STRIPE_SECRET_KEY,
            return_url=return_url,
        )
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"url": portal_url}
