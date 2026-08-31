from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models import ApiKey, User
from app.schemas import ApiKeyCreated, ApiKeyCreateRequest, ApiKeyRead
from app.security import generate_api_keypair, hash_password, secret_prefix

router = APIRouter(prefix="/v1/api-keys", tags=["api-keys"])


async def _get_own_key_or_404(db: AsyncSession, user: User, api_key_id: str) -> ApiKey:
    api_key = await db.get(ApiKey, api_key_id)
    if api_key is None or api_key.merchant_id != user.merchant_id:
        raise HTTPException(status_code=404, detail="api key not found")
    return api_key


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


@router.post("/{api_key_id}/regenerate", response_model=ApiKeyCreated)
async def regenerate_api_key(
    api_key_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyCreated:
    api_key = await _get_own_key_or_404(db, user, api_key_id)
    if api_key.revoked_at is not None:
        raise HTTPException(status_code=400, detail="cannot regenerate a revoked key")

    # public_key stays stable — only the secret is rolled, matching Stripe's
    # "roll key" UX. Anything integrated against the old public_key keeps
    # resolving to the same key record; only the old secret stops working.
    _, raw_secret = generate_api_keypair()
    api_key.hashed_secret = hash_password(raw_secret)
    api_key.secret_prefix = secret_prefix(raw_secret)

    await db.commit()
    await db.refresh(api_key)

    return ApiKeyCreated(**ApiKeyRead.model_validate(api_key).model_dump(), secret_key=raw_secret)


@router.delete("/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    api_key_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    api_key = await _get_own_key_or_404(db, user, api_key_id)
    if api_key.revoked_at is None:
        api_key.revoked_at = datetime.now(timezone.utc)
        await db.commit()
