from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


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
