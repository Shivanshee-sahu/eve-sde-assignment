import logging

from sqlalchemy.exc import SQLAlchemyError

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.services.webhook_service import process_webhook_event

logger = logging.getLogger("eve.tasks")


@celery_app.task(
    bind=True,
    name="app.tasks.process_payment_webhook",
    autoretry_for=(SQLAlchemyError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
)
def process_payment_webhook(self, event_id: str) -> str:
    with SessionLocal() as db:
        result = process_webhook_event(db, event_id)
    logger.info("webhook_task_finished", extra={"event": "webhook_task_finished", "event_id": event_id})
    return result
