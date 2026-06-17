"""baseline pre-alembic

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-16 07:00:00 UTC

Empty baseline marker. The pre-Alembic schema is defined in
``infra/db/01_schema.sql`` and is assumed to be already applied to any
database that gets stamped at this revision.

For a brand-new DB the recommended order is:

    psql ... < infra/db/01_schema.sql      # bootstrap the existing schema
    uv run alembic stamp 0001_baseline     # mark it as up-to-date
    uv run alembic upgrade head            # apply 0002+ (the new stuff)

Future schema changes are added as new revisions on top of this one.
"""
from __future__ import annotations

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Intentionally empty — see module docstring.
    pass


def downgrade() -> None:
    # Cannot meaningfully roll back the pre-Alembic baseline.
    pass
