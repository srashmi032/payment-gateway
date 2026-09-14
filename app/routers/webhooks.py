import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Merchant, Payment
from app.services.fees import compute_platform_fee
from app.services.razorpay_client import RazorpayError, create_transfer, verify_webhook_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


@router.post("/razorpay", status_code=status.HTTP_200_OK)
async def razorpay_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Source of truth for payment confirmation — never trust a client
    telling us a payment succeeded, only this (signature-verified) webhook.

    Must read the RAW body for signature verification before any JSON
    parsing, which is why this takes a bare Request instead of a Pydantic
    body model.
    """
    raw_body = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")

    if not verify_webhook_signature(raw_body=raw_body, signature=signature):
        raise HTTPException(status_code=400, detail="invalid webhook signature")

    payload = await request.json()
    event = payload.get("event")

    if event == "payment.captured":
        await _handle_payment_captured(db, payload)
    elif event == "payment.failed":
        await _handle_payment_failed(db, payload)
    else:
        logger.info("ignoring unhandled razorpay webhook event: %s", event)

    # Razorpay expects a fast 2xx ack and retries on anything else — always
    # return 200 once signature verification has passed, even for events
    # we don't act on.
    return {"status": "ok"}


async def _handle_payment_captured(db: AsyncSession, payload: dict) -> None:
    entity = payload["payload"]["payment"]["entity"]
    order_id = entity["order_id"]
    razorpay_payment_id = entity["id"]

    payment = await db.scalar(select(Payment).where(Payment.razorpay_order_id == order_id))
    if payment is None:
        logger.warning("payment.captured webhook for unknown order_id=%s", order_id)
        return
    if payment.status == "succeeded":
        # Webhooks can be delivered more than once — this must be a no-op
        # on redelivery, not a double-transfer.
        return

    merchant = await db.get(Merchant, payment.merchant_id)
    fee, net = compute_platform_fee(
        amount_minor_units=payment.amount_minor_units, take_rate_bps=merchant.take_rate_bps
    )

    payment.razorpay_payment_id = razorpay_payment_id
    payment.status = "succeeded"
    payment.platform_fee_minor_units = fee
    payment.net_amount_minor_units = net
    payment.take_rate_bps_snapshot = merchant.take_rate_bps

    if merchant.razorpay_account_id:
        try:
            transfer = await create_transfer(
                razorpay_payment_id=razorpay_payment_id,
                linked_account_id=merchant.razorpay_account_id,
                amount_minor_units=net,
                currency=payment.currency,
            )
            payment.razorpay_transfer_id = transfer.get("id")
        except RazorpayError:
            # Payment stays "succeeded" (the customer really was charged)
            # even if the transfer failed — but the merchant's share is
            # stuck in the platform's master account until this is retried
            # or handled manually. Logged loudly on purpose.
            logger.exception(
                "razorpay transfer failed for payment %s (merchant %s) — "
                "funds are in the platform account, needs manual follow-up",
                payment.id,
                merchant.id,
            )
    else:
        logger.warning(
            "merchant %s has no razorpay_account_id — payment %s captured "
            "but nothing was transferred, funds sit in the platform account",
            merchant.id,
            payment.id,
        )

    await db.commit()


async def _handle_payment_failed(db: AsyncSession, payload: dict) -> None:
    entity = payload["payload"]["payment"]["entity"]
    order_id = entity["order_id"]

    payment = await db.scalar(select(Payment).where(Payment.razorpay_order_id == order_id))
    if payment is not None and payment.status == "created":
        payment.status = "failed"
        await db.commit()
