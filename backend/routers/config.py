from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session
from schemas.business import ConfigResponse
from services.business_service import get_business_config

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/{tenant_id}")
async def get_tenant_config(tenant_id: str, db: AsyncSession = Depends(get_session)) -> ConfigResponse:
    config = await get_business_config(db, tenant_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return ConfigResponse(
        business_name=config["name"],
        color=config["color"],
        greeting=config["greeting"] or "",
        has_calendar=bool(config.get("google_calendar_id")),
    )
