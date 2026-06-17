"""In-app notification record.

Phase 1 delivery is via polling: the frontend hits /notifications periodically
to fetch unread items. Realtime (SSE/WS) is a Phase 2 upgrade — the table
shape doesn't change.
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import JSON, Enum as SAEnum
from sqlmodel import Column, Field, SQLModel
from sqlalchemy.dialects.postgresql import JSONB

from app.models.enums import NotificationType


class Notification(SQLModel, table=True):
    __tablename__ = "notifications"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    recipient_user_id: UUID = Field(foreign_key="users.id", index=True)
    organization_id: UUID = Field(foreign_key="organizations.id", index=True)

    type: NotificationType = Field(
        sa_type=SAEnum(
            NotificationType,
            name="notification_type_enum",
            create_constraint=False,
            native_enum=True,
        ),
    )

    title: str = Field(max_length=255)
    body: Optional[str] = None
    link_url: Optional[str] = Field(default=None, max_length=512)

    # Free-form context (e.g. {"interaction_id": "...", "event_id": "..."}).
    # JSONB on Postgres (indexable), JSON-as-text on SQLite (used in unit tests).
    payload: Optional[dict] = Field(
        default=None,
        sa_column=Column(JSON().with_variant(JSONB(), "postgresql")),
    )

    is_read: bool = Field(default=False, index=True)
    read_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
