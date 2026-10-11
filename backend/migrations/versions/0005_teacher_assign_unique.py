"""Enforce null-safe normalized teacher assignment uniqueness.

Revision ID: 0005_teacher_assign_unique
Revises: 0004_acad_structure_unique
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_teacher_assign_unique"
down_revision: Union[str, None] = "0004_acad_structure_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    duplicate = bind.execute(sa.text(
        """
        SELECT teacher_id, subject_id, COALESCE(section_id, 0) AS normalized_section,
               lower(trim(academic_year)) AS normalized_year, COUNT(*) AS row_count
        FROM teacher_subject_assignments
        GROUP BY teacher_id, subject_id, COALESCE(section_id, 0), lower(trim(academic_year))
        HAVING COUNT(*) > 1
        LIMIT 1
        """
    )).first()
    if duplicate:
        raise RuntimeError(
            "Cannot enforce unique teacher assignments: "
            f"teacher_id={duplicate.teacher_id}, subject_id={duplicate.subject_id}, "
            f"section_id={duplicate.normalized_section}, academic_year={duplicate.normalized_year}, "
            f"count={duplicate.row_count}. Reconcile duplicates before retrying migration 0005."
        )

    duplicate_enrollment = bind.execute(sa.text(
        """
        SELECT student_id, subject_id, lower(trim(academic_year)) AS normalized_year,
               COUNT(*) AS row_count
        FROM student_enrollments
        GROUP BY student_id, subject_id, lower(trim(academic_year))
        HAVING COUNT(*) > 1
        LIMIT 1
        """
    )).first()
    if duplicate_enrollment:
        raise RuntimeError(
            "Cannot enforce unique student enrollments: "
            f"student_id={duplicate_enrollment.student_id}, subject_id={duplicate_enrollment.subject_id}, "
            f"academic_year={duplicate_enrollment.normalized_year}, count={duplicate_enrollment.row_count}. "
            "Reconcile duplicates before retrying migration 0005."
        )

    op.create_index(
        "uq_teacher_assignment_normalized",
        "teacher_subject_assignments",
        [
            "teacher_id",
            "subject_id",
            sa.text("coalesce(section_id, 0)"),
            sa.text("lower(trim(academic_year))"),
        ],
        unique=True,
    )
    op.create_index(
        "uq_enrollment_normalized_year",
        "student_enrollments",
        ["student_id", "subject_id", sa.text("lower(trim(academic_year))")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_enrollment_normalized_year", table_name="student_enrollments")
    op.drop_index("uq_teacher_assignment_normalized", table_name="teacher_subject_assignments")
