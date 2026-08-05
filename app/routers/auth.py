import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models import Merchant, RefreshToken, User
from app.schemas import (
    LoginRequest,
    SignupRequest,
    SignupResponse,
    TokenResponse,
    VerifyEmailRequest,
)
from app.security import (
    REFRESH_TOKEN_EXPIRE_DAYS,
    create_access_token,
    generate_refresh_token,
    generate_verification_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
async def signup(payload: SignupRequest, db: AsyncSession = Depends(get_db)) -> SignupResponse:
    existing = await db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(status_code=400, detail="an account with this email already exists")

    merchant = Merchant(business_name=payload.business_name)
    db.add(merchant)
    await db.flush()

    verification_token = generate_verification_token()
    user = User(
        merchant_id=merchant.id,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        is_email_verified=False,
        email_verification_token=verification_token,
    )
    db.add(user)
    await db.commit()

    # No email provider wired up yet — log the token so it can be used to
    # exercise POST /v1/auth/verify-email during local development.
    logger.info("verification token for %s: %s", payload.email, verification_token)

    return SignupResponse(merchant_id=merchant.id, user_id=user.id)


@router.post("/verify-email", status_code=status.HTTP_200_OK)
async def verify_email(payload: VerifyEmailRequest, db: AsyncSession = Depends(get_db)) -> dict:
    user = await db.scalar(
        select(User).where(User.email_verification_token == payload.token)
    )
    if user is None:
        raise HTTPException(status_code=400, detail="invalid or already-used verification token")

    user.is_email_verified = True
    user.email_verification_token = None
    await db.commit()

    return {"message": "email verified"}


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    user = await db.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="invalid email or password")

    access_token = create_access_token(user_id=user.id, merchant_id=user.merchant_id)

    raw_refresh_token = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(raw_refresh_token),
            expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        )
    )
    await db.commit()

    return TokenResponse(access_token=access_token, refresh_token=raw_refresh_token)
