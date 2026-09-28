"""Track asynchronous webhook processing state."""
from alembic import op
import sqlalchemy as sa

revision = "0002_async_webhook"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "webhook_events",
        sa.Column("processing_status", sa.String(20), nullable=False, server_default="RECEIVED"),
    )
    op.execute(sa.text("UPDATE webhook_events SET processing_status = 'PROCESSED' WHERE processed_at IS NOT NULL"))
    with op.batch_alter_table("webhook_events") as batch_op:
        batch_op.alter_column("processed_at", existing_type=sa.DateTime(timezone=True), nullable=True)
        batch_op.create_check_constraint(
            "ck_webhook_processing_status",
            "processing_status IN ('RECEIVED', 'PROCESSING', 'PROCESSED', 'FAILED')",
        )
    op.create_index("ix_webhook_events_processing_status", "webhook_events", ["processing_status"])


def downgrade():
    op.drop_index("ix_webhook_events_processing_status", table_name="webhook_events")
    with op.batch_alter_table("webhook_events") as batch_op:
        batch_op.drop_constraint("ck_webhook_processing_status", type_="check")
        batch_op.drop_column("processing_status")
        batch_op.alter_column("processed_at", existing_type=sa.DateTime(timezone=True), nullable=False)
