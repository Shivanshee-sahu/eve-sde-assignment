from celery import Celery

from app.core.config import settings
from app.core.logging import configure_logging

configure_logging()

broker_url = settings.celery_broker_url or settings.redis_url or "redis://localhost:6379/1"
result_backend = settings.celery_result_backend or broker_url

celery_app = Celery("eve_healthcare", broker=broker_url, backend=result_backend)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    task_default_queue="eve_webhooks",
    task_default_exchange="eve_webhooks",
    task_default_routing_key="eve_webhooks",
    task_routes={"app.tasks.process_payment_webhook": {"queue": "eve_webhooks"}},
)

import app.tasks.webhooks  # noqa: E402,F401
