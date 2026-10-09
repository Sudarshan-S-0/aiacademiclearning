"""Initial schema baseline for the current academic LMS models.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-09

This first bootstrap revision creates the current SQLAlchemy model metadata on
an empty database. For an existing database that already has this schema, back
it up and use `alembic stamp 0001_initial_schema` after verifying the schema.
All future schema changes must be added as new, explicit Alembic revisions.
"""

from typing import Sequence, Union

from alembic import op

from app.db.session import Base
from app.models import models  # noqa: F401 - registers all model tables

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Bootstrap the schema from the current model metadata for fresh installs.
    # Keep this baseline immutable after it is adopted; subsequent changes belong
    # in new revisions generated with --autogenerate and reviewed before release.
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    # A baseline downgrade drops application tables and their data. Only run it
    # against a disposable database after taking any required backup.
    Base.metadata.drop_all(bind=op.get_bind())
