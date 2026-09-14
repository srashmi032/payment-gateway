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


async def create_linked_account(
    *, reference_id: str, legal_business_name: str, email: str, phone: str
) -> dict:
    """Creates a Razorpay Route "linked account" for one of our merchants.
    Once created, that merchant's share of each payment can be transferred
    directly to it (see create_transfer below) — Razorpay then settles from
    the linked account to the merchant's own bank account on its own
    schedule. This platform never holds or moves the money itself.

    IMPORTANT — two things to verify before relying on this in anything
    beyond a portfolio demo:
    1. This requires OUR Razorpay account to be approved for Route/the
       Partner program. That's a manual approval from Razorpay (apply via
       your dashboard or contact their sales/support) — it does not become
       available just by generating API keys, and test-mode access to it
       may itself require that approval.
    2. The exact request shape below is a best-effort based on Razorpay's
       documented Route account-creation flow. This part of their API has
       had multiple versions (Route "linked accounts" vs. the newer
       "Partner"-style connected accounts) — verify field names against
       https://razorpay.com/docs/route/accounts/ (current as of when you
       read this) before using this against a real approved account.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.razorpay.com/v2/accounts",
                auth=_auth(),
                json={
                    "email": email,
                    "phone": phone,
                    "type": "route",
                    "reference_id": reference_id,
                    "legal_business_name": legal_business_name,
                    "business_type": "individual",
                    "contact_name": legal_business_name,
                    "profile": {"category": "other", "subcategory": "other"},
                },
            )
    except httpx.HTTPError as exc:
        raise RazorpayError(f"could not reach Razorpay: {exc}") from exc

    if response.status_code >= 400:
        raise RazorpayError(
            f"Razorpay linked account creation failed: {response.text}",
            status_code=response.status_code,
        )
    return response.json()


async def create_transfer(
    *, razorpay_payment_id: str, linked_account_id: str, amount_minor_units: int, currency: str
) -> dict:
    """Moves the merchant's net share of a captured payment to their Route
    linked account. Whatever isn't transferred (our platform fee) stays in
    our own master Razorpay account. This is the well-established, stable
    part of Route's API — higher confidence than create_linked_account."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{RAZORPAY_API_BASE}/payments/{razorpay_payment_id}/transfers",
                auth=_auth(),
                json={
                    "transfers": [
                        {
                            "account": linked_account_id,
                            "amount": amount_minor_units,
                            "currency": currency,
                            "on_hold": 0,
                        }
                    ]
                },
            )
    except httpx.HTTPError as exc:
        raise RazorpayError(f"could not reach Razorpay: {exc}") from exc

    if response.status_code >= 400:
        raise RazorpayError(
            f"Razorpay transfer failed: {response.text}", status_code=response.status_code
        )
    return response.json()


async def create_refund(
    *, razorpay_payment_id: str, amount_minor_units: int | None, reverse_all: bool = False
) -> dict:
    """Refunds a captured payment, fully or partially. Passing None for
    amount tells Razorpay to refund the full remaining (unrefunded) amount.

    reverse_all=True also claws back any Route transfer(s) associated with
    this payment — use it for full refunds. NOTE: partial refunds do NOT
    reverse a proportional slice of the transfer here (Razorpay supports
    that but it needs per-transfer reversal calls this client doesn't
    implement yet) — a partial refund currently leaves the merchant's
    already-transferred amount untouched, which means a partial refund
    comes out of the platform's own margin, not the merchant's payout.
    Flag this to whoever owns reconciliation before relying on it.
    """
    body = {}
    if amount_minor_units is not None:
        body["amount"] = amount_minor_units
    if reverse_all:
        body["reverse_all"] = 1

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
