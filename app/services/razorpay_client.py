"""Thin client for the real Razorpay REST API — this is the seam that
replaced the old mocked process_charge()/process_refund() functions.

Auth: HTTP Basic, using RAZORPAY_KEY_ID as username and RAZORPAY_KEY_SECRET
as password (that's how Razorpay's API works — no OAuth, no bearer tokens).

Docs: https://razorpay.com/docs/api/orders/ , /payments/ , /webhooks/
"""

import hashlib
import hmac

import httpx

from app.config import settings

RAZORPAY_API_BASE = "https://api.razorpay.com/v1"


class RazorpayError(Exception):
    """Raised on any non-2xx response from Razorpay, or a network failure.
    Carries enough detail for the caller to turn it into a clean HTTP error
    rather than letting a raw httpx exception leak out."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _auth() -> tuple[str, str]:
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise RazorpayError(
            "Razorpay is not configured — set RAZORPAY_KEY_ID and "
            "RAZORPAY_KEY_SECRET in .env (see .env.example for how to get "
            "test-mode keys)."
        )
    return (settings.razorpay_key_id, settings.razorpay_key_secret)


async def create_order(*, amount_minor_units: int, currency: str, receipt: str) -> dict:
    """Creates a Razorpay Order — the object the customer's checkout widget
    pays against. Returns Razorpay's order dict (includes "id", the
    order_id the frontend needs to launch Checkout)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{RAZORPAY_API_BASE}/orders",
                auth=_auth(),
                json={
                    "amount": amount_minor_units,
                    "currency": currency,
                    "receipt": receipt[:40],
                },
            )
    except httpx.HTTPError as exc:
        raise RazorpayError(f"could not reach Razorpay: {exc}") from exc

    if response.status_code >= 400:
        raise RazorpayError(
            f"Razorpay order creation failed: {response.text}",
            status_code=response.status_code,
        )
    return response.json()


async def create_refund(*, razorpay_payment_id: str, amount_minor_units: int | None) -> dict:
    """Refunds a captured payment, fully or partially. Passing None for
    amount tells Razorpay to refund the full remaining (unrefunded) amount."""
    body = {}
    if amount_minor_units is not None:
        body["amount"] = amount_minor_units

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{RAZORPAY_API_BASE}/payments/{razorpay_payment_id}/refund",
                auth=_auth(),
                json=body,
            )
    except httpx.HTTPError as exc:
        raise RazorpayError(f"could not reach Razorpay: {exc}") from exc

    if response.status_code >= 400:
        raise RazorpayError(
            f"Razorpay refund failed: {response.text}",
            status_code=response.status_code,
        )
    return response.json()


def verify_webhook_signature(*, raw_body: bytes, signature: str) -> bool:
    """Verifies the X-Razorpay-Signature header against the raw request
    body using the webhook secret YOU configured in the Razorpay dashboard
    (RAZORPAY_WEBHOOK_SECRET — not the same as the API key secret).

    This is the only thing standing between "Razorpay told us this payment
    succeeded" and "anyone on the internet POSTed to our webhook claiming
    that" — never skip it, never trust an unverified webhook body.
    """
    if not settings.razorpay_webhook_secret:
        return False

    expected = hmac.new(
        settings.razorpay_webhook_secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
