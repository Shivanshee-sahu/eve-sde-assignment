import json
import logging
import logging.config
from datetime import datetime, timezone

from app.core.config import settings


class JsonFormatter(logging.Formatter):
    fields = ("event", "user_id", "booking_id", "payment_id", "provider_payment_id", "event_id", "scope", "status_code")

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in self.fields:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"json": {"()": JsonFormatter}},
        "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json", "stream": "ext://sys.stdout"}},
        "loggers": {"eve": {"handlers": ["console"], "level": settings.log_level.upper(), "propagate": False}},
    })
