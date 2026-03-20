from pydantic import BaseModel


class ConfigResponse(BaseModel):
    business_name: str
    color: str
    greeting: str
    has_calendar: bool = False
    timezone: str = "America/New_York"
    business_hours: dict | None = None
    after_hours_message: str | None = None
    faq_entries: list | None = None
    language: str = "en"


class BusinessSettingsUpdate(BaseModel):
    name: str | None = None
    color: str | None = None
    greeting: str | None = None
    webhook_url: str | None = None
    notification_email: str | None = None
    notification_sms: str | None = None
