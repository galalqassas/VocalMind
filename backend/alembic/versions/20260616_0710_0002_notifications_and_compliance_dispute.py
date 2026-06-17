"""notifications + compliance dispute columns

Revision ID: 0002_notifications_and_compliance_dispute
Revises: 0001_baseline
Create Date: 2026-06-16 07:10:00 UTC

Adds the schema for the in-app notification system and the agent-dispute
parity columns on ``policy_compliance`` (the v5.2 dispute fields already
exist on ``emotion_events``).

Concretely:
  * new enum ``notification_type_enum``
  * new table ``notifications``
  * 4 new columns on ``policy_compliance``:
      ``is_flagged``, ``agent_flagged_by``, ``agent_flagged_at``,
      ``agent_flag_note`` (plus a CHECK constraint and a partial index)

The ``IF NOT EXISTS`` clauses make the migration safe to re-run against
a DB that was hand-patched out-of-band before Alembic was adopted.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002_notifications_and_compliance_dispute"
down_revision: Union[str, Sequence[str], None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NOTIFICATION_TYPES = (
    "evaluation_complete",
    "agent_flag_pending",
    "flag_approved",
    "flag_rejected",
    "manager_correction",
    "feedback_applied",
)


def upgrade() -> None:
    # ── notification_type_enum ─────────────────────────────────────────
    notification_type = postgresql.ENUM(
        *NOTIFICATION_TYPES,
        name="notification_type_enum",
        create_type=False,
    )
    # PostgreSQL: DO block makes the type create idempotent across re-runs.
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE notification_type_enum AS ENUM (
                'evaluation_complete', 'agent_flag_pending',
                'flag_approved', 'flag_rejected',
                'manager_correction', 'feedback_applied'
            );
        EXCEPTION WHEN duplicate_object THEN
            NULL;
        END $$;
        """
    )

    # ── notifications table ────────────────────────────────────────────
    op.create_table(
        "notifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "recipient_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("type", notification_type, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("link_url", sa.String(length=512), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "is_read",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            index=True,
        ),
        sa.Column("read_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        if_not_exists=True,
    )
    op.create_index(
        "idx_notifications_recipient_unread",
        "notifications",
        ["recipient_user_id", "is_read"],
        if_not_exists=True,
    )
    op.create_index(
        "idx_notifications_created_at",
        "notifications",
        [sa.text("created_at DESC")],
        if_not_exists=True,
    )

    # ── policy_compliance: agent-dispute parity columns ────────────────
    with op.batch_alter_table("policy_compliance") as batch:
        batch.add_column(
            sa.Column(
                "is_flagged",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
        batch.add_column(
            sa.Column(
                "agent_flagged_by",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column("agent_flagged_at", sa.TIMESTAMP(timezone=True), nullable=True)
        )
        batch.add_column(sa.Column("agent_flag_note", sa.Text(), nullable=True))

    op.create_index(
        "idx_policy_compliance_agent_flagged",
        "policy_compliance",
        ["agent_flagged_by"],
        postgresql_where=sa.text("agent_flagged_by IS NOT NULL"),
        if_not_exists=True,
    )

    op.create_check_constraint(
        "policy_compliance_agent_flag_consistency",
        "policy_compliance",
        "(agent_flagged_by IS NULL AND agent_flagged_at IS NULL)"
        " OR (agent_flagged_by IS NOT NULL AND agent_flagged_at IS NOT NULL"
        " AND is_flagged = TRUE)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "policy_compliance_agent_flag_consistency",
        "policy_compliance",
        type_="check",
    )
    op.drop_index(
        "idx_policy_compliance_agent_flagged",
        table_name="policy_compliance",
        if_exists=True,
    )
    with op.batch_alter_table("policy_compliance") as batch:
        batch.drop_column("agent_flag_note")
        batch.drop_column("agent_flagged_at")
        batch.drop_column("agent_flagged_by")
        batch.drop_column("is_flagged")

    op.drop_index(
        "idx_notifications_created_at", table_name="notifications", if_exists=True
    )
    op.drop_index(
        "idx_notifications_recipient_unread", table_name="notifications", if_exists=True
    )
    op.drop_table("notifications", if_exists=True)

    op.execute("DROP TYPE IF EXISTS notification_type_enum")
