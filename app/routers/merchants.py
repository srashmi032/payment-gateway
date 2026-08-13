from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models import Merchant, User
from app.schemas import MerchantConfigUpdate, MerchantProfileUpdate, MerchantRead

router = APIRouter(prefix="/v1/merchants", tags=["merchants"])


async def _get_own_merchant(db: AsyncSession, user: User) -> Merchant:
    merchant = await db.get(Merchant, user.merchant_id)
    if merchant is None:
        raise HTTPException(status_code=404, detail="merchant not found")
    return merchant


@router.get("/me", response_model=MerchantRead)
async def get_my_merchant(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Merchant:
    return await _get_own_merchant(db, user)


@router.patch("/me", response_model=MerchantRead)
async def update_my_merchant(
    payload: MerchantProfileUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Merchant:
    merchant = await _get_own_merchant(db, user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(merchant, field, value)
    await db.commit()
    await db.refresh(merchant)
    return merchant


@router.patch("/me/config", response_model=MerchantRead)
async def update_my_merchant_config(
    payload: MerchantConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Merchant:
    merchant = await _get_own_merchant(db, user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(merchant, field, value)
    await db.commit()
    await db.refresh(merchant)
    return merchant
