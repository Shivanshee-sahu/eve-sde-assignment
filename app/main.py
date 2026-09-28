from fastapi import FastAPI

from app.api.routes import router
from app.core.logging import configure_logging

configure_logging()

app = FastAPI(title="EVE Healthcare Backend", version="1.0.0", description="Diagnostic booking, Redis caching, and Celery-backed simulated payment webhook processing")
app.include_router(router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
