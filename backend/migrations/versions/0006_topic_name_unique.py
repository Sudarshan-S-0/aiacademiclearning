"""Enforce normalized topic names within a subject.

Revision ID: 0006_topic_name_unique
Revises: 0005_teacher_assign_unique
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_topic_name_unique"
down_revision: Union[str, None] = "0005_teacher_assign_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    duplicate = bind.execute(sa.text(
        """
        SELECT subject_id, lower(trim(topic_name)) AS normalized_name,
               COUNT(*) AS row_count
        FROM syllabus_topics
        GROUP BY subject_id, lower(trim(topic_name))
        HAVING COUNT(*) > 1
        LIMIT 1
        """
    )).first()
    if duplicate:
        raise RuntimeError(
            "Cannot enforce unique topic names within a subject: "
            f"subject_id={duplicate.subject_id}, name={duplicate.normalized_name}, "
            f"count={duplicate.row_count}. Reconcile duplicates before retrying migration 0006."
        )

    op.create_index(
        "uq_topic_subject_name_normalized",
        "syllabus_topics",
        ["subject_id", sa.text("lower(trim(topic_name))")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_topic_subject_name_normalized", table_name="syllabus_topics")
