from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "payment-service-saas"
    environment: str = "local"

    database_url: str = "postgresql+asyncpg://postgres:mysecretpassword@localhost:5432/payment_service"

    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Razorpay (test-mode keys from the Razorpay dashboard — see .env.example
    # for where to get them). Left blank until you have real ones; any call
    # to app/services/razorpay_client.py will fail clearly until then.
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""


settings = Settings()
