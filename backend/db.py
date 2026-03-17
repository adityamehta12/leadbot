from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import DATABASE_URL

engine = None
async_session_factory = None


def _init_engine():
    global engine, async_session_factory
    if not DATABASE_URL:
        return
    engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True, pool_size=5, max_overflow=10)
    async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


_init_engine()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    if async_session_factory is None:
        raise RuntimeError("Database not configured — set DATABASE_URL")
    async with async_session_factory() as session:
        yield session


@asynccontextmanager
async def get_session_ctx() -> AsyncGenerator[AsyncSession, None]:
    """Context manager version of get_session for use outside of FastAPI dependencies."""
    if async_session_factory is None:
        raise RuntimeError("Database not configured — set DATABASE_URL")
    async with async_session_factory() as session:
        yield session


async def dispose_engine():
    global engine
    if engine:
        await engine.dispose()
