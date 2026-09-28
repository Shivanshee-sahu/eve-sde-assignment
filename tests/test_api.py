from datetime import datetime, timedelta, timezone


def test_auth_signup_duplicate_login_and_invalid_password(client):
    data = {"name": "A", "email": "a@example.com", "password": "password123"}
    assert client.post("/auth/signup", json=data).status_code == 201
    assert client.post("/auth/signup", json=data).status_code == 409
    assert client.post("/auth/login", json={"email": data["email"], "password": data["password"]}).status_code == 200
    assert client.post("/auth/login", json={"email": data["email"], "password": "wrongpassword"}).status_code == 401


def test_booking_pricing_ownership_cancel_and_payment(client, user, seeded):
    centre, test, _ = seeded
    appointment = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    payload = {"centre_id": centre, "test_id": test, "appointment_datetime": appointment}
    assert client.post("/bookings/", json=payload).status_code == 401
    assert client.post("/bookings/", json={**payload, "amount": 1}, headers=user["headers"]).status_code == 422
    created = client.post("/bookings/", json=payload, headers=user["headers"])
    assert created.status_code == 201
    booking = created.json()
    assert booking["amount"] == "450.00" and booking["status"] == "PENDING"
    assert client.get(f"/bookings/{booking['id']}", headers=user["headers"]).status_code == 200
    listed = client.get("/bookings/?page=1&page_size=10", headers=user["headers"]).json()
    assert listed["total"] == 1 and listed["items"][0]["id"] == booking["id"]
    assert client.post("/payments/", json={"booking_id": booking["id"]}, headers=user["headers"]).json()["status"] == "SUCCESS"
    assert client.get(f"/bookings/{booking['id']}", headers=user["headers"]).json()["status"] == "CONFIRMED"
    assert client.post("/payments/", json={"booking_id": booking["id"]}, headers=user["headers"]).status_code == 409
    assert client.post("/payments/", json={"booking_id": 99999}, headers=user["headers"]).status_code == 404


def test_booking_validation_authorization_and_cancel(client, user, seeded):
    centre, test, other_centre = seeded
    appointment = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    assert client.post("/bookings/", json={"centre_id": 999, "test_id": test, "appointment_datetime": appointment}, headers=user["headers"]).status_code == 404
    assert client.post("/bookings/", json={"centre_id": centre, "test_id": 999, "appointment_datetime": appointment}, headers=user["headers"]).status_code == 404
    assert client.post("/bookings/", json={"centre_id": other_centre, "test_id": test,
                       "appointment_datetime": appointment}, headers=user["headers"]).status_code == 400
    assert client.post("/bookings/", json={"centre_id": centre, "test_id": test, "appointment_datetime": (datetime.now(timezone.utc)-timedelta(days=1)).isoformat()}, headers=user["headers"]).status_code == 400
    b = client.post("/bookings/", json={"centre_id": centre, "test_id": test, "appointment_datetime": appointment}, headers=user["headers"]).json()
    other = client.post("/auth/signup", json={"name": "B", "email": "b@example.com", "password": "password123"})
    token = client.post("/auth/login", json={"email": "b@example.com", "password": "password123"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get(f"/bookings/{b['id']}", headers=headers).status_code == 404
    assert client.post("/payments/", json={"booking_id": b["id"]}, headers=headers).status_code == 404
    assert client.post(f"/bookings/{b['id']}/cancel", headers=user["headers"]).json()["status"] == "CANCELLED"
    assert client.post("/payments/", json={"booking_id": b["id"]}, headers=user["headers"]).status_code == 409


def test_failed_payment_marks_booking_failed(client, user, seeded, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "payment_success", False)
    centre, test, _ = seeded
    appointment = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    booking = client.post("/bookings/", json={"centre_id": centre, "test_id": test,
                              "appointment_datetime": appointment}, headers=user["headers"]).json()
    payment = client.post("/payments/", json={"booking_id": booking["id"]}, headers=user["headers"])
    assert payment.status_code == 200
    assert payment.json()["status"] == "FAILED"
    assert client.get(f"/bookings/{booking['id']}", headers=user["headers"]).json()["status"] == "FAILED"
    assert client.post("/payments/", json={"booking_id": booking["id"]}, headers=user["headers"]).status_code == 409


def test_webhook_idempotency_and_state_safety(client, user, seeded):
    centre, test, _ = seeded
    appointment = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    b = client.post("/bookings/", json={"centre_id": centre, "test_id": test, "appointment_datetime": appointment}, headers=user["headers"]).json()
    payment = client.post("/payments/", json={"booking_id": b["id"]}, headers=user["headers"]).json()
    event = {"event_id": "evt_1", "event_type": "payment.success", "payment_id": payment["provider_payment_id"], "status": "SUCCESS"}
    assert client.post("/payments/webhook/", json=event).json()["duplicate"] is False
    assert client.post("/payments/webhook/", json=event).json()["duplicate"] is True
    assert client.get(f"/bookings/{b['id']}", headers=user["headers"]).json()["status"] == "CONFIRMED"
    event2 = {"event_id": "evt_2", "event_type": "payment.failed", "payment_id": payment["provider_payment_id"], "status": "FAILED"}
    assert client.post("/payments/webhook/", json=event2).status_code == 200
    assert client.get(f"/bookings/{b['id']}", headers=user["headers"]).json()["status"] == "CONFIRMED"
    assert client.post("/payments/webhook/", json={**event, "event_id": "evt_unknown", "payment_id": "missing"}).status_code == 404


def test_webhook_can_be_retried_after_transient_database_error(client, user, seeded, monkeypatch):
    from sqlalchemy.orm import Session
    from sqlalchemy.exc import OperationalError

    centre, test, _ = seeded
    appointment = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    booking = client.post("/bookings/", json={"centre_id": centre, "test_id": test,
                                "appointment_datetime": appointment}, headers=user["headers"]).json()
    payment = client.post("/payments/", json={"booking_id": booking["id"]}, headers=user["headers"]).json()
    event = {"event_id": "evt_retry", "event_type": "payment.success",
             "payment_id": payment["provider_payment_id"], "status": "SUCCESS"}

    original_commit = Session.commit
    fail_once = True

    def transient_failure(session):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise OperationalError("COMMIT", {}, RuntimeError("temporary database failure"))
        return original_commit(session)

    monkeypatch.setattr(Session, "commit", transient_failure)
    failed = client.post("/payments/webhook/", json=event)
    assert failed.status_code == 503
    assert failed.headers["Retry-After"] == "2"

    monkeypatch.setattr(Session, "commit", original_commit)
    retried = client.post("/payments/webhook/", json=event)
    assert retried.status_code == 200
    assert retried.json()["duplicate"] is False
    assert client.post("/payments/webhook/", json=event).json()["duplicate"] is True


def test_centre_and_tests_catalog(client, seeded):
    centre, test, _ = seeded
    assert client.get(f"/centres/{centre}").json()["tests"][0]["id"] == test
    centres = client.get("/centres/?page=1&page_size=1").json()
    assert centres["total"] == 2 and centres["page_size"] == 1
    assert centres["items"][0]["id"] == centre
    tests = client.get("/tests/?page=1&page_size=1").json()
    assert tests["total"] == 1 and tests["items"][0]["id"] == test
    assert client.get("/tests/?page=0").status_code == 422


def test_admin_can_manage_catalogue_with_configured_key(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "admin_api_key", None)
    assert client.post("/centres/", json={"name": "Admin Centre", "location": "Dhanbad"}).status_code == 503
    monkeypatch.setattr(settings, "admin_api_key", "test-admin-secret")
    headers = {"X-Admin-Key": "test-admin-secret"}
    assert client.post("/centres/", json={"name": "Admin Centre", "location": "Dhanbad"},
                       headers={"X-Admin-Key": "wrong"}).status_code == 403
    centre = client.post("/centres/", json={"name": "Admin Centre", "location": "Dhanbad"}, headers=headers)
    assert centre.status_code == 201
    test = client.post("/tests/", json={"name": "Admin CBC", "description": "Sample"}, headers=headers)
    assert test.status_code == 201
    assert client.post("/tests/", json={"name": "Admin CBC", "description": "Duplicate"},
                       headers=headers).status_code == 409
    offering = client.post(f"/centres/{centre.json()['id']}/tests",
                           json={"test_id": test.json()["id"], "price": "399.00"}, headers=headers)
    assert offering.status_code == 201 and offering.json()["price"] == "399.00"
    assert client.get(f"/centres/{centre.json()['id']}").json()["tests"][0]["price"] == "399.00"
    assert client.post(f"/centres/{centre.json()['id']}/tests",
                       json={"test_id": test.json()["id"], "price": "400.00"}, headers=headers).status_code == 409

