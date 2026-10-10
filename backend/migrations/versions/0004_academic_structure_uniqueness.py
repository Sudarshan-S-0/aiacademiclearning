"""Enforce normalized semester and section uniqueness.

Revision ID: 0004_acad_structure_unique
Revises: 0003_subject_semester_code
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_acad_structure_unique"
down_revision: Union[str, None] = "0003_subject_semester_code"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    duplicate_semester = bind.execute(sa.text(
        """
        SELECT department_id, lower(trim(academic_year)) AS normalized_year,
               semester_number, COUNT(*) AS row_count
        FROM semesters
        GROUP BY department_id, lower(trim(academic_year)), semester_number
        HAVING COUNT(*) > 1
        LIMIT 1
        """
    )).first()
    if duplicate_semester:
        raise RuntimeError(
            "Cannot enforce unique semester records: "
            f"department_id={duplicate_semester.department_id}, "
            f"academic_year={duplicate_semester.normalized_year}, "
            f"semester_number={duplicate_semester.semester_number}, "
            f"count={duplicate_semester.row_count}. Reconcile duplicates before retrying migration 0004."
        )

    duplicate_section = bind.execute(sa.text(
        """
        SELECT semester_id, lower(trim(name)) AS normalized_name, COUNT(*) AS row_count
        FROM sections
        GROUP BY semester_id, lower(trim(name))
        HAVING COUNT(*) > 1
        LIMIT 1
        """
    )).first()
    if duplicate_section:
        raise RuntimeError(
            "Cannot enforce unique section names within a semester: "
            f"semester_id={duplicate_section.semester_id}, "
            f"name={duplicate_section.normalized_name}, count={duplicate_section.row_count}. "
            "Reconcile duplicates before retrying migration 0004."
        )

    op.create_index(
        "uq_semester_department_year_number",
        "semesters",
        ["department_id", sa.text("lower(trim(academic_year))"), "semester_number"],
        unique=True,
    )
    op.create_index(
        "uq_section_semester_name_normalized",
        "sections",
        ["semester_id", sa.text("lower(trim(name))")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_section_semester_name_normalized", table_name="sections")
    op.drop_index("uq_semester_department_year_number", table_name="semesters")
