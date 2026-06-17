"""Notification service.

Single emit() entry point. Call sites are deliberately dumb — they pass a
type, recipient, and payload; the service writes the row. Realtime delivery
is Phase 2; today the frontend polls /notifications.
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.enums import NotificationType, UserRole
from app.models.notification import Notification
from app.models.user import User

logger = logging.getLogger(__name__)


async def emit(
    session: AsyncSession,
    *,
    recipient_user_id: UUID,
    organization_id: UUID,
    type: NotificationType,
    title: str,
    body: Optional[str] = None,
    link_url: Optional[str] = None,
    payload: Optional[dict] = None,
) -> Notification:
    """Persist a single notification. Caller commits."""
    notification = Notification(
        recipient_user_id=recipient_user_id,
        organization_id=organization_id,
        type=type,
        title=title,
        body=body,
        link_url=link_url,
        payload=payload,
    )
    session.add(notification)
    await session.flush()
    return notification


async def emit_to_managers(
    session: AsyncSession,
    *,
    organization_id: UUID,
    type: NotificationType,
    title: str,
    body: Optional[str] = None,
    link_url: Optional[str] = None,
    payload: Optional[dict] = None,
) -> Sequence[Notification]:
    """Fan-out: send the same notification to every manager in the org."""
    stmt = select(User).where(
        User.organization_id == organization_id,
        User.role == UserRole.manager,
        User.is_active.is_(True),
    )
    result = await session.exec(stmt)
    managers = result.all()

    if not managers:
        logger.info("emit_to_managers: no active managers in org %s", organization_id)
        return []

    out: list[Notification] = []
    for manager in managers:
        n = await emit(
            session,
            recipient_user_id=manager.id,
            organization_id=organization_id,
            type=type,
            title=title,
            body=body,
            link_url=link_url,
            payload=payload,
        )
        out.append(n)
    return out
