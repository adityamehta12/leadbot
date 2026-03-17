from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session
from schemas.auth import LoginRequest, LoginResponse
from services.auth_service import authenticate, create_token

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
