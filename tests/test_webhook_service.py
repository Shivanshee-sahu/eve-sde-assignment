from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Booking, CentreTest, DiagnosticCentre, DiagnosticTest, Payment, User, WebhookEvent
from app.services.webhook_service import process_webhook_event
from app.core.celery_app import celery_app


def test_webhook_worker_confirms_pending_payment_once():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(name="Worker Test", email="worker@example.com", password_hash="not-a-login-hash")
        centre = DiagnosticCentre(name="Worker Centre", location="Dhanbad")
        test = DiagnosticTest(name="Worker CBC", description="CBC")
        db.add_all([user, centre, test])
        db.flush()
        offer = CentreTest(centre_id=centre.id, test_id=test.id, price=Decimal("450.00"))
        db.add(offer)
        db.flush()
        booking = Booking(user_id=user.id, centre_id=centre.id, test_id=test.id,
                          appointment_datetime=datetime.now(timezone.utc) + timedelta(days=1),
                          amount=Decimal("450.00"), status="PENDING")
        db.add(booking)
        db.flush()
        payment = Payment(booking_id=booking.id, amount=booking.amount, status="PENDING",
                          provider_payment_id="pay_worker_test")
        event = WebhookEvent(event_id="evt_worker_test", event_type="payment.success",
                             payment_id="pay_worker_test", payload={"status": "SUCCESS"},
                             processing_status="RECEIVED")
        db.add_all([payment, event])
        db.commit()

        assert process_webhook_event(db, "evt_worker_test") == "processed"
        db.refresh(booking)
        db.refresh(payment)
        db.refresh(event)
        assert booking.status == "CONFIRMED"
        assert payment.status == "SUCCESS"
        assert event.processing_status == "PROCESSED"
        assert process_webhook_event(db, "evt_worker_test") == "duplicate"

    Base.metadata.drop_all(engine)


def test_celery_uses_an_isolated_webhook_queue():
    assert celery_app.conf.task_default_queue == "eve_webhooks"
    assert celery_app.conf.task_routes["app.tasks.process_payment_webhook"]["queue"] == "eve_webhooks"


def test_failed_webhook_fails_pending_payment_and_booking():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(name="Failure Test", email="failure@example.com", password_hash="not-a-login-hash")
        centre = DiagnosticCentre(name="Failure Centre", location="Dhanbad")
        test = DiagnosticTest(name="Failure CBC", description="CBC")
        db.add_all([user, centre, test]); db.flush()
        db.add(CentreTest(centre_id=centre.id, test_id=test.id, price=Decimal("250.00"))); db.flush()
        booking = Booking(user_id=user.id, centre_id=centre.id, test_id=test.id,
                          appointment_datetime=datetime.now(timezone.utc) + timedelta(days=1),
                          amount=Decimal("250.00"), status="PENDING")
        db.add(booking); db.flush()
        payment = Payment(booking_id=booking.id, amount=booking.amount, status="PENDING",
                          provider_payment_id="pay_failed_worker")
        event = WebhookEvent(event_id="evt_failed_worker", event_type="payment.failed",
                             payment_id="pay_failed_worker", payload={"status": "FAILED"},
                             processing_status="RECEIVED")
        db.add_all([payment, event]); db.commit()

        assert process_webhook_event(db, "evt_failed_worker") == "processed"
        db.refresh(booking); db.refresh(payment)
        assert booking.status == "FAILED"
        assert payment.status == "FAILED"

    Base.metadata.drop_all(engine)
