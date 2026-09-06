from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class SignupRequest(BaseModel):
    business_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class SignupResponse(BaseModel):
    merchant_id: str
    user_id: str
    message: str = "Signup successful. Check your email to verify your account."


class VerifyEmailRequest(BaseModel):
    token: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class MerchantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_name: str
    legal_name: str | None
    business_category: str | None
    settlement_bank_account_holder: str | None
    settlement_bank_account_number: str | None
    settlement_bank_routing_code: str | None
    settlement_bank_name: str | None
    enabled_currencies: list[str]
    payment_methods: list[str]
    created_at: datetime
    updated_at: datetime


class MerchantProfileUpdate(BaseModel):
    business_name: str | None = Field(default=None, min_length=1, max_length=255)
    legal_name: str | None = Field(default=None, max_length=255)
    business_category: str | None = Field(default=None, max_length=100)
    settlement_bank_account_holder: str | None = Field(default=None, max_length=255)
    settlement_bank_account_number: str | None = Field(default=None, max_length=64)
    settlement_bank_routing_code: str | None = Field(default=None, max_length=32)
    settlement_bank_name: str | None = Field(default=None, max_length=255)


class MerchantConfigUpdate(BaseModel):
    enabled_currencies: list[str] | None = None
    payment_methods: list[str] | None = None


class ApiKeyCreateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)


class ApiKeyRead(BaseModel):
    """Never includes the secret — only shown once, at creation time."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str | None
    public_key: str
    secret_prefix: str
    revoked_at: datetime | None
    created_at: datetime


class ApiKeyCreated(ApiKeyRead):
    secret_key: str


class CustomerInfo(BaseModel):
    """Who a payment is from — deliberately minimal. At least one of
    email/phone is required so a customer can actually be identified/
    contacted; a name alone isn't enough to be useful."""

    name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def _require_email_or_phone(self) -> "CustomerInfo":
        if not self.email and not self.phone:
            raise ValueError("customer.email or customer.phone is required")
        return self


class CustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str | None
    email: str | None
    phone: str | None


class PaymentCreateRequest(BaseModel):
    amount_minor_units: int = Field(gt=0, description="Smallest currency unit, e.g. cents/paise")
    currency: str = Field(min_length=3, max_length=3)
    description: str | None = Field(default=None, max_length=500)
    customer: CustomerInfo


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    merchant_id: str
    customer: CustomerRead | None
    amount_minor_units: int
    currency: str
    description: str | None
    status: str
    refunded_amount_minor_units: int
    razorpay_order_id: str | None
    razorpay_payment_id: str | None
    platform_fee_minor_units: int
    net_amount_minor_units: int | None
    take_rate_bps_snapshot: int | None
    created_at: datetime
    updated_at: datetime


class PaymentCreated(PaymentRead):
    """Returned from POST /v1/payments — includes what the merchant's
    frontend needs to actually launch Razorpay Checkout for the customer."""

    razorpay_key_id: str


class RefundRequest(BaseModel):
    # Omit or null = refund the full remaining (unrefunded) amount.
    amount_minor_units: int | None = Field(default=None, gt=0)
