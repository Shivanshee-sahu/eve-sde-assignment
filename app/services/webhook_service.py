from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Booking, Payment, WebhookEvent
from app.services.booking_service import InvalidBookingTransition, transition_booking


def process_webhook_event(db: Session, event_id: str) -> str:
    """Apply a persisted event exactly once; SQL errors are left for Celery to retry."""
    try:
        event = db.scalar(select(WebhookEvent).where(WebhookEvent.event_id == event_id).with_for_update())
        if event is None:
            return "missing"
        if event.processing_status == "PROCESSED":
            return "duplicate"

        event.processing_status = "PROCESSING"
        payment = db.scalar(select(Payment).where(Payment.provider_payment_id == event.payment_id).with_for_update())
        if payment is None:
            event.processing_status = "FAILED"
            db.commit()
            return "payment_missing"

        booking = db.scalar(select(Booking).where(Booking.id == payment.booking_id).with_for_update())
        result = event.payload["status"]
        if payment.status == "PENDING":
            payment.status = result
            if booking.status == "PENDING":
                transition_booking(booking, "CONFIRMED" if result == "SUCCESS" else "FAILED")
        event.processing_status = "PROCESSED"
        event.processed_at = datetime.now(timezone.utc)
        db.commit()
        return "processed"
    except (SQLAlchemyError, InvalidBookingTransition, KeyError):
        db.rollback()
        raise
