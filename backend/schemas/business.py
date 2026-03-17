from pydantic import BaseModel


class ConfigResponse(BaseModel):
    business_name: str
    color: str
    greeting: str
    has_calendar: bool = False


class BusinessSettingsUpdate(BaseModel):
    name: str | None = None
    color: str | None = None
    greeting: str | None = None
    webhook_url: str | None = None
    notification_email: str | None = None
    notification_sms: str | None = None
