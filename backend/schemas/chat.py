from pydantic import BaseModel


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    tenant_id: str | None = None
    source: str | None = None


class TTSRequest(BaseModel):
    text: str
    voice: str = "en-US-JennyNeural"


class ResetRequest(BaseModel):
    session_id: str
    tenant_id: str | None = None
