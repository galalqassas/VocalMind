"""Notification REST endpoints (polling-based delivery)."""
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep
from app.models.enums import NotificationType
from app.models.notification import Notification

router = APIRouter()


# ── Response schemas ─────────────────────────────────────────────────────────

class NotificationItem(BaseModel):
    id: UUID
    type: NotificationType
    title: str
    body: Optional[str]
    link_url: Optional[str]
    payload: Optional[dict]
    is_read: bool
    read_at: Optional[datetime]
    created_at: datetime


class UnreadCountResponse(BaseModel):
    unread: int


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=List[NotificationItem])
async def list_notifications(
    session: SessionDep,
    current_user: CurrentUser,
    unread: bool = Query(False, description="Filter to unread only"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    stmt = (
        select(Notification)
        .where(Notification.recipient_user_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if unread:
        stmt = stmt.where(Notification.is_read.is_(False))

    result = await session.exec(stmt)
    rows = result.all()
    return [
        NotificationItem(
            id=n.id,
            type=n.type,
            title=n.title,
            body=n.body,
            link_url=n.link_url,
            payload=n.payload,
            is_read=n.is_read,
            read_at=n.read_at,
            created_at=n.created_at,
        )
        for n in rows
    ]


@router.get("/unread-count", response_model=UnreadCountResponse)
async def unread_count(session: SessionDep, current_user: CurrentUser):
    stmt = (
        select(func.count(Notification.id))
        .where(Notification.recipient_user_id == current_user.id)
        .where(Notification.is_read.is_(False))
    )
    result = await session.exec(stmt)
    count = result.one() or 0
    return UnreadCountResponse(unread=int(count))


@router.post("/{notification_id}/read", status_code=status.HTTP_200_OK)
async def mark_read(
    notification_id: UUID,
    session: SessionDep,
    current_user: CurrentUser,
):
    stmt = select(Notification).where(Notification.id == notification_id)
    result = await session.exec(stmt)
    notification = result.first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    if notification.recipient_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your notification")

    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.add(notification)
        await session.commit()

    return {"id": str(notification_id), "is_read": True}


@router.post("/read-all", status_code=status.HTTP_200_OK)
async def mark_all_read(session: SessionDep, current_user: CurrentUser):
    stmt = (
        select(Notification)
        .where(Notification.recipient_user_id == current_user.id)
        .where(Notification.is_read.is_(False))
    )
    result = await session.exec(stmt)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    touched = 0
    for n in result.all():
        n.is_read = True
        n.read_at = now
        session.add(n)
        touched += 1
    await session.commit()
    return {"updated": touched}
