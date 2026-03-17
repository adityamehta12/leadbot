from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import JWT_SECRET
from db import get_session
from models.business import Business
from models.user import BusinessUser
from schemas.auth import LoginRequest, LoginResponse
from services.auth_service import authenticate, create_token, hash_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
async def login(req: LoginRequest, response: Response, db: AsyncSession = Depends(get_session)):
    user = await authenticate(db, req.email, req.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_token(str(user.id), str(user.business_id))

    response.set_cookie(
        key="token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400,  # 24 hours
    )

    return LoginResponse(
        token=token,
        user_name=user.name,
        business_name="",  # filled by frontend from session
    )


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("token")
    return {"status": "ok"}


class SetupRequest(BaseModel):
    admin_secret: str
    email: EmailStr
    password: str
    name: str


@router.post("/setup")
async def setup_first_user(req: SetupRequest, db: AsyncSession = Depends(get_session)):
    """One-time bootstrap: create the first owner user. Requires JWT_SECRET as admin_secret."""
    if req.admin_secret != JWT_SECRET:
        raise HTTPException(status_code=403, detail="Invalid admin secret")

    # Check if any users exist already
    existing = await db.execute(select(BusinessUser).limit(1))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Setup already completed — users exist")

    # Find default business
    result = await db.execute(select(Business).where(Business.slug == "default"))
    business = result.scalar_one_or_none()
    if business is None:
        raise HTTPException(status_code=500, detail="No default business — migrations may not have run")

    user = BusinessUser(
        business_id=business.id,
        email=req.email,
        password_hash=hash_password(req.password),
        name=req.name,
        is_owner=True,
    )
    db.add(user)
    await db.commit()
    return {"status": "ok", "message": f"Owner '{req.name}' created for '{business.name}'"}
