"""Enforce subject code uniqueness within each semester.

Revision ID: 0003_subject_semester_code
Revises: 0002_assignment_progress_link
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_subject_semester_code"
down_revision: Union[str, None] = "0002_assignment_progress_link"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    duplicate = bind.execute(sa.text(
        """
        SELECT semester_id, lower(trim(code)) AS normalized_code, COUNT(*) AS subject_count
        FROM subjects
        GROUP BY semester_id, lower(trim(code))
        HAVING COUNT(*) > 1
        LIMIT 1
        """
    )).first()
    if duplicate:
        raise RuntimeError(
            "Cannot enforce unique subject codes within each semester: "
            f"semester_id={duplicate.semester_id}, code={duplicate.normalized_code}, "
            f"count={duplicate.subject_count}. Reconcile duplicate subject codes "
            "before retrying migration 0003."
        )
    op.create_index(
        "uq_subject_semester_code_normalized",
        "subjects",
        ["semester_id", sa.text("lower(trim(code))")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_subject_semester_code_normalized",
        table_name="subjects",
    )
