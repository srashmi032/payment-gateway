import logging

from fastapi import FastAPI

from app.config import settings
from app.routers.api_keys import router as api_keys_router
from app.routers.auth import router as auth_router
from app.routers.merchants import router as merchants_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(title=settings.app_name)

app.include_router(auth_router)
app.include_router(merchants_router)
app.include_router(api_keys_router)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
