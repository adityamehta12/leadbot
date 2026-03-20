"""Email (SendGrid) + SMS (Twilio) notifications on lead capture."""

import asyncio

import httpx

from config import SENDGRID_API_KEY, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER


async def _send_email(to_email: str, subject: str, body: str):
    if not SENDGRID_API_KEY:
        return
    async with httpx.AsyncClient() as client:
        await client.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {SENDGRID_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "personalizations": [{"to": [{"email": to_email}]}],
                "from": {"email": "noreply@leadbot.app", "name": "LeadBot"},
                "subject": subject,
                "content": [{"type": "text/plain", "value": body}],
            },
        )


async def _send_sms(to_number: str, body: str):
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER]):
        return
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json",
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            data={
                "From": TWILIO_FROM_NUMBER,
                "To": to_number,
                "Body": body,
            },
        )


async def notify_new_lead(notification_config: dict | None, lead_data: dict, business_name: str):
    """Send email and/or SMS notification for a new lead."""
    if not notification_config:
        return

    name = lead_data.get("name", "Unknown")
    cleaning_type = lead_data.get("cleaning_type", "N/A")
    summary = lead_data.get("summary", "")

    subject = f"New Lead: {name} — {cleaning_type}"
    body = (
        f"New lead captured for {business_name}!\n\n"
        f"Name: {name}\n"
        f"Contact: {lead_data.get('contact', 'N/A')}\n"
        f"Type: {cleaning_type}\n"
        f"Size: {lead_data.get('property_size', 'N/A')}\n"
        f"Date: {lead_data.get('preferred_date', 'N/A')}\n"
        f"Estimate: {lead_data.get('estimated_price_range', 'N/A')}\n"
        f"Summary: {summary}\n"
    )

    tasks = []
    if notification_config.get("email"):
        tasks.append(_send_email(notification_config["email"], subject, body))
    if notification_config.get("sms"):
        tasks.append(_send_sms(notification_config["sms"], body[:160]))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def send_transcript_email(to_email: str, transcript: list[dict], business_name: str):
    """Email a conversation transcript to the lead."""
    if not SENDGRID_API_KEY:
        return

    lines = []
    for msg in transcript:
        role = "You" if msg["role"] == "user" else business_name
        lines.append(f"{role}: {msg['content']}")

    body = f"Here's a copy of your conversation with {business_name}:\n\n" + "\n\n".join(lines)

    await _send_email(to_email, f"Your conversation with {business_name}", body)


async def send_message_to_lead(channel: str, to_address: str, content: str, business_name: str):
    """Send an email or SMS message directly to a lead."""
    if channel == "email":
        await _send_email(to_address, f"Message from {business_name}", content)
    elif channel == "sms":
        await _send_sms(to_address, content[:160])
    else:
        raise ValueError(f"Unsupported channel: {channel}")
