"""Automated follow-up background loop.

Runs every 5 minutes, checks for leads that need auto follow-up,
and sends the configured template message via email.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session_ctx
from models.business import Business
from models.lead import Lead
from models.lead_activity import LeadActivity
from models.lead_message import LeadMessage
from services.notification_service import send_message_to_lead

logger = logging.getLogger(__name__)

LOOP_INTERVAL_SECONDS = 300  # 5 minutes


def _extract_email(contact: str | None) -> str | None:
    """Try to extract an email address from the contact field."""
    if not contact:
        return None
    match = re.search(r"[^@\s]+@[^@\s]+\.[^@\s]+", contact)
    return match.group(0) if match else None


async def _process_business_followups(db: AsyncSession, business: Business) -> int:
    """Process auto follow-ups for a single business. Returns count of messages sent."""
    nc = business.notification_config or {}
    auto_followup = nc.get("auto_followup")
    if not auto_followup or not auto_followup.get("enabled"):
        return 0

    delay_hours = auto_followup.get("delay_hours", 1)
    template = auto_followup.get("template", "")
    if not template:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(hours=delay_hours)

    # Find leads that are still 'new', created before the cutoff, and have no outbound messages yet
    leads_result = await db.execute(
        select(Lead).where(
            Lead.business_id == business.id,
            Lead.status == "new",
            Lead.created_at <= cutoff,
        )
    )
    candidates = leads_result.scalars().all()

    sent = 0
    for lead in candidates:
        # Check if any outbound message already exists for this lead
        msg_check = await db.execute(
            select(LeadMessage.id).where(
                LeadMessage.lead_id == lead.id,
                LeadMessage.direction == "outbound",
            ).limit(1)
        )
        if msg_check.scalar_one_or_none() is not None:
            continue

        email = _extract_email(lead.contact)
        if not email:
            continue

        # Personalize template
        content = template.replace("{{name}}", lead.name or "there")
        content = content.replace("{{business_name}}", business.name)

        try:
            await send_message_to_lead("email", email, content, business.name)
        except Exception:
            logger.exception("Failed to send auto follow-up to %s for lead %s", email, lead.id)
            continue

        db.add(LeadMessage(
            lead_id=lead.id,
            business_id=business.id,
            direction="outbound",
            channel="email",
            content=content,
            sent_by=None,  # automated
        ))

        db.add(LeadActivity(
            lead_id=lead.id,
            business_id=business.id,
            action="auto_followup_sent",
            detail={"channel": "email", "to": email},
            actor_id=None,
        ))

        sent += 1

    if sent:
        await db.commit()
    return sent


async def _run_once():
    """Single pass: check all businesses for pending auto follow-ups."""
    try:
        async with get_session_ctx() as db:
            result = await db.execute(select(Business))
            businesses = result.scalars().all()

            total_sent = 0
            for biz in businesses:
                count = await _process_business_followups(db, biz)
                total_sent += count

            if total_sent:
                logger.info("Auto follow-up: sent %d messages", total_sent)
    except Exception:
        logger.exception("Error in follow-up loop iteration")


async def followup_loop():
    """Background task that runs every 5 minutes to send auto follow-ups."""
    logger.info("Follow-up background loop started")
    while True:
        await _run_once()
        await asyncio.sleep(LOOP_INTERVAL_SECONDS)
