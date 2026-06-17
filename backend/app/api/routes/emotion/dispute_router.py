"""Agent-side emotion event dispute endpoints.

Mirrors ``api/routes/compliance_disputes.py`` for consistency — both speak
SQLModel + the project's JWT auth, both fan out a notification to managers
on flag and to the originating agent on retract.

Workflow:
  1. Agent sees their emotion events on the agent call detail page.
  2. Agent clicks "Dispute" → ``POST /interactions/emotion-events/{id}/dispute``.
  3. is_flagged = TRUE, agent_flagged_by/at/note populated.
  4. Notification fan-out to every manager in the agent's org.
  5. Manager sees the flag in ``GET /reviews/queue`` and accepts/rejects via
     ``POST /reviews/emotion/{id}``.
  6. Either side can retract via DELETE on the same URL.

The pre-v5.3 Supabase-client implementation has been retired — the new
``/reviews/queue`` endpoint covers the manager-side read, so the old
``GET /emotion-events/flagged`` endpoint is gone.
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.core.notification_service import emit_to_managers
from app.models.emotion_event import EmotionEvent
from app.models.enums import NotificationType, UserRole
from app.models.interaction import Interaction

router = APIRouter(prefix="/emotion-events", tags=["emotion-events"])


class DisputeRequest(BaseModel):
    agent_flag_note: Optional[str] = None  # free-text "why I think this is wrong"


class DisputeResponse(BaseModel):
    event_id: UUID
    is_flagged: bool
    agent_flagged_at: datetime
    message: str


@router.post(
    "/{event_id}/dispute",
    response_model=DisputeResponse,
    summary="Agent disputes an emotion event",
)
async def dispute_emotion_event(
    event_id: UUID,
    body: DisputeRequest,
    session: SessionDep,
    current_user: CurrentUser,
):
    if current_user.role != UserRole.agent:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only agents can dispute emotion events.",
        )

    event = (await session.exec(
        select(EmotionEvent).where(EmotionEvent.id == event_id)
    )).first()
    if not event:
        raise HTTPException(status_code=404, detail="Emotion event not found")

    interaction = (await session.exec(
        select(Interaction).where(Interaction.id == event.interaction_id)
    )).first()
    if not interaction:
        raise HTTPException(status_code=404, detail="Parent interaction not found")
    if interaction.agent_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You can only dispute emotion events on your own calls.",
        )

    now = datetime.now(timezone.utc)
    event.is_flagged = True
    event.agent_flagged_by = current_user.id
    event.agent_flagged_at = now
    event.agent_flag_note = body.agent_flag_note
    session.add(event)

    await emit_to_managers(
        session,
        organization_id=current_user.organization_id,
        type=NotificationType.agent_flag_pending,
        title=f"{current_user.name} flagged an emotion event",
        body=body.agent_flag_note,
        link_url="/manager/reviews",
        payload={
            "interaction_id": str(event.interaction_id),
            "event_id": str(event.id),
            "kind": "emotion",
        },
    )

    await session.commit()
    return DisputeResponse(
        event_id=event_id,
        is_flagged=True,
        agent_flagged_at=now,
        message="Event disputed. A manager will review it shortly.",
    )


@router.delete(
    "/{event_id}/dispute",
    summary="Agent or manager retracts an emotion dispute",
)
async def retract_dispute(
    event_id: UUID,
    session: SessionDep,
    current_user: CurrentUser,
):
    event = (await session.exec(
        select(EmotionEvent).where(EmotionEvent.id == event_id)
    )).first()
    if not event:
        raise HTTPException(status_code=404, detail="Emotion event not found")

    # Agent can only retract their own flag; manager can clear any flag in their org.
    if current_user.role == UserRole.agent:
        if event.agent_flagged_by != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="You can only retract disputes you submitted.",
            )
    else:
        interaction = (await session.exec(
            select(Interaction).where(Interaction.id == event.interaction_id)
        )).first()
        if not interaction or interaction.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=403, detail="Cross-organization access denied"
            )

    event.is_flagged = False
    event.agent_flagged_by = None
    event.agent_flagged_at = None
    event.agent_flag_note = None
    session.add(event)
    await session.commit()
    return {"event_id": str(event_id), "message": "Dispute retracted."}
