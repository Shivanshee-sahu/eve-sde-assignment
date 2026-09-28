from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import CentreTest, DiagnosticCentre, DiagnosticTest


def seed():
    with SessionLocal() as db:
        centre = db.scalar(select(DiagnosticCentre).where(DiagnosticCentre.name == "EVE Diagnostics"))
        if centre is None:
            centre = DiagnosticCentre(name="EVE Diagnostics", location="Dhanbad")
            db.add(centre)
            db.flush()
        tests = [("CBC", "Complete blood count", "450.00"), ("Lipid Profile", "Cholesterol screening", "700.00"),
                 ("Thyroid Profile", "Thyroid hormone panel", "600.00"), ("Blood Sugar", "Fasting blood glucose", "250.00")]
        for name, description, price in tests:
            test = db.scalar(select(DiagnosticTest).where(DiagnosticTest.name == name))
            if test is None:
                test = DiagnosticTest(name=name, description=description)
                db.add(test)
                db.flush()
            offer = db.scalar(select(CentreTest).where(CentreTest.centre_id == centre.id, CentreTest.test_id == test.id))
            if offer is None:
                db.add(CentreTest(centre_id=centre.id, test_id=test.id, price=Decimal(price)))
        db.commit()
    print("Sample diagnostic data is ready.")


if __name__ == "__main__":
    seed()
