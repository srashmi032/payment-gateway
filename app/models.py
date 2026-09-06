import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid_str() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Merchant(Base):
    __tablename__ = "merchant"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    business_name: Mapped[str] = mapped_column(String(255))

    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    settlement_bank_account_holder: Mapped[str | None] = mapped_column(String(255), nullable=True)
    settlement_bank_account_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    settlement_bank_routing_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    settlement_bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    enabled_currencies: Mapped[list] = mapped_column(JSONB, default=list)
    payment_methods: Mapped[list] = mapped_column(JSONB, default=list)

    # Platform take-rate, in basis points (250 = 2.50%), deducted from each
    # captured payment before computing the merchant's net amount. Snapshotted
    # onto each Payment at capture time so later rate changes never alter
    # historical fee reporting.
    take_rate_bps: Mapped[int] = mapped_column(default=250)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Customer(Base):
    """The end customer paying a merchant — minimal by design: just enough
    to identify who a payment is from. Not a full identity/auth system."""

    __tablename__ = "customer"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    merchant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("merchant.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RefreshToken(Base):
    __tablename__ = "refresh_token"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ApiKey(Base):
    __tablename__ = "api_key"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    merchant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("merchant.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    public_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # One-way hash (bcrypt, via app.security.hash_password) — never store the
    # raw secret. Verified by re-hashing a presented secret and comparing,
    # same pattern as a login password.
    hashed_secret: Mapped[str] = mapped_column(String(255))
    # First ~12 chars of the raw secret, kept in cleartext so the dashboard
    # can display "key ending in ..." without ever re-showing the full value.
    secret_prefix: Mapped[str] = mapped_column(String(16))

    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Payment(Base):
    __tablename__ = "payment"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    merchant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("merchant.id", ondelete="CASCADE"), index=True
    )
    # Nullable so existing dev rows created before this column existed don't
    # break the migration — every payment created going forward always gets one
    # (enforced by the API layer, not the DB, since this is dev-stage data).
    customer_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("customer.id"), nullable=True, index=True
    )
    # eager-loaded (selectin) so listing payments never N+1s on customer info
    customer: Mapped["Customer | None"] = relationship(lazy="selectin")

    # Amounts are always integers in the smallest currency unit (cents/paise)
    # — never floats — to avoid rounding errors.
    amount_minor_units: Mapped[int] = mapped_column()
    currency: Mapped[str] = mapped_column(String(3))
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # created (order placed, awaiting customer checkout) -> succeeded (webhook
    # confirmed capture) | failed -> partially_refunded -> refunded.
    # Driven by real Razorpay webhooks (see app/routers/webhooks.py), never
    # self-reported by the merchant.
    status: Mapped[str] = mapped_column(String(20), default="created")
    refunded_amount_minor_units: Mapped[int] = mapped_column(default=0)

    # Razorpay identifiers. order_id exists from creation; payment_id is only
    # filled in once the customer actually completes checkout and Razorpay
    # confirms capture via webhook.
    razorpay_order_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    razorpay_payment_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )

    # Platform economics — computed and snapshotted at capture time (see
    # app/services/fees.py), never before, since a payment that never
    # captures never earns the platform anything.
    platform_fee_minor_units: Mapped[int] = mapped_column(default=0)
    net_amount_minor_units: Mapped[int | None] = mapped_column(nullable=True)
    take_rate_bps_snapshot: Mapped[int | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class User(Base):
    __tablename__ = "user"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    merchant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("merchant.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))

    is_email_verified: Mapped[bool] = mapped_column(default=False)
    email_verification_token: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
