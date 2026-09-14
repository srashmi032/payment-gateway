import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.models import Customer, Merchant, Payment, User
from app.schemas import PaymentCreated, PaymentCreateRequest, PaymentRead, RefundRequest
from app.services.razorpay_client import RazorpayError, create_order, create_refund

router = APIRouter(prefix="/v1/payments", tags=["payments"])


async def _get_own_payment_or_404(db: AsyncSession, user: User, payment_id: str) -> Payment:
    payment = await db.get(Payment, payment_id)
    if payment is None or payment.merchant_id != user.merchant_id:
        raise HTTPException(status_code=404, detail="payment not found")
    return payment


async def _find_or_create_customer(
    db: AsyncSession, merchant_id: str, info
) -> Customer:
    """Reuses an existing customer row by email within this merchant, so a
    repeat payer doesn't accumulate a new row every time. Falls back to
    creating a new row (e.g. phone-only customers, or first-time emails)."""
    if info.email:
        existing = await db.scalar(
            select(Customer).where(
                Customer.merchant_id == merchant_id, Customer.email == info.email
            )
        )
        if existing is not None:
            return existing

    customer = Customer(
        merchant_id=merchant_id, name=info.name, email=info.email, phone=info.phone
    )
    db.add(customer)
    await db.flush()
    return customer


@router.post("", response_model=PaymentCreated, status_code=status.HTTP_201_CREATED)
async def create_payment(
    payload: PaymentCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaymentCreated:
    merchant = await db.get(Merchant, user.merchant_id)
    currency = payload.currency.upper()

    if not merchant.razorpay_account_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "merchant has no Razorpay linked account yet — complete "
                "POST /v1/merchants/me/razorpay-account before accepting "
                "payments, otherwise your share of the money has nowhere "
                "to be transferred to"
            ),
        )

    # Lenient on purpose: an empty enabled_currencies list means the
    # merchant hasn't restricted currencies yet, so anything is allowed.
    if merchant.enabled_currencies and currency not in merchant.enabled_currencies:
        raise HTTPException(
            status_code=400,
            detail=f"currency '{currency}' is not enabled for this merchant",
        )

    customer = await _find_or_create_customer(db, user.merchant_id, payload.customer)

    payment_id = str(uuid.uuid4())
    try:
        order = await create_order(
            amount_minor_units=payload.amount_minor_units,
            currency=currency,
            receipt=payment_id,
        )
    except RazorpayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    payment = Payment(
        id=payment_id,
        merchant_id=user.merchant_id,
        customer_id=customer.id,
        amount_minor_units=payload.amount_minor_units,
        currency=currency,
        description=payload.description,
        status="created",
        razorpay_order_id=order["id"],
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)

    return PaymentCreated(
        **PaymentRead.model_validate(payment).model_dump(),
        razorpay_key_id=settings.razorpay_key_id,
    )


@router.get("/{payment_id}", response_model=PaymentRead)
async def get_payment(
    payment_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Payment:
    return await _get_own_payment_or_404(db, user, payment_id)


@router.get("", response_model=list[PaymentRead])
async def list_payments(
    payment_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Payment]:
    query = select(Payment).where(Payment.merchant_id == user.merchant_id)
    if payment_status is not None:
        query = query.where(Payment.status == payment_status)
    query = query.order_by(Payment.created_at.desc()).limit(limit).offset(offset)

    result = await db.scalars(query)
    return list(result)


@router.post("/{payment_id}/refund", response_model=PaymentRead)
async def refund_payment(
    payment_id: str,
    payload: RefundRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Payment:
    payment = await _get_own_payment_or_404(db, user, payment_id)

    if payment.status not in ("succeeded", "partially_refunded"):
        raise HTTPException(
            status_code=400,
            detail=f"cannot refund a payment with status '{payment.status}'",
        )
    if payment.razorpay_payment_id is None:
        # Shouldn't happen if status is succeeded/partially_refunded, but
        # guards against any inconsistent state.
        raise HTTPException(status_code=400, detail="payment was never captured")

    remaining = payment.amount_minor_units - payment.refunded_amount_minor_units
    refund_amount = (
        payload.amount_minor_units if payload.amount_minor_units is not None else remaining
    )

    if refund_amount > remaining:
        raise HTTPException(
            status_code=400,
            detail=f"refund amount {refund_amount} exceeds remaining refundable amount {remaining}",
        )

    is_full_refund = refund_amount == remaining
    try:
        await create_refund(
            razorpay_payment_id=payment.razorpay_payment_id,
            amount_minor_units=refund_amount,
            # Full refund also claws back the Route transfer already made
            # to the merchant. Partial refunds do NOT reverse any transfer
            # (see create_refund's docstring) — the merchant keeps their
            # already-transferred share, and the refund comes out of the
            # platform's own margin until per-transfer reversal is built.
            reverse_all=is_full_refund,
        )
    except RazorpayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    payment.refunded_amount_minor_units += refund_amount
    payment.status = (
        "refunded"
        if payment.refunded_amount_minor_units == payment.amount_minor_units
        else "partially_refunded"
    )

    await db.commit()
    await db.refresh(payment)
    return payment
