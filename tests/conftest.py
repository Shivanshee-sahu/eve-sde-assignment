import os

os.environ["DATABASE_URL"] = "sqlite:///./test_eve.db"
os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes-long"
os.environ["PAYMENT_SUCCESS"] = "true"
os.environ["REDIS_URL"] = ""
os.environ["CELERY_BROKER_URL"] = "memory://"
os.environ["CELERY_RESULT_BACKEND"] = "cache+memory://"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.rate_limit import reset_rate_limits
from app.main import app

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def client(monkeypatch):
    from app.api.routes import process_payment_webhook

    reset_rate_limits()
    monkeypatch.setattr(process_payment_webhook, "delay", lambda event_id: None)
    Base.metadata.create_all(engine)

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    reset_rate_limits()
    Base.metadata.drop_all(engine)


@pytest.fixture()
def user(client):
    response = client.post("/auth/signup", json={"name": "Alice", "email": "alice@example.com", "password": "securepass123"})
    assert response.status_code == 201
    token = client.post("/auth/login", json={"email": "alice@example.com", "password": "securepass123"}).json()["access_token"]
    return {"id": response.json()["id"], "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture()
def seeded(client, user):
    from decimal import Decimal
    from app.models import CentreTest, DiagnosticCentre, DiagnosticTest
    db = TestingSession()
    centre = DiagnosticCentre(name="EVE", location="Dhanbad")
    other_centre = DiagnosticCentre(name="EVE Annex", location="Bokaro")
    test = DiagnosticTest(name="CBC", description="Blood count")
    db.add_all([centre, other_centre, test])
    db.flush()
    db.add(CentreTest(centre_id=centre.id, test_id=test.id, price=Decimal("450.00")))
    db.commit()
    ids = (centre.id, test.id, other_centre.id)
    db.close()
    return ids
