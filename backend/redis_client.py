import redis.asyncio as aioredis

from config import REDIS_URL

pool: aioredis.Redis | None = None


def init_redis():
    global pool
    if not REDIS_URL:
        return
    pool = aioredis.from_url(REDIS_URL, decode_responses=True)


init_redis()


async def get_redis() -> aioredis.Redis | None:
    return pool


async def close_redis():
    global pool
    if pool:
        await pool.aclose()
        pool = None
