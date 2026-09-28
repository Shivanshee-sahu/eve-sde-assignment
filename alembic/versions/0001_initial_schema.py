"""Initial normalized booking schema."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("users",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(120), nullable=False),
        sa.Column("email", sa.String(255), nullable=False), sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table("diagnostic_centres",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(160), nullable=False),
        sa.Column("location", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("diagnostic_tests",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.String(500), nullable=False), sa.UniqueConstraint("name"))
    op.create_table("centre_tests",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("centre_id", sa.Integer(), nullable=False),
        sa.Column("test_id", sa.Integer(), nullable=False), sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.ForeignKeyConstraint(["centre_id"], ["diagnostic_centres.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["test_id"], ["diagnostic_tests.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("centre_id", "test_id", name="uq_centre_test"),
        sa.CheckConstraint("price >= 0", name="ck_centre_test_price_nonnegative"))
    op.create_index("ix_centre_tests_centre_id", "centre_tests", ["centre_id"])
    op.create_index("ix_centre_tests_test_id", "centre_tests", ["test_id"])
    op.create_table("bookings",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("centre_id", sa.Integer(), nullable=False), sa.Column("test_id", sa.Integer(), nullable=False),
        sa.Column("appointment_datetime", sa.DateTime(timezone=True), nullable=False), sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["centre_id", "test_id"], ["centre_tests.centre_id", "centre_tests.test_id"], name="fk_booking_centre_test"),
        sa.CheckConstraint("amount >= 0", name="ck_booking_amount_nonnegative"),
        sa.CheckConstraint("status IN ('PENDING', 'CONFIRMED', 'FAILED', 'CANCELLED')", name="ck_booking_status"))
    op.create_index("ix_bookings_user_id", "bookings", ["user_id"])
    op.create_index("ix_bookings_status", "bookings", ["status"])
    op.create_index("ix_booking_user_created", "bookings", ["user_id", "created_at"])
    op.create_table("payments",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("provider_payment_id", sa.String(80), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("booking_id", name="uq_payment_booking"),
        sa.CheckConstraint("amount >= 0", name="ck_payment_amount_nonnegative"),
        sa.CheckConstraint("status IN ('PENDING', 'SUCCESS', 'FAILED')", name="ck_payment_status"))
    op.create_index("ix_payments_booking_id", "payments", ["booking_id"])
    op.create_index("ix_payments_provider_payment_id", "payments", ["provider_payment_id"], unique=True)
    op.create_table("webhook_events",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("event_id", sa.String(120), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False), sa.Column("payment_id", sa.String(80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        )
    op.create_index("ix_webhook_events_event_id", "webhook_events", ["event_id"], unique=True)


def downgrade():
    op.drop_table("webhook_events")
    op.drop_table("payments")
    op.drop_table("bookings")
    op.drop_table("centre_tests")
    op.drop_table("diagnostic_tests")
    op.drop_table("diagnostic_centres")
    op.drop_table("users")
