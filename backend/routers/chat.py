"""Chat router — multi-tenant version of the original chat endpoint."""

import json
import re
import uuid

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from config import ANTHROPIC_API_KEY, ABUSE_LIMIT, SYSTEM_PROMPT
from db import get_session
from schemas.chat import ChatRequest, ResetRequest, TTSRequest
from services import session_service
from services.business_service import get_business_config
from services.lead_service import save_lead
from services.notification_service import notify_new_lead
from services.webhook_service import dispatch_webhook

router = APIRouter(prefix="/api", tags=["chat"])

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── Input pre-screening ──────────────────────────────────────
_PROFANITY_PATTERNS = re.compile(
    r"\b("
    r"f+u+c+k+|s+h+i+t+|a+s+s+h+o+l+e|b+i+t+c+h|c+u+n+t|d+i+c+k|"
    r"n+i+g+g+|f+a+g+|r+e+t+a+r+d|w+h+o+r+e|s+l+u+t"
    r")\b",
    re.IGNORECASE,
)

_INJECTION_PATTERNS = re.compile(
    r"("
    r"ignore\s+(your|all|previous|above)\s+(instructions|rules|prompt)|"
    r"you\s+are\s+now|"
    r"pretend\s+(to\s+be|you\s+are)|"
    r"act\s+as\s+(if|a|an)|"
    r"(reveal|show|repeat|print)\s+(your|the)\s+(system\s+)?(prompt|instructions|rules)|"
    r"jailbreak|"
    r"DAN\s+mode|"
    r"do\s+anything\s+now|"
    r"override\s+(your|safety|content)"
    r")",
    re.IGNORECASE,
)


async def screen_message(message: str, session_id: str, business_name: str) -> str | None:
    text = message.strip()
    if not text:
        return None

    strikes = await session_service.get_abuse_strikes(session_id)
    if strikes >= ABUSE_LIMIT:
        return "This conversation has ended. Please visit our website or call us directly for assistance."

    if _PROFANITY_PATTERNS.search(text):
        new_strikes = await session_service.increment_abuse_strikes(session_id)
        if new_strikes >= ABUSE_LIMIT:
            return "I'm not able to continue this conversation. If you'd like help with cleaning services in the future, feel free to come back. Have a good day!"
        return "I want to make sure I can help you. Could we keep things professional? I'm happy to assist with any cleaning needs."

    if _INJECTION_PATTERNS.search(text):
        return f"I'm Sarah, the virtual assistant for {business_name}. How can I help you with our cleaning services?"

    return None


def _resolve_system_prompt(biz_config: dict | None) -> str:
    """Use business-specific system prompt if set, otherwise the default."""
    if biz_config and biz_config.get("system_prompt"):
        return biz_config["system_prompt"]
    if biz_config:
        # Inject business name into default prompt
        return SYSTEM_PROMPT.replace("Sparkle Cleaning Co.", biz_config["name"])
    return SYSTEM_PROMPT


@router.post("/chat")
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_session)):
    session_id = req.session_id or str(uuid.uuid4())
    tenant_id = req.tenant_id or "default"

    # Resolve business
    biz_config = await get_business_config(db, tenant_id)
    if biz_config is None:
        raise HTTPException(status_code=404, detail="Business not found")

    business_name = biz_config["name"]
    business_id = biz_config["id"]
    system_prompt = _resolve_system_prompt(biz_config)

    # Load session
    messages = await session_service.get_session(session_id)

    # Pre-screen
    blocked = await screen_message(req.message, session_id, business_name)
    if blocked:
        await session_service.append_message(session_id, "user", req.message)
        await session_service.append_message(session_id, "assistant", blocked)

        async def blocked_response():
            yield f"data: {json.dumps({'type': 'text', 'content': blocked, 'session_id': session_id})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"

        return StreamingResponse(blocked_response(), media_type="text/event-stream")

    messages.append({"role": "user", "content": req.message})
    await session_service.save_session(session_id, messages)

    async def generate():
        full_response = ""
        with client.messages.stream(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            system=system_prompt,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                full_response += text
                if "<lead_data>" not in full_response:
                    yield f"data: {json.dumps({'type': 'text', 'content': text, 'session_id': session_id})}\n\n"

        # Extract lead data
        lead_match = re.search(r"<lead_data>\s*(\{.*?\})\s*</lead_data>", full_response, re.DOTALL)
        clean_response = re.sub(r"\s*<lead_data>.*?</lead_data>", "", full_response, flags=re.DOTALL).strip()

        if "<lead_data>" in full_response:
            yield f"data: {json.dumps({'type': 'text', 'content': clean_response, 'session_id': session_id})}\n\n"

        # Save assistant message
        await session_service.append_message(session_id, "assistant", clean_response)

        if lead_match:
            try:
                lead_data = json.loads(lead_match.group(1))
                lead_data["session_id"] = session_id
                lead_data["business"] = business_name

                # Get full transcript for storage
                transcript = await session_service.get_session(session_id)

                # Save to database
                lead = await save_lead(
                    db,
                    business_id=uuid.UUID(business_id),
                    session_id=session_id,
                    lead_data=lead_data,
                    transcript=transcript,
                )

                print(f"\n{'='*60}")
                print(f"NEW LEAD CAPTURED — {business_name} — {lead.id}")
                print(json.dumps(lead_data, indent=2))
                print(f"{'='*60}\n")

                # Webhook
                webhook_url = biz_config.get("webhook_url")
                if webhook_url:
                    await dispatch_webhook(db, lead.id, uuid.UUID(business_id), webhook_url, lead_data)

                # Notifications
                await notify_new_lead(biz_config.get("notification_config"), lead_data, business_name)

                yield f"data: {json.dumps({'type': 'lead_captured', 'lead': lead_data, 'session_id': session_id})}\n\n"
            except json.JSONDecodeError:
                pass

        yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/tts")
async def text_to_speech(req: TTSRequest):
    import io

    import edge_tts

    communicate = edge_tts.Communicate(req.text, req.voice, rate="+5%")
    audio_buffer = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_buffer.write(chunk["data"])

    audio_buffer.seek(0)
    return StreamingResponse(audio_buffer, media_type="audio/mpeg")


@router.post("/reset")
async def reset_session(req: ResetRequest):
    await session_service.delete_session(req.session_id)
    return {"status": "ok"}
