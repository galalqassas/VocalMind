"""Manager-initiated corrections (no agent flag required).

Manager sees an AI verdict in the Session Inspector, decides it's wrong, and
submits a correction directly. The feedback row is created at
FeedbackStatus.reviewed so it's immediately eligible for the training export.
The originating agent is notified.
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.models.emotion_event import EmotionEvent
from app.models.enums import FeedbackStatus, NotificationType, UserRole
from app.models.feedback import ComplianceFeedback, EmotionFeedback
from app.models.interaction import Interaction
from app.models.policy import PolicyCompliance
from app.models.utterance import Utterance
from app.core.notification_service import emit

router = APIRouter()


def _ensure_manager(current_user) -> None:
    if current_user.role != UserRole.manager:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manager-only endpoint",
        )


class EmotionCorrectionRequest(BaseModel):
    emotion_event_id: UUID
    corrected_emotion: str
    corrected_justification: Optional[str] = None
    correction_reason: Optional[str] = None


class ComplianceCorrectionRequest(BaseModel):
    policy_compliance_id: UUID
    corrected_is_compliant: bool
    corrected_score: Optional[float] = None
    correction_reason: Optional[str] = None


class CorrectionResponse(BaseModel):
    feedback_id: UUID


@router.post("/emotion", response_model=CorrectionResponse, status_code=201)
async def correct_emotion(
    body: EmotionCorrectionRequest,
    session: SessionDep,
    current_user: CurrentUser,
):
    _ensure_manager(current_user)

    event = (await session.exec(
        select(EmotionEvent).where(EmotionEvent.id == body.emotion_event_id)
    )).first()
    if not event:
        raise HTTPException(status_code=404, detail="Emotion event not found")

    interaction = (await session.exec(
        select(Interaction).where(Interaction.id == event.interaction_id)
    )).first()
    if not interaction or interaction.organization_id != current_user.organization_id:
        raise HTTPException(status_code=403, detail="Cross-organization access denied")

    corrected = (body.corrected_emotion or "").strip().lower()
    if not corrected:
        raise HTTPException(status_code=400, detail="corrected_emotion is required")

    event.new_emotion = corrected
    if body.corrected_justification:
        event.llm_justification = body.corrected_justification.strip()
    session.add(event)

    utterance = await session.get(Utterance, event.utterance_id)
    if utterance:
        utterance.emotion = corrected
        session.add(utterance)

    feedback = EmotionFeedback(
        emotion_event_id=event.id,
        provided_by_user_id=current_user.id,
        llm_justification=event.llm_justification,
        corrected_emotion=corrected,
        corrected_justification=body.corrected_justification,
        correction_reason=body.correction_reason,
        feedback_status=FeedbackStatus.reviewed,
    )
    session.add(feedback)
    await session.flush()

    await emit(
        session,
        recipient_user_id=interaction.agent_id,
        organization_id=current_user.organization_id,
        type=NotificationType.manager_correction,
        title="Manager corrected an emotion evaluation",
        body=f"Emotion updated to '{body.corrected_emotion}'.",
        link_url=f"/agent/calls/{interaction.id}",
        payload={
            "interaction_id": str(interaction.id),
            "event_id": str(event.id),
            "feedback_id": str(feedback.id),
        },
    )

    await session.commit()
    return CorrectionResponse(feedback_id=feedback.id)


@router.post("/compliance", response_model=CorrectionResponse, status_code=201)
async def correct_compliance(
    body: ComplianceCorrectionRequest,
    session: SessionDep,
    current_user: CurrentUser,
):
    _ensure_manager(current_user)

    pc = (await session.exec(
        select(PolicyCompliance).where(PolicyCompliance.id == body.policy_compliance_id)
    )).first()
    if not pc:
        raise HTTPException(status_code=404, detail="Compliance record not found")

    interaction = (await session.exec(
        select(Interaction).where(Interaction.id == pc.interaction_id)
    )).first()
    if not interaction or interaction.organization_id != current_user.organization_id:
        raise HTTPException(status_code=403, detail="Cross-organization access denied")

    feedback = ComplianceFeedback(
        policy_compliance_id=pc.id,
        provided_by_user_id=current_user.id,
        original_is_compliant=pc.is_compliant,
        corrected_is_compliant=body.corrected_is_compliant,
        original_score=pc.compliance_score,
        corrected_score=body.corrected_score,
        correction_reason=body.correction_reason,
        feedback_status=FeedbackStatus.reviewed,
    )
    session.add(feedback)
    await session.flush()

    verdict = "compliant" if body.corrected_is_compliant else "non-compliant"
    await emit(
        session,
        recipient_user_id=interaction.agent_id,
        organization_id=current_user.organization_id,
        type=NotificationType.manager_correction,
        title="Manager corrected a compliance verdict",
        body=f"Updated to {verdict}.",
        link_url=f"/agent/calls/{interaction.id}",
        payload={
            "interaction_id": str(interaction.id),
            "compliance_id": str(pc.id),
            "feedback_id": str(feedback.id),
        },
    )

    await session.commit()
    return CorrectionResponse(feedback_id=feedback.id)
