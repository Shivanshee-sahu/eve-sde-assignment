import logging
import uuid
from datetime import datetime, timezone
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query
from kombu.exceptions import OperationalError as BrokerOperationalError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api.pagination import paginate
from app.core.cache import delete_cached_pattern, get_cached_json, set_cached_json
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import rate_limit
from app.core.security import create_access_token, hash_password, verify_password
from app.dependencies import get_current_user, require_admin
from app.models import Booking, CentreTest, DiagnosticCentre, DiagnosticTest, Payment, User, WebhookEvent
from app.schemas.api import (
    BookingCreate,
    BookingOut,
    CentreCreate,
    CentreOut,
    CentreTestCreate,
    DiagnosticTestCreate,
    Login,
    Page,
    PaymentCreate,
    PaymentOut,
    Signup,
    TestCatalogOut,
    TestOut,
    Token,
    UserOut,
    WebhookIn,
    WebhookOut,
)
from app.services.booking_service import InvalidBookingTransition, transition_booking
from app.tasks.webhooks import process_payment_webhook

router = APIRouter()
logger = logging.getLogger("eve.api")
auth_limit = rate_limit("auth", settings.auth_requests_per_minute)
booking_limit = rate_limit("bookings", settings.booking_requests_per_minute)
payment_limit = rate_limit("payments", settings.payment_requests_per_minute)
webhook_limit = rate_limit("payment-webhooks", settings.webhook_requests_per_minute)
admin_limit = rate_limit("catalog-admin", settings.admin_requests_per_minute)


@router.post("/auth/signup", response_model=UserOut, status_code=201, tags=["auth"],
             dependencies=[Depends(auth_limit)], responses={429: {"description": "Authentication rate limit exceeded"}})
def signup(data: Signup, db: Session = Depends(get_db)):
    user = User(name=data.name.strip(), email=data.email.lower(), password_hash=hash_password(data.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Email is already registered")
    db.refresh(user)
    logger.info("user_signed_up", extra={"event": "user_signed_up", "user_id": user.id})
    return user


@router.post("/auth/login", response_model=Token, tags=["auth"],
             dependencies=[Depends(auth_limit)], responses={429: {"description": "Authentication rate limit exceeded"}})
def login(data: Login, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email.lower()))
    if user is None or not verify_password(data.password, user.password_hash):
        logger.warning("login_failed", extra={"event": "login_failed"})
        raise HTTPException(401, "Invalid email or password", headers={"WWW-Authenticate": "Bearer"})
    logger.info("user_logged_in", extra={"event": "user_logged_in", "user_id": user.id})
    return Token(access_token=create_access_token(str(user.id)))


@router.get("/centres/", response_model=Page[CentreOut], tags=["centres"],
            summary="List diagnostic centres", description="Paginated centre list with tests and centre-specific prices.")
def list_centres(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    key = f"eve:centres:v1:p{page}:s{page_size}"
    cached = get_cached_json(key)
    if cached is not None:
        return Page[CentreOut].model_validate(cached)
    query = select(DiagnosticCentre).options(
        selectinload(DiagnosticCentre.offerings).joinedload(CentreTest.test)
    ).order_by(DiagnosticCentre.id)
    result = paginate(db, query, DiagnosticCentre, page, page_size)
    response = Page[CentreOut](
        items=[_centre_out(c) for c in result.items], total=result.total,
        page=page, page_size=page_size, pages=result.pages,
    )
    set_cached_json(key, response.model_dump(mode="json"))
    return response


@router.get("/centres/{centre_id}", response_model=CentreOut, tags=["centres"])
def get_centre(centre_id: int, db: Session = Depends(get_db)):
    key = f"eve:centre:v1:{centre_id}"
    cached = get_cached_json(key)
    if cached is not None:
        return CentreOut.model_validate(cached)
    centre = db.scalar(
        select(DiagnosticCentre)
        .where(DiagnosticCentre.id == centre_id)
        .options(selectinload(DiagnosticCentre.offerings).joinedload(CentreTest.test))
    )
    if centre is None:
        raise HTTPException(404, "Diagnostic centre not found")
    response = CentreOut.model_validate(_centre_out(centre))
    set_cached_json(key, response.model_dump(mode="json"))
    return response


@router.post("/centres/", response_model=CentreOut, status_code=201, tags=["centres"],
             summary="Create a diagnostic centre", dependencies=[Depends(require_admin), Depends(admin_limit)],
             responses={403: {"description": "Invalid admin key"}, 503: {"description": "Admin API key is not configured"}})
def create_centre(data: CentreCreate, db: Session = Depends(get_db)):
    centre = DiagnosticCentre(name=data.name.strip(), location=data.location.strip())
    db.add(centre)
    db.commit()
    db.refresh(centre)
    delete_cached_pattern("eve:centres:v1:*")
    logger.info("centre_created", extra={"event": "centre_created"})
    return _centre_out(centre)


def _centre_out(centre):
    return {
        "id": centre.id,
        "name": centre.name,
        "location": centre.location,
        "tests": [
            {
                "id": offer.test.id,
                "name": offer.test.name,
                "description": offer.test.description,
                "price": offer.price,
            }
            for offer in centre.offerings
        ],
    }


@router.get("/tests/", response_model=Page[TestCatalogOut], tags=["tests"],
            summary="List diagnostic tests", description="Paginated diagnostic test catalogue.")
def list_tests(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    key = f"eve:tests:v1:p{page}:s{page_size}"
    cached = get_cached_json(key)
    if cached is not None:
        return Page[TestCatalogOut].model_validate(cached)
    query = select(DiagnosticTest).order_by(DiagnosticTest.id)
    result = paginate(db, query, DiagnosticTest, page, page_size)
    response = Page[TestCatalogOut](
        items=[TestCatalogOut.model_validate(item) for item in result.items],
        total=result.total,
        page=page,
        page_size=page_size,
        pages=result.pages,
    )
    set_cached_json(key, response.model_dump(mode="json"))
    return response


@router.post("/tests/", response_model=TestCatalogOut, status_code=201, tags=["tests"],
             summary="Create a diagnostic test", dependencies=[Depends(require_admin), Depends(admin_limit)])
def create_test(data: DiagnosticTestCreate, db: Session = Depends(get_db)):
    test = DiagnosticTest(name=data.name.strip(), description=data.description.strip())
    db.add(test)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A diagnostic test with this name already exists")
    db.refresh(test)
    delete_cached_pattern("eve:tests:v1:*")
    logger.info("diagnostic_test_created", extra={"event": "diagnostic_test_created"})
    return test


@router.post("/centres/{centre_id}/tests", response_model=TestOut, status_code=201, tags=["centres"],
             summary="Offer a test at a centre", dependencies=[Depends(require_admin), Depends(admin_limit)])
def add_centre_test(centre_id: int, data: CentreTestCreate, db: Session = Depends(get_db)):
    if db.get(DiagnosticCentre, centre_id) is None:
        raise HTTPException(404, "Diagnostic centre not found")
    test = db.get(DiagnosticTest, data.test_id)
    if test is None:
        raise HTTPException(404, "Diagnostic test not found")
    offer = CentreTest(centre_id=centre_id, test_id=test.id, price=data.price)
    db.add(offer)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This test is already offered by the centre")
    delete_cached_pattern("eve:centres:v1:*")
    delete_cached_pattern(f"eve:centre:v1:{centre_id}")
    return TestOut(id=test.id, name=test.name, description=test.description, price=data.price)


@router.post("/bookings/", response_model=BookingOut, status_code=201, tags=["bookings"],
             dependencies=[Depends(booking_limit)], responses={429: {"description": "Booking rate limit exceeded"}})
def create_booking(data: BookingCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    appointment = data.appointment_datetime
    if appointment.tzinfo is None:
        appointment = appointment.replace(tzinfo=timezone.utc)
    if appointment <= datetime.now(timezone.utc):
        raise HTTPException(400, "Appointment must be in the future")
    offer = db.scalar(
        select(CentreTest).where(
            CentreTest.centre_id == data.centre_id,
            CentreTest.test_id == data.test_id,
        )
    )
    if offer is None:
        if db.get(DiagnosticCentre, data.centre_id) is None:
            raise HTTPException(404, "Diagnostic centre not found")
        if db.get(DiagnosticTest, data.test_id) is None:
            raise HTTPException(404, "Diagnostic test not found")
        raise HTTPException(400, "Diagnostic test is not offered by this centre")
    booking = Booking(
        user_id=user.id,
        centre_id=data.centre_id,
        test_id=data.test_id,
        appointment_datetime=appointment,
        amount=offer.price,
        status="PENDING",
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    logger.info("booking_created", extra={"event": "booking_created", "booking_id": booking.id, "user_id": user.id})
    return booking


def _owned_booking(booking_id: int, user: User, db: Session) -> Booking:
    booking = db.scalar(
        select(Booking)
        .where(Booking.id == booking_id, Booking.user_id == user.id)
        .with_for_update()
    )
    if booking is None:
        raise HTTPException(404, "Booking not found")
    return booking


@router.get("/bookings/", response_model=Page[BookingOut], tags=["bookings"],
            summary="List my bookings", description="Returns only bookings owned by the authenticated user, with pagination.")
def list_bookings(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    query = select(Booking).where(Booking.user_id == user.id).order_by(Booking.created_at.desc())
    total = db.scalar(select(func.count()).select_from(Booking).where(Booking.user_id == user.id)) or 0
    items = db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
    return Page(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=ceil(total / page_size) if total else 0,
    )


@router.get("/bookings/{booking_id}", response_model=BookingOut, tags=["bookings"])
def get_booking(booking_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _owned_booking(booking_id, user, db)


@router.post("/bookings/{booking_id}/cancel", response_model=BookingOut, tags=["bookings"])
def cancel_booking(booking_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    booking = _owned_booking(booking_id, user, db)
    try:
        transition_booking(booking, "CANCELLED")
    except InvalidBookingTransition as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    db.refresh(booking)
    return booking


@router.post("/payments/", response_model=PaymentOut, tags=["payments"],
             dependencies=[Depends(payment_limit)], responses={429: {"description": "Payment rate limit exceeded"}})
def create_payment(data: PaymentCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    booking = _owned_booking(data.booking_id, user, db)
    if booking.status != "PENDING":
        raise HTTPException(409, f"Booking in {booking.status} state cannot be paid")
    if booking.payments:
        raise HTTPException(409, "A payment has already been created for this booking")
    payment_status = "SUCCESS" if settings.payment_success else "FAILED"
    payment = Payment(
        booking_id=booking.id,
        amount=booking.amount,
        status=payment_status,
        provider_payment_id=f"pay_{uuid.uuid4().hex}",
    )
    transition_booking(booking, "CONFIRMED" if payment_status == "SUCCESS" else "FAILED")
    db.add(payment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A payment has already been created for this booking")
    db.refresh(payment)
    logger.info("payment_processed", extra={
        "event": "payment_processed", "payment_id": payment.id,
        "provider_payment_id": payment.provider_payment_id, "booking_id": payment.booking_id,
    })
    return PaymentOut(payment_id=payment.id, booking_id=payment.booking_id, amount=payment.amount,
                      status=payment.status, provider_payment_id=payment.provider_payment_id)


@router.post("/payments/webhook/", response_model=WebhookOut, tags=["payments"], dependencies=[Depends(webhook_limit)],
             summary="Process payment webhook", description="Idempotently records an event. Retry 503 responses with the same event_id.",
             responses={429: {"description": "Webhook rate limit exceeded"},
                        503: {"description": "Temporary database failure; retry with the same event_id"}})
def payment_webhook(data: WebhookIn, db: Session = Depends(get_db)):
    if data.status not in {"SUCCESS", "FAILED"}:
        raise HTTPException(422, "status must be SUCCESS or FAILED")
    expected_type = "payment.success" if data.status == "SUCCESS" else "payment.failed"
    if data.event_type != expected_type:
        raise HTTPException(422, "event_type does not match payment status")
    payload = data.model_dump(mode="json")
    is_duplicate = False
    try:
        if db.scalar(select(Payment.id).where(Payment.provider_payment_id == data.payment_id)) is None:
            raise HTTPException(404, "Payment not found")
        existing = None
        event = WebhookEvent(
            event_id=data.event_id,
            event_type=data.event_type,
            payment_id=data.payment_id,
            payload=payload,
            processing_status="RECEIVED",
        )
        db.add(event)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            existing = db.scalar(select(WebhookEvent).where(WebhookEvent.event_id == data.event_id))
            if existing:
                is_duplicate = True
                if existing.payload != payload:
                    raise HTTPException(409, "event_id was already used with a different payload")
                if existing.processing_status == "PROCESSED":
                    logger.info("webhook_duplicate", extra={"event": "webhook_duplicate", "event_id": data.event_id})
                    return WebhookOut(duplicate=True, processing_status="PROCESSED")
                event = existing
            else:
                raise HTTPException(409, "Webhook event conflicts with existing data")
        if existing is None:
            db.commit()
        try:
                process_payment_webhook.delay(data.event_id)
        except BrokerOperationalError as exc:
            logger.exception("webhook_enqueue_failed", extra={"event": "webhook_enqueue_failed", "event_id": data.event_id})
            raise HTTPException(status_code=503, detail="Webhook queue temporarily unavailable; retry this event",
                                headers={"Retry-After": "2"}) from exc
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("webhook_temporarily_unavailable", extra={
            "event": "webhook_temporarily_unavailable", "event_id": data.event_id,
        })
        raise HTTPException(
            status_code=503,
            detail="Webhook processing temporarily unavailable; retry this event",
            headers={"Retry-After": "2"},
        ) from exc
    logger.info("webhook_queued", extra={
        "event": "webhook_queued", "event_id": data.event_id,
        "provider_payment_id": data.payment_id, "status_code": 200,
    })
    return WebhookOut(duplicate=is_duplicate, processing_status="RECEIVED")
