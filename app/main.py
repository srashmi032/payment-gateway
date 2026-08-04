from fastapi import FastAPI

from app.config import settings

app = FastAPI(title=settings.app_name)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
