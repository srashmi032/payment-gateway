from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models import ApiKey, User
from app.schemas import ApiKeyCreated, ApiKeyCreateRequest, ApiKeyRead
from app.security import generate_api_keypair, hash_password, secret_prefix

router = APIRouter(prefix="/v1/api-keys", tags=["api-keys"])


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: ApiKeyCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyCreated:
    public_key, raw_secret = generate_api_keypair()

    api_key = ApiKey(
        merchant_id=user.merchant_id,
        name=payload.name,
        public_key=public_key,
        hashed_secret=hash_password(raw_secret),
        secret_prefix=secret_prefix(raw_secret),
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return ApiKeyCreated(**ApiKeyRead.model_validate(api_key).model_dump(), secret_key=raw_secret)


@router.get("", response_model=list[ApiKeyRead])
async def list_api_keys(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[ApiKey]:
    result = await db.scalars(
        select(ApiKey)
        .where(ApiKey.merchant_id == user.merchant_id)
        .order_by(ApiKey.created_at.desc())
    )
    return list(result)
