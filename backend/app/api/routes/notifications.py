"""Notification REST endpoints (polling-based delivery)."""
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Path, status
from pydantic import BaseModel, Field
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep
from app.models.enums import NotificationType
from app.models.notification import Notification

router = APIRouter()


# ── Response schemas ─────────────────────────────────────────────────────────

class NotificationItem(BaseModel):
    id: UUID = Field(..., description="The unique UUID identifier of the notification.")
    type: NotificationType = Field(..., description="The type/category of the notification (e.g., SYSTEM, COACHING, CRITICAL).")
    title: str = Field(..., description="The brief title summary of the notification.")
    body: Optional[str] = Field(None, description="Detailed text body containing description/context of the notification.")
    link_url: Optional[str] = Field(None, description="Optional target navigation URL associated with the notification click event.")
    payload: Optional[dict] = Field(None, description="Structured metadata payload containing event-specific parameters.")
    is_read: bool = Field(..., description="Read status flag indicating whether the notification has been seen by the user.")
    read_at: Optional[datetime] = Field(None, description="Timestamp when the notification was marked read, or null.")
    created_at: datetime = Field(..., description="Timestamp when the notification was created.")


class UnreadCountResponse(BaseModel):
    unread: int = Field(..., description="The count of unread notifications for the authenticated user.")


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=List[NotificationItem], responses={401: {"description": "Not authenticated"}, 403: {"description": "Credentials invalid"}, 422: {"description": "Validation error on query parameters"}})
async def list_notifications(
    session: SessionDep,
    current_user: CurrentUser,
    unread: bool = Query(False, description="Filter to unread notifications only."),
    limit: int = Query(50, ge=1, le=200, description="The maximum number of notifications to return."),
    offset: int = Query(0, ge=0, description="The offset pagination count."),
):
    """
    Retrieve a paginated list of notifications for the authenticated user.
    """
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


@router.get("/unread-count", response_model=UnreadCountResponse, responses={401: {"description": "Not authenticated"}, 403: {"description": "Credentials invalid"}})
async def unread_count(session: SessionDep, current_user: CurrentUser):
    """
    Get the total count of unread notifications for the authenticated user.
    """
    stmt = (
        select(func.count(Notification.id))
        .where(Notification.recipient_user_id == current_user.id)
        .where(Notification.is_read.is_(False))
    )
    result = await session.exec(stmt)
    count = result.one() or 0
    return UnreadCountResponse(unread=int(count))


@router.post("/{notification_id}/read", status_code=status.HTTP_200_OK, responses={401: {"description": "Not authenticated"}, 403: {"description": "Access denied/Not recipient"}, 404: {"description": "Notification not found"}, 422: {"description": "Invalid UUID format"}})
async def mark_read(
    session: SessionDep,
    current_user: CurrentUser,
    notification_id: UUID = Path(..., description="The unique UUID of the notification to mark as read."),
):
    """
    Mark a specific notification as read.
    Validates that the notification belongs to the calling user.
    """
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


@router.post("/read-all", status_code=status.HTTP_200_OK, responses={401: {"description": "Not authenticated"}, 403: {"description": "Credentials invalid"}})
async def mark_all_read(session: SessionDep, current_user: CurrentUser):
    """
    Mark all unread notifications for the authenticated user as read.
    """
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
