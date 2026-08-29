import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

REFRESH_TOKEN_EXPIRE_DAYS = 30


def hash_password(raw_password: str) -> str:
    return pwd_context.hash(raw_password)


def verify_password(raw_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(raw_password, hashed_password)


def generate_verification_token() -> str:
    return secrets.token_urlsafe(32)


def create_access_token(*, user_id: str, merchant_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "merchant_id": merchant_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw_token: str) -> str:
    # One-way hash — the DB never stores the raw refresh token, only enough
    # to verify a presented token by re-hashing and comparing.
    return hashlib.sha256(raw_token.encode()).hexdigest()


_B62_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def _random_b62(length: int) -> str:
    return "".join(secrets.choice(_B62_ALPHABET) for _ in range(length))


def generate_api_keypair() -> tuple[str, str]:
    """Returns (public_key, raw_secret_key). The caller must show
    raw_secret_key to the client exactly once and never persist it —
    only its hash (hash_password) and prefix (secret_prefix) are stored."""
    public_key = f"pk_{_random_b62(22)}"
    secret_key = f"sk_{_random_b62(32)}"
    return public_key, secret_key


def secret_prefix(raw_secret_key: str) -> str:
    return raw_secret_key[:12]
