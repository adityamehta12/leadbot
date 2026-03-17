"""Authentication: bcrypt hashing + JWT tokens."""

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import JWT_ALGORITHM, JWT_EXPIRY_HOURS, JWT_SECRET
from models.user import BusinessUser


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user_id: str, business_id: str) -> str:
    payload = {
        "sub": user_id,
        "biz": business_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None


async def authenticate(db: AsyncSession, email: str, password: str) -> BusinessUser | None:
    result = await db.execute(select(BusinessUser).where(BusinessUser.email == email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user


async def get_user_by_id(db: AsyncSession, user_id: str) -> BusinessUser | None:
    result = await db.execute(select(BusinessUser).where(BusinessUser.id == uuid.UUID(user_id)))
    return result.scalar_one_or_none()
