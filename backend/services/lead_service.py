"""Lead persistence — saves captured leads to the database."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.lead import Lead


async def save_lead(
    db: AsyncSession,
    business_id: uuid.UUID,
    session_id: str,
    lead_data: dict,
    transcript: list[dict] | None = None,
) -> Lead:
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
        raw_json=lead_data,
        status="new",
        conversation_transcript=transcript,
    )
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    return lead


async def get_leads(
    db: AsyncSession,
    business_id: uuid.UUID,
    status: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[Lead], int]:
    query = select(Lead).where(Lead.business_id == business_id)
    count_query = select(func.count(Lead.id)).where(Lead.business_id == business_id)

    if status:
        query = query.where(Lead.status == status)
        count_query = count_query.where(Lead.status == status)

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
    from datetime import timedelta
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

    return {
        "total_leads": total,
        "converted": converted,
        "conversion_rate": round(converted / total * 100, 1) if total > 0 else 0,
        "daily": daily,
    }
