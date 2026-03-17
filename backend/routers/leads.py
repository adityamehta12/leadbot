import csv
import io
import uuid

from fastapi import APIRouter, Cookie, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session
from schemas.lead import LeadListResponse, LeadResponse, LeadStatusUpdate
from services.auth_service import decode_token
from services.lead_service import get_lead_by_id, get_lead_stats, get_leads, update_lead_status

router = APIRouter(prefix="/api/leads", tags=["leads"])


def _get_business_id(token: str | None = Cookie(None)) -> uuid.UUID:
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    return uuid.UUID(payload["biz"])


@router.get("")
async def list_leads(
    status: str | None = None,
    offset: int = 0,
    limit: int = 50,
    business_id: uuid.UUID = Depends(_get_business_id),
    db: AsyncSession = Depends(get_session),
) -> LeadListResponse:
    leads, total = await get_leads(db, business_id, status=status, offset=offset, limit=limit)
    return LeadListResponse(
        leads=[LeadResponse.model_validate(l) for l in leads],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/stats")
async def lead_stats(
    days: int = 30,
    business_id: uuid.UUID = Depends(_get_business_id),
    db: AsyncSession = Depends(get_session),
):
    return await get_lead_stats(db, business_id, days=days)


@router.get("/export/csv")
async def export_csv(
    business_id: uuid.UUID = Depends(_get_business_id),
    db: AsyncSession = Depends(get_session),
):
    leads, _ = await get_leads(db, business_id, limit=10000)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name", "Contact", "Type", "Size", "Date", "Price Range", "Status", "Created"])
    for lead in leads:
        writer.writerow([
            lead.name, lead.contact, lead.cleaning_type, lead.property_size,
            lead.preferred_date, lead.estimated_price_range, lead.status,
            lead.created_at.isoformat() if lead.created_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


@router.get("/{lead_id}")
async def get_lead(
    lead_id: uuid.UUID,
    business_id: uuid.UUID = Depends(_get_business_id),
    db: AsyncSession = Depends(get_session),
):
    lead = await get_lead_by_id(db, lead_id, business_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {
        "lead": LeadResponse.model_validate(lead),
        "transcript": lead.conversation_transcript or [],
    }


@router.patch("/{lead_id}/status")
async def patch_lead_status(
    lead_id: uuid.UUID,
    body: LeadStatusUpdate,
    business_id: uuid.UUID = Depends(_get_business_id),
    db: AsyncSession = Depends(get_session),
):
    valid = {"new", "contacted", "qualified", "converted", "lost"}
    if body.status not in valid:
        raise HTTPException(status_code=400, detail=f"Status must be one of: {valid}")
    lead = await update_lead_status(db, lead_id, business_id, body.status)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return LeadResponse.model_validate(lead)
