"""Seed script: create a dashboard user for the default business.

Usage:
    python seed_user.py --email you@example.com --password yourpassword --name "Your Name"

Requires DATABASE_URL in env or .env file.
"""

import argparse
import asyncio
import sys

from config import DATABASE_URL

if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set. Add it to .env or export it.")
    sys.exit(1)

from db import get_session_ctx
from models.business import Business
from models.user import BusinessUser
from services.auth_service import hash_password
from sqlalchemy import select


async def seed(email: str, password: str, name: str):
    async with get_session_ctx() as db:
        # Find default business
        result = await db.execute(select(Business).where(Business.slug == "default"))
        business = result.scalar_one_or_none()

        if business is None:
            print("No 'default' business found. Run migrations first (alembic upgrade head).")
            sys.exit(1)

        # Check if user already exists
        existing = await db.execute(select(BusinessUser).where(BusinessUser.email == email))
        if existing.scalar_one_or_none():
            print(f"User {email} already exists.")
            return

        user = BusinessUser(
            business_id=business.id,
            email=email,
            password_hash=hash_password(password),
            name=name,
            is_owner=True,
        )
        db.add(user)
        await db.commit()
        print(f"Created owner '{name}' ({email}) for business '{business.name}'")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed a dashboard user")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    asyncio.run(seed(args.email, args.password, args.name))
