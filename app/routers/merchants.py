from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models import Merchant, User
from app.schemas import MerchantConfigUpdate, MerchantProfileUpdate, MerchantRead
from app.services.razorpay_client import RazorpayError, create_linked_account

router = APIRouter(prefix="/v1/merchants", tags=["merchants"])

_RAZORPAY_ACCOUNT_REQUIRED_FIELDS = (
    "legal_name",
    "contact_phone",
    "settlement_bank_account_holder",
    "settlement_bank_account_number",
    "settlement_bank_routing_code",
    "settlement_bank_name",
)


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


@router.post("/me/razorpay-account", response_model=MerchantRead)
async def create_my_razorpay_account(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Merchant:
    """Creates the Razorpay Route linked account this merchant's payments
    get transferred to. Requires our platform's Razorpay account to be
    Route/Partner-approved (see razorpay_client.create_linked_account) —
    calling this before that approval will fail with whatever error
    Razorpay's API returns for an unapproved account.

    Note: this only creates the account object. A full Route integration
    also needs a separate "stakeholder"/bank-account call to attach the
    merchant's settlement bank details to the linked account before
    Razorpay can actually pay them out — not implemented here yet. We
    still require those fields to be filled in on our side first, as our
    own minimum-completeness gate before onboarding a merchant onto Route.
    """
    merchant = await _get_own_merchant(db, user)
    if merchant.razorpay_account_id:
        raise HTTPException(status_code=400, detail="razorpay linked account already exists")

    missing = [f for f in _RAZORPAY_ACCOUNT_REQUIRED_FIELDS if not getattr(merchant, f)]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=(
                "complete these profile fields before creating a Razorpay "
                f"account: {', '.join(missing)}"
            ),
        )

    try:
        account = await create_linked_account(
            reference_id=merchant.id,
            legal_business_name=merchant.legal_name,
            email=user.email,
            phone=merchant.contact_phone,
        )
    except RazorpayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    merchant.razorpay_account_id = account["id"]
    await db.commit()
    await db.refresh(merchant)
    return merchant
