"""Webhook dispatch with retry + dead letter queue."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session_ctx
from models.webhook_log import WebhookDelivery

MAX_RETRIES = 3
RETRY_DELAYS = [0, 30, 120]  # seconds: immediate, 30s, 2min


async def dispatch_webhook(
    db: AsyncSession,
    lead_id: uuid.UUID,
    business_id: uuid.UUID,
    url: str,
    payload: dict,
    event_type: str = "lead.captured",
):
    """Create a webhook delivery record and attempt first delivery."""
    delivery = WebhookDelivery(
        lead_id=lead_id,
        business_id=business_id,
        url=url,
        payload=payload,
        status="pending",
        attempts=0,
    )
    db.add(delivery)
    await db.commit()
    await db.refresh(delivery)

    # Attempt immediate delivery
    await _attempt_delivery(db, delivery, event_type=event_type)


async def _attempt_delivery(db: AsyncSession, delivery: WebhookDelivery, event_type: str = "lead.captured"):
    delivery.attempts += 1
    try:
        headers = {"X-LeadBot-Event": event_type}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(delivery.url, json=delivery.payload, headers=headers)
            resp.raise_for_status()
        delivery.status = "success"
        delivery.last_error = None
        delivery.next_retry_at = None
    except Exception as e:
        delivery.last_error = str(e)[:500]
        if delivery.attempts >= MAX_RETRIES:
            delivery.status = "failed"
            delivery.next_retry_at = None
        else:
            delay = RETRY_DELAYS[min(delivery.attempts, len(RETRY_DELAYS) - 1)]
            delivery.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            delivery.status = "pending"

    await db.commit()


async def retry_pending_webhooks():
    """Background task: retry pending webhooks whose next_retry_at has passed."""
    try:
        async with get_session_ctx() as db:
            now = datetime.now(timezone.utc)
            result = await db.execute(
                select(WebhookDelivery).where(
                    WebhookDelivery.status == "pending",
                    WebhookDelivery.next_retry_at <= now,
                    WebhookDelivery.attempts < MAX_RETRIES,
                )
            )
            deliveries = result.scalars().all()
            for delivery in deliveries:
                await _attempt_delivery(db, delivery)
    except Exception as e:
        print(f"Webhook retry error: {e}")


async def webhook_retry_loop():
    """Run the retry loop every 60 seconds."""
    while True:
        await asyncio.sleep(60)
        await retry_pending_webhooks()


async def dispatch_event_webhooks(
    db: AsyncSession,
    business_id: uuid.UUID,
    event_type: str,
    payload: dict,
    lead_id: uuid.UUID | None = None,
):
    """Dispatch webhooks for a specific event type.

    Looks up event-specific webhook URLs from the business's notification_config.
    notification_config can have a "webhooks" dict mapping event types to URLs, e.g.:
    {
        "webhooks": {
            "lead.captured": "https://example.com/hook1",
            "booking.created": "https://example.com/hook2",
        }
    }
    """
    from services.business_service import get_business_by_id

    business = await get_business_by_id(db, business_id)
    if business is None:
        return

    nc = business.notification_config or {}
    webhooks_config = nc.get("webhooks", {})

    # Check for event-specific URL
    url = webhooks_config.get(event_type)
    if not url:
        # Fall back to the global webhook_url
        url = business.webhook_url

    if not url:
        return

    # Use a dummy lead_id if none provided
    effective_lead_id = lead_id or uuid.UUID("00000000-0000-0000-0000-000000000000")

    await dispatch_webhook(
        db=db,
        lead_id=effective_lead_id,
        business_id=business_id,
        url=url,
        payload=payload,
        event_type=event_type,
    )
