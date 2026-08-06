import logging

from fastapi import FastAPI

from app.config import settings
from app.routers.auth import router as auth_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(title=settings.app_name)

app.include_router(auth_router)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
