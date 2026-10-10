"""Link assignment progress records to their submissions.

Revision ID: 0002_assignment_progress_link
Revises: 0001_initial_schema
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_assignment_progress_link"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "student_progress",
        sa.Column("assignment_submission_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_student_progress_assignment_submission_id",
        "student_progress",
        ["assignment_submission_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_student_progress_assignment_submission_id",
        "student_progress",
        "assignment_submissions",
        ["assignment_submission_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_student_progress_assignment_submission_id",
        "student_progress",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_student_progress_assignment_submission_id",
        table_name="student_progress",
    )
    op.drop_column("student_progress", "assignment_submission_id")
