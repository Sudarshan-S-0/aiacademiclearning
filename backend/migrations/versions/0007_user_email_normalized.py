"""Enforce case-insensitive normalized email uniqueness.

Revision ID: 0007_user_email_normalized
Revises: 0006_topic_name_unique
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_user_email_normalized"
down_revision: Union[str, None] = "0006_topic_name_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    duplicate = bind.execute(sa.text(
        """
        SELECT lower(trim(email)) AS normalized_email, COUNT(*) AS row_count
        FROM users
        GROUP BY lower(trim(email))
        HAVING COUNT(*) > 1
        LIMIT 1
        """
    )).first()
    if duplicate:
        raise RuntimeError(
            "Cannot enforce normalized email uniqueness: "
            f"email={duplicate.normalized_email}, count={duplicate.row_count}. "
            "Reconcile duplicate accounts before retrying migration 0007."
        )

    op.create_index(
        "uq_users_email_normalized",
        "users",
        [sa.text("lower(trim(email))")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_users_email_normalized", table_name="users")
