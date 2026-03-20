"""Business CRUD with Redis caching."""

import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.business import Business
from redis_client import get_redis

CACHE_TTL = 300  # 5 minutes


async def _cache_business(business: Business):
    r = await get_redis()
    if r is None:
        return
    data = {
        "id": str(business.id),
        "slug": business.slug,
        "name": business.name,
        "color": business.color,
        "greeting": business.greeting,
        "system_prompt": business.system_prompt,
        "webhook_url": business.webhook_url,
        "google_calendar_id": business.google_calendar_id,
        "notification_config": business.notification_config,
        "timezone": business.timezone,
        "business_hours": business.business_hours,
        "service_config": business.service_config,
        "service_areas": business.service_areas,
        "after_hours_message": business.after_hours_message,
        "faq_entries": business.faq_entries,
        "plan": business.plan,
        "widget_language": business.widget_language,
    }
    await r.set(f"biz:{business.slug}", json.dumps(data), ex=CACHE_TTL)


async def _get_cached_business(slug: str) -> dict | None:
    r = await get_redis()
    if r is None:
        return None
    raw = await r.get(f"biz:{slug}")
    if raw is None:
        return None
    return json.loads(raw)


async def invalidate_cache(slug: str):
    r = await get_redis()
    if r:
        await r.delete(f"biz:{slug}")


async def get_business_by_slug(db: AsyncSession, slug: str) -> Business | None:
    result = await db.execute(select(Business).where(Business.slug == slug))
    return result.scalar_one_or_none()


async def get_business_config(db: AsyncSession, slug: str) -> dict | None:
    """Get business config, with Redis cache."""
    cached = await _get_cached_business(slug)
    if cached:
        return cached

    biz = await get_business_by_slug(db, slug)
    if biz is None:
        return None

    await _cache_business(biz)
    return {
        "id": str(biz.id),
        "slug": biz.slug,
        "name": biz.name,
        "color": biz.color,
        "greeting": biz.greeting,
        "system_prompt": biz.system_prompt,
        "webhook_url": biz.webhook_url,
        "google_calendar_id": biz.google_calendar_id,
        "notification_config": biz.notification_config,
        "timezone": biz.timezone,
        "business_hours": biz.business_hours,
        "service_config": biz.service_config,
        "service_areas": biz.service_areas,
        "after_hours_message": biz.after_hours_message,
        "faq_entries": biz.faq_entries,
        "plan": biz.plan,
        "widget_language": biz.widget_language,
    }


async def get_business_by_id(db: AsyncSession, business_id: uuid.UUID) -> Business | None:
    result = await db.execute(select(Business).where(Business.id == business_id))
    return result.scalar_one_or_none()


async def update_business(db: AsyncSession, business: Business, **kwargs) -> Business:
    for key, value in kwargs.items():
        if hasattr(business, key):
            setattr(business, key, value)
    await db.commit()
    await db.refresh(business)
    await invalidate_cache(business.slug)
    return business
