"""Prevent duplicate active document deletion jobs.

Revision ID: d14e6a9c2b31
Revises: b7c3e1d8f642
"""

from alembic import op
import sqlalchemy as sa


revision = "d14e6a9c2b31"
down_revision = "b7c3e1d8f642"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY document_id
                       ORDER BY created_at, id
                   ) AS position
            FROM ingestion_jobs
            WHERE job_type = 'DELETE_FROM_INDEX'
              AND state IN (
                  'PENDING', 'IN_PROGRESS', 'FAILED_RETRYABLE', 'RUNNING', 'RETRY'
              )
        )
        UPDATE ingestion_jobs
        SET state = 'CANCELLED',
            completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
            error_code = 'DUPLICATE_DELETE_JOB',
            safe_error_message = 'A duplicate document deletion job was cancelled.'
        WHERE id IN (SELECT id FROM ranked WHERE position > 1)
        """
    )
    op.create_index(
        "uq_ingestion_jobs_active_document_delete",
        "ingestion_jobs",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text(
            "job_type = 'DELETE_FROM_INDEX' AND state IN "
            "('PENDING','IN_PROGRESS','FAILED_RETRYABLE','RUNNING','RETRY')"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_ingestion_jobs_active_document_delete",
        table_name="ingestion_jobs",
    )
