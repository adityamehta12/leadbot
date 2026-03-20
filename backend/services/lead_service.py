"""Lead persistence — saves captured leads to the database."""

import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.lead import Lead


def score_lead(lead_data: dict) -> int:
    """Score a lead 0-100 based on data completeness."""
    score = 0
    contact = lead_data.get("contact") or ""
    if contact:
        score += 20
        # Bonus for email-looking contact
        if re.search(r"[^@\s]+@[^@\s]+\.[^@\s]+", contact):
            score += 10
    if lead_data.get("address"):
        score += 15
    if lead_data.get("preferred_date"):
        score += 15
    if lead_data.get("cleaning_type"):
        score += 15
    if lead_data.get("property_size"):
        score += 15
    if lead_data.get("zip_code"):
        score += 10
    return min(score, 100)


async def save_lead(
    db: AsyncSession,
    business_id: uuid.UUID,
    session_id: str,
    lead_data: dict,
    transcript: list[dict] | None = None,
    source: str | None = None,
) -> Lead:
    computed_score = score_lead(lead_data)
    lead = Lead(
        business_id=business_id,
        session_id=session_id,
        name=lead_data.get("name"),
        contact=lead_data.get("contact"),
        cleaning_type=lead_data.get("cleaning_type"),
        property_size=lead_data.get("property_size"),
        preferred_date=lead_data.get("preferred_date"),
        special_requests=lead_data.get("special_requests"),
        estimated_price_range=lead_data.get("estimated_price_range"),
        summary=lead_data.get("summary"),
        address=lead_data.get("address"),
        zip_code=lead_data.get("zip_code"),
        raw_json=lead_data,
        status="new",
        conversation_transcript=transcript,
        source=source or "widget",
        score=computed_score,
    )
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    return lead


async def get_leads(
    db: AsyncSession,
    business_id: uuid.UUID,
    status: str | None = None,
    follow_up: bool = False,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[Lead], int]:
    query = select(Lead).where(Lead.business_id == business_id)
    count_query = select(func.count(Lead.id)).where(Lead.business_id == business_id)

    if status:
        query = query.where(Lead.status == status)
        count_query = count_query.where(Lead.status == status)

    if follow_up:
        now = datetime.now(timezone.utc)
        query = query.where(
            Lead.follow_up_at <= now,
            Lead.status.notin_(["converted", "lost"]),
        )
        count_query = count_query.where(
            Lead.follow_up_at <= now,
            Lead.status.notin_(["converted", "lost"]),
        )

    query = query.order_by(Lead.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(query)
    leads = list(result.scalars().all())

    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    return leads, total


async def get_lead_by_id(db: AsyncSession, lead_id: uuid.UUID, business_id: uuid.UUID) -> Lead | None:
    result = await db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.business_id == business_id)
    )
    return result.scalar_one_or_none()


async def update_lead_status(db: AsyncSession, lead_id: uuid.UUID, business_id: uuid.UUID, status: str) -> Lead | None:
    lead = await get_lead_by_id(db, lead_id, business_id)
    if lead is None:
        return None
    lead.status = status
    lead.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(lead)
    return lead


async def get_lead_stats(db: AsyncSession, business_id: uuid.UUID, days: int = 30) -> dict:
    """Get lead statistics for the dashboard."""
    cutoff = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = cutoff - timedelta(days=days)

    total_result = await db.execute(
        select(func.count(Lead.id)).where(
            Lead.business_id == business_id,
            Lead.created_at >= cutoff,
        )
    )
    total = total_result.scalar() or 0

    converted_result = await db.execute(
        select(func.count(Lead.id)).where(
            Lead.business_id == business_id,
            Lead.created_at >= cutoff,
            Lead.status == "converted",
        )
    )
    converted = converted_result.scalar() or 0

    # Leads per day
    daily_result = await db.execute(
        select(
            func.date_trunc("day", Lead.created_at).label("day"),
            func.count(Lead.id).label("count"),
        )
        .where(Lead.business_id == business_id, Lead.created_at >= cutoff)
        .group_by("day")
        .order_by("day")
    )
    daily = [{"date": str(row.day.date()), "count": row.count} for row in daily_result.all()]

    # Total revenue (sum of actual_value where converted)
    revenue_result = await db.execute(
        select(func.sum(Lead.actual_value)).where(
            Lead.business_id == business_id,
            Lead.status == "converted",
            Lead.actual_value.isnot(None),
        )
    )
    total_revenue = revenue_result.scalar() or Decimal("0")

    # Average value of converted leads
    avg_result = await db.execute(
        select(func.avg(Lead.actual_value)).where(
            Lead.business_id == business_id,
            Lead.status == "converted",
            Lead.actual_value.isnot(None),
        )
    )
    avg_value = avg_result.scalar()
    avg_value = round(float(avg_value), 2) if avg_value else 0

    # Per-service-type breakdown
    service_result = await db.execute(
        select(
            Lead.cleaning_type,
            func.count(Lead.id).label("count"),
            func.count(Lead.id).filter(Lead.status == "converted").label("converted_count"),
        )
        .where(Lead.business_id == business_id, Lead.created_at >= cutoff)
        .group_by(Lead.cleaning_type)
    )
    by_service = [
        {
            "service": row.cleaning_type or "Unknown",
            "count": row.count,
            "converted": row.converted_count,
        }
        for row in service_result.all()
    ]

    # Funnel counts (per status)
    funnel_result = await db.execute(
        select(
            Lead.status,
            func.count(Lead.id).label("count"),
        )
        .where(Lead.business_id == business_id, Lead.created_at >= cutoff)
        .group_by(Lead.status)
    )
    funnel = {row.status: row.count for row in funnel_result.all()}

    # Source breakdown
    source_result = await db.execute(
        select(
            Lead.source,
            func.count(Lead.id).label("count"),
        )
        .where(Lead.business_id == business_id, Lead.created_at >= cutoff)
        .group_by(Lead.source)
    )
    by_source = {(row.source or "unknown"): row.count for row in source_result.all()}

    return {
        "total_leads": total,
        "converted": converted,
        "conversion_rate": round(converted / total * 100, 1) if total > 0 else 0,
        "daily": daily,
        "total_revenue": float(total_revenue),
        "avg_value": avg_value,
        "by_service": by_service,
        "funnel": funnel,
        "by_source": by_source,
    }
