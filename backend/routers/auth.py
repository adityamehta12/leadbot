import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
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


# ── Registration ──────────────────────────────────────────────


@router.get("/register", response_class=HTMLResponse, include_in_schema=False)
async def register_page(request: Request):
    # This route is outside the /api/auth prefix — we register it separately below
    pass


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str
    business_name: str


def _slugify(name: str) -> str:
    """Generate a URL-safe slug from a business name."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "business"


@router.post("/register")
async def register(req: RegisterRequest, response: Response, db: AsyncSession = Depends(get_session)):
    """Create a new Business + BusinessUser and auto-login."""
    # Check unique email
    existing_user = await db.execute(
        select(BusinessUser).where(BusinessUser.email == req.email)
    )
    if existing_user.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    # Generate unique slug
    base_slug = _slugify(req.business_name)
    slug = base_slug
    counter = 1
    while True:
        existing_biz = await db.execute(
            select(Business).where(Business.slug == slug)
        )
        if existing_biz.scalar_one_or_none() is None:
            break
        slug = f"{base_slug}-{counter}"
        counter += 1

    # Create business
    business = Business(
        slug=slug,
        name=req.business_name,
    )
    db.add(business)
    await db.flush()  # Get the business ID

    # Create owner user
    user = BusinessUser(
        business_id=business.id,
        email=req.email,
        password_hash=hash_password(req.password),
        name=req.name,
        is_owner=True,
        role="owner",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Auto-login
    token = create_token(str(user.id), str(business.id))
    response.set_cookie(
        key="token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400,
    )

    return {
        "status": "ok",
        "token": token,
        "redirect": "/dashboard",
        "business_slug": slug,
    }


# We need a GET /register page route outside the /api/auth prefix.
# This is handled via a separate mini-router included by the caller.
register_page_router = APIRouter(tags=["auth"])


@register_page_router.get("/register", response_class=HTMLResponse)
async def register_page_view(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse("register.html", {"request": request})
