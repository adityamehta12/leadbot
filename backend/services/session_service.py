"""Session management with Redis (falls back to in-memory if REDIS_URL is empty)."""

import json

from redis_client import get_redis

SESSION_TTL = 1800  # 30 minutes

# In-memory fallback for local dev
_mem_sessions: dict[str, list[dict]] = {}
_mem_abuse: dict[str, int] = {}


async def get_session(session_id: str) -> list[dict]:
    r = await get_redis()
    if r is None:
        return _mem_sessions.get(session_id, [])
    raw = await r.get(f"session:{session_id}")
    if raw is None:
        return []
    return json.loads(raw)


async def save_session(session_id: str, messages: list[dict]):
    r = await get_redis()
    if r is None:
        _mem_sessions[session_id] = messages
        return
    await r.set(f"session:{session_id}", json.dumps(messages), ex=SESSION_TTL)


async def append_message(session_id: str, role: str, content: str):
    messages = await get_session(session_id)
    messages.append({"role": role, "content": content})
    await save_session(session_id, messages)


async def delete_session(session_id: str):
    r = await get_redis()
    if r is None:
        _mem_sessions.pop(session_id, None)
        _mem_abuse.pop(session_id, None)
        return
    await r.delete(f"session:{session_id}", f"abuse:{session_id}")


async def get_abuse_strikes(session_id: str) -> int:
    r = await get_redis()
    if r is None:
        return _mem_abuse.get(session_id, 0)
    val = await r.get(f"abuse:{session_id}")
    return int(val) if val else 0


async def increment_abuse_strikes(session_id: str) -> int:
    r = await get_redis()
    if r is None:
        _mem_abuse[session_id] = _mem_abuse.get(session_id, 0) + 1
        return _mem_abuse[session_id]
    pipe = r.pipeline()
    pipe.incr(f"abuse:{session_id}")
    pipe.expire(f"abuse:{session_id}", SESSION_TTL)
    results = await pipe.execute()
    return results[0]
