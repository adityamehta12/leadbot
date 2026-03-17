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
    await _attempt_delivery(db, delivery)


async def _attempt_delivery(db: AsyncSession, delivery: WebhookDelivery):
    delivery.attempts += 1
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(delivery.url, json=delivery.payload)
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
