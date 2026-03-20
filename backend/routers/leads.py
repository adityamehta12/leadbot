import csv
import io
import uuid
from datetime import datetime, timezone
from html import escape

from fastapi import APIRouter, Cookie, Depends, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session
from models.lead_activity import LeadActivity
from models.lead_message import LeadMessage
from schemas.lead import (
    LeadBulkStatusRequest,
    LeadFollowUpRequest,
    LeadListResponse,
    LeadMessageRequest,
    LeadNoteRequest,
    LeadResponse,
    LeadStatusUpdate,
    LeadValueRequest,
)
from services.auth_service import decode_token
from services.lead_service import get_lead_by_id, get_lead_stats, get_leads, update_lead_status
from services.notification_service import send_message_to_lead

router = APIRouter(prefix="/api/leads", tags=["leads"])


def _get_business_id(token: str | None = Cookie(None)) -> uuid.UUID:
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    return uuid.UUID(payload["biz"])


def _get_user_id(token: str | None = Cookie(None)) -> uuid.UUID:
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    return uuid.UUID(payload["sub"])


@router.get("")
async def list_leads(
    status: str | None = None,
    follow_up: bool = False,
    offset: int = 0,
    limit: int = 50,
    business_id: uuid.UUID = Depends(_get_business_id),
    db: AsyncSession = Depends(get_session),
) -> LeadListResponse:
    leads, total = await get_leads(db, business_id, status=status, follow_up=follow_up, offset=offset, limit=limit)
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
    writer.writerow(["Name", "Contact", "Type", "Size", "Address", "Zip", "Date", "Price Range", "Status", "Score", "Source", "Value", "Created"])
    for lead in leads:
        writer.writerow([
            lead.name, lead.contact, lead.cleaning_type, lead.property_size,
            lead.address, lead.zip_code,
            lead.preferred_date, lead.estimated_price_range, lead.status,
            lead.score, lead.source, lead.actual_value,
            lead.created_at.isoformat() if lead.created_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


@router.patch("/bulk-status")
async def bulk_update_status(
    body: LeadBulkStatusRequest,
    business_id: uuid.UUID = Depends(_get_business_id),
    user_id: uuid.UUID = Depends(_get_user_id),
    db: AsyncSession = Depends(get_session),
):
    valid = {"new", "contacted", "qualified", "converted", "lost"}
    if body.status not in valid:
        raise HTTPException(status_code=400, detail=f"Status must be one of: {valid}")

    updated = 0
    for lead_id in body.lead_ids:
        lead = await update_lead_status(db, lead_id, business_id, body.status)
        if lead is not None:
            updated += 1
            db.add(LeadActivity(
                lead_id=lead_id,
                business_id=business_id,
                action="status_change",
                detail={"new_status": body.status, "bulk": True},
                actor_id=user_id,
            ))
    await db.commit()
    return {"updated": updated}


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
        "notes": lead.notes or [],
    }


@router.patch("/{lead_id}/status")
async def patch_lead_status(
    lead_id: uuid.UUID,
    body: LeadStatusUpdate,
    business_id: uuid.UUID = Depends(_get_business_id),
    user_id: uuid.UUID = Depends(_get_user_id),
    db: AsyncSession = Depends(get_session),
):
    valid = {"new", "contacted", "qualified", "converted", "lost"}
    if body.status not in valid:
        raise HTTPException(status_code=400, detail=f"Status must be one of: {valid}")
    lead = await update_lead_status(db, lead_id, business_id, body.status)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    db.add(LeadActivity(
        lead_id=lead_id,
        business_id=business_id,
        action="status_change",
        detail={"new_status": body.status},
        actor_id=user_id,
    ))
    await db.commit()
    return LeadResponse.model_validate(lead)


@router.post("/{lead_id}/notes")
async def add_note(
    lead_id: uuid.UUID,
    body: LeadNoteRequest,
    business_id: uuid.UUID = Depends(_get_business_id),
    user_id: uuid.UUID = Depends(_get_user_id),
    db: AsyncSession = Depends(get_session),
):
    lead = await get_lead_by_id(db, lead_id, business_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    note_entry = {
        "text": body.text,
        "by": str(user_id),
        "at": datetime.now(timezone.utc).isoformat(),
    }
    existing_notes = list(lead.notes or [])
    existing_notes.append(note_entry)
    lead.notes = existing_notes
    lead.updated_at = datetime.now(timezone.utc)

    db.add(LeadActivity(
        lead_id=lead_id,
        business_id=business_id,
        action="note_added",
        detail={"text": body.text},
        actor_id=user_id,
    ))
    await db.commit()
    await db.refresh(lead)
    return {"notes": lead.notes}


@router.patch("/{lead_id}/follow-up")
async def set_follow_up(
    lead_id: uuid.UUID,
    body: LeadFollowUpRequest,
    business_id: uuid.UUID = Depends(_get_business_id),
    user_id: uuid.UUID = Depends(_get_user_id),
    db: AsyncSession = Depends(get_session),
):
    lead = await get_lead_by_id(db, lead_id, business_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    lead.follow_up_at = body.follow_up_at
    lead.updated_at = datetime.now(timezone.utc)

    db.add(LeadActivity(
        lead_id=lead_id,
        business_id=business_id,
        action="follow_up_set",
        detail={"follow_up_at": body.follow_up_at.isoformat() if body.follow_up_at else None},
        actor_id=user_id,
    ))
    await db.commit()
    await db.refresh(lead)
    return LeadResponse.model_validate(lead)


@router.patch("/{lead_id}/value")
async def set_value(
    lead_id: uuid.UUID,
    body: LeadValueRequest,
    business_id: uuid.UUID = Depends(_get_business_id),
    user_id: uuid.UUID = Depends(_get_user_id),
    db: AsyncSession = Depends(get_session),
):
    lead = await get_lead_by_id(db, lead_id, business_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    lead.actual_value = body.actual_value
    lead.updated_at = datetime.now(timezone.utc)

    db.add(LeadActivity(
        lead_id=lead_id,
        business_id=business_id,
        action="value_set",
        detail={"actual_value": str(body.actual_value)},
        actor_id=user_id,
    ))
    await db.commit()
    await db.refresh(lead)
    return LeadResponse.model_validate(lead)


@router.post("/{lead_id}/message")
async def send_message(
    lead_id: uuid.UUID,
    body: LeadMessageRequest,
    business_id: uuid.UUID = Depends(_get_business_id),
    user_id: uuid.UUID = Depends(_get_user_id),
    db: AsyncSession = Depends(get_session),
):
    if body.channel not in ("email", "sms"):
        raise HTTPException(status_code=400, detail="Channel must be 'email' or 'sms'")

    lead = await get_lead_by_id(db, lead_id, business_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    contact = lead.contact
    if not contact:
        raise HTTPException(status_code=400, detail="Lead has no contact info")

    # Fetch business name for the message
    from models.business import Business
    biz_result = await db.execute(select(Business).where(Business.id == business_id))
    business = biz_result.scalar_one_or_none()
    business_name = business.name if business else "Our Team"

    await send_message_to_lead(body.channel, contact, body.content, business_name)

    msg = LeadMessage(
        lead_id=lead_id,
        business_id=business_id,
        direction="outbound",
        channel=body.channel,
        content=body.content,
        sent_by=user_id,
    )
    db.add(msg)

    db.add(LeadActivity(
        lead_id=lead_id,
        business_id=business_id,
        action="message_sent",
        detail={"channel": body.channel, "preview": body.content[:100]},
        actor_id=user_id,
    ))
    await db.commit()
    return {"status": "sent", "message_id": str(msg.id)}


@router.get("/{lead_id}/quote")
async def get_quote(
    lead_id: uuid.UUID,
    business_id: uuid.UUID = Depends(_get_business_id),
    db: AsyncSession = Depends(get_session),
):
    lead = await get_lead_by_id(db, lead_id, business_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    from models.business import Business
    biz_result = await db.execute(select(Business).where(Business.id == business_id))
    business = biz_result.scalar_one_or_none()
    business_name = escape(business.name) if business else "Our Team"

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Quote for {escape(lead.name or 'Customer')}</title>
<style>
  body {{ font-family: Arial, sans-serif; max-width: 700px; margin: 40px auto; padding: 20px; }}
  h1 {{ color: #2563eb; }}
  table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
  th, td {{ text-align: left; padding: 8px 12px; border-bottom: 1px solid #e5e7eb; }}
  th {{ background: #f9fafb; }}
  .footer {{ margin-top: 30px; font-size: 0.9em; color: #6b7280; }}
</style>
</head>
<body>
  <h1>{business_name} — Quote</h1>
  <p>Prepared for: <strong>{escape(lead.name or 'N/A')}</strong></p>
  <table>
    <tr><th>Service Type</th><td>{escape(lead.cleaning_type or 'N/A')}</td></tr>
    <tr><th>Property Size</th><td>{escape(lead.property_size or 'N/A')}</td></tr>
    <tr><th>Address</th><td>{escape(lead.address or 'N/A')}</td></tr>
    <tr><th>Preferred Date</th><td>{escape(lead.preferred_date or 'N/A')}</td></tr>
    <tr><th>Estimated Price</th><td>{escape(lead.estimated_price_range or 'N/A')}</td></tr>
    <tr><th>Special Requests</th><td>{escape(lead.special_requests or 'None')}</td></tr>
  </table>
  <p>{escape(lead.summary or '')}</p>
  <div class="footer">
    <p>Contact: {escape(lead.contact or 'N/A')}</p>
    <p>Generated by {business_name}</p>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html)


@router.get("/{lead_id}/activity")
async def get_activity(
    lead_id: uuid.UUID,
    business_id: uuid.UUID = Depends(_get_business_id),
    db: AsyncSession = Depends(get_session),
):
    lead = await get_lead_by_id(db, lead_id, business_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    result = await db.execute(
        select(LeadActivity)
        .where(LeadActivity.lead_id == lead_id, LeadActivity.business_id == business_id)
        .order_by(LeadActivity.created_at.desc())
    )
    activities = result.scalars().all()
    return [
        {
            "id": str(a.id),
            "action": a.action,
            "detail": a.detail,
            "actor_id": str(a.actor_id) if a.actor_id else None,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in activities
    ]


@router.get("/{lead_id}/messages")
async def get_messages(
    lead_id: uuid.UUID,
    business_id: uuid.UUID = Depends(_get_business_id),
    db: AsyncSession = Depends(get_session),
):
    lead = await get_lead_by_id(db, lead_id, business_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    result = await db.execute(
        select(LeadMessage)
        .where(LeadMessage.lead_id == lead_id, LeadMessage.business_id == business_id)
        .order_by(LeadMessage.created_at.desc())
    )
    messages = result.scalars().all()
    return [
        {
            "id": str(m.id),
            "direction": m.direction,
            "channel": m.channel,
            "content": m.content,
            "sent_by": str(m.sent_by) if m.sent_by else None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages
    ]
