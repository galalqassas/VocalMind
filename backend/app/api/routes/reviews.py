"""Manager Review Queue.

Single home for agent-disputed AI evaluations (emotion + compliance).
Manager either:
  * accepts → creates a feedback row at `reviewed` (eligible for export).
  * rejects → clears the flag, no feedback row written.

Both actions notify the originating agent.
"""
from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, Field
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.models.emotion_event import EmotionEvent
from app.models.enums import FeedbackStatus, NotificationType, UserRole
from app.models.feedback import ComplianceFeedback, EmotionFeedback
from app.models.interaction import Interaction
from app.models.policy import CompanyPolicy, PolicyCompliance
from app.models.user import User
from app.core.notification_service import emit

router = APIRouter()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _ensure_manager(current_user: User) -> None:
    if current_user.role != UserRole.manager:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manager-only endpoint",
        )


# ── Response schemas ─────────────────────────────────────────────────────────

class EmotionFlagItem(BaseModel):
    kind: Literal["emotion"] = Field("emotion", description="Discriminator field identifying this review item as an emotion dispute.")
    review_id: UUID = Field(..., description="The unique UUID of the disputed emotion event.")
    interaction_id: UUID = Field(..., description="The unique UUID of the interaction/call containing this event.")
    agent_id: UUID = Field(..., description="The unique UUID of the agent who flagged the event.")
    agent_name: str = Field(..., description="The name or email of the agent who flagged the event.")
    agent_flagged_at: datetime = Field(..., description="Timestamp when the agent flagged the event.")
    agent_flag_note: Optional[str] = Field(None, description="Optional explanation note provided by the agent when flagging.")
    previous_emotion: Optional[str] = Field(None, description="The original emotion detected before the event (if any).")
    new_emotion: str = Field(..., description="The new disputed emotion label predicted by AI.")
    llm_justification: Optional[str] = Field(None, description="AI-generated justification for the predicted emotion.")
    confidence_score: Optional[float] = Field(None, description="AI confidence score for the predicted emotion.")
    jump_to_seconds: float = Field(..., description="Timestamp in seconds offset from the audio start where the emotion event occurred.")


class ComplianceFlagItem(BaseModel):
    kind: Literal["compliance"] = Field("compliance", description="Discriminator field identifying this review item as a compliance dispute.")
    review_id: UUID = Field(..., description="The unique UUID of the disputed policy compliance record.")
    interaction_id: UUID = Field(..., description="The unique UUID of the interaction/call containing this compliance record.")
    agent_id: UUID = Field(..., description="The unique UUID of the agent who flagged the compliance record.")
    agent_name: str = Field(..., description="The name or email of the agent who flagged the compliance record.")
    agent_flagged_at: datetime = Field(..., description="Timestamp when the agent flagged the compliance record.")
    agent_flag_note: Optional[str] = Field(None, description="Optional explanation note provided by the agent when flagging.")
    policy_id: UUID = Field(..., description="The unique UUID of the policy that was evaluated.")
    policy_title: Optional[str] = Field(None, description="Title of the evaluated policy.")
    is_compliant: bool = Field(..., description="The disputed compliance status (True if compliant, False otherwise).")
    compliance_score: float = Field(..., description="The disputed compliance score value.")
    llm_reasoning: Optional[str] = Field(None, description="AI-generated reasoning for the compliance verdict.")
    evidence_text: Optional[str] = Field(None, description="Transcript evidence text anchored to the compliance verdict.")


class ReviewQueueResponse(BaseModel):
    emotion: List[EmotionFlagItem] = Field(..., description="List of agent-disputed emotion events pending manager review.")
    compliance: List[ComplianceFlagItem] = Field(..., description="List of agent-disputed compliance verdicts pending manager review.")


class EmotionReviewRequest(BaseModel):
    decision: Literal["accept", "reject"] = Field(..., description="The manager's decision to accept (correct) or reject (dismiss) the agent's dispute.")
    corrected_emotion: Optional[str] = Field(None, description="The corrected emotion label. Required if decision is 'accept'.")
    corrected_justification: Optional[str] = Field(None, description="Optional manager justification for the correction.")
    manager_note: Optional[str] = Field(None, description="Optional review notes/feedback for the agent.")


class ComplianceReviewRequest(BaseModel):
    decision: Literal["accept", "reject"] = Field(..., description="The manager's decision to accept (correct) or reject (dismiss) the agent's dispute.")
    corrected_is_compliant: Optional[bool] = Field(None, description="The corrected compliance status. Required if decision is 'accept'.")
    corrected_score: Optional[float] = Field(None, description="Optional corrected compliance score value (0.0 to 1.0).")
    manager_note: Optional[str] = Field(None, description="Optional review notes/feedback for the agent.")


class ReviewDecisionResponse(BaseModel):
    review_id: UUID = Field(..., description="The unique UUID of the reviewed dispute (event_id or compliance_id).")
    decision: str = Field(..., description="The manager's decision ('accept' or 'reject').")
    feedback_id: Optional[UUID] = Field(None, description="The unique UUID of the created feedback/correction record, if accepted.")


# ── Queue ────────────────────────────────────────────────────────────────────

@router.get("/queue", response_model=ReviewQueueResponse, responses={401: {"description": "Not authenticated"}, 403: {"description": "Manager access or organization scope validation failed"}})
async def get_review_queue(session: SessionDep, current_user: CurrentUser):
    """
    Retrieve the queue of all agent-disputed AI evaluations (emotion and compliance) within the manager's organization.
    """
    _ensure_manager(current_user)
    org_id = current_user.organization_id

    # Emotion flags joined w/ interaction (for org scope) and flagging agent
    emo_stmt = (
        select(EmotionEvent, User, Interaction)
        .join(Interaction, EmotionEvent.interaction_id == Interaction.id)
        .join(User, EmotionEvent.agent_flagged_by == User.id)
        .where(Interaction.organization_id == org_id)
        .where(EmotionEvent.is_flagged.is_(True))
        .where(EmotionEvent.agent_flagged_by.is_not(None))
        .order_by(EmotionEvent.agent_flagged_at.desc())
    )
    emo_rows = (await session.exec(emo_stmt)).all()
    emotion_items = [
        EmotionFlagItem(
            review_id=ev.id,
            interaction_id=ev.interaction_id,
            agent_id=user.id,
            agent_name=user.name or user.email,
            agent_flagged_at=ev.agent_flagged_at,  # type: ignore[arg-type]
            agent_flag_note=ev.agent_flag_note,
            previous_emotion=ev.previous_emotion,
            new_emotion=ev.new_emotion,
            llm_justification=ev.llm_justification,
            confidence_score=ev.confidence_score,
            jump_to_seconds=ev.jump_to_seconds,
        )
        for ev, user, _ in emo_rows
    ]

    # Compliance flags joined w/ interaction + policy + flagging agent
    comp_stmt = (
        select(PolicyCompliance, User, Interaction, CompanyPolicy)
        .join(Interaction, PolicyCompliance.interaction_id == Interaction.id)
        .join(User, PolicyCompliance.agent_flagged_by == User.id)
        .join(CompanyPolicy, PolicyCompliance.policy_id == CompanyPolicy.id)
        .where(Interaction.organization_id == org_id)
        .where(PolicyCompliance.is_flagged.is_(True))
        .where(PolicyCompliance.agent_flagged_by.is_not(None))
        .order_by(PolicyCompliance.agent_flagged_at.desc())
    )
    comp_rows = (await session.exec(comp_stmt)).all()
    compliance_items = [
        ComplianceFlagItem(
            review_id=pc.id,
            interaction_id=pc.interaction_id,
            agent_id=user.id,
            agent_name=user.name or user.email,
            agent_flagged_at=pc.agent_flagged_at,  # type: ignore[arg-type]
            agent_flag_note=pc.agent_flag_note,
            policy_id=pc.policy_id,
            policy_title=policy.policy_title,
            is_compliant=pc.is_compliant,
            compliance_score=pc.compliance_score,
            llm_reasoning=pc.llm_reasoning,
            evidence_text=pc.evidence_text,
        )
        for pc, user, _, policy in comp_rows
    ]

    return ReviewQueueResponse(emotion=emotion_items, compliance=compliance_items)


# ── Emotion flag decision ────────────────────────────────────────────────────

@router.post("/emotion/{event_id}", response_model=ReviewDecisionResponse, responses={401: {"description": "Not authenticated"}, 403: {"description": "Manager access or organization scope validation failed"}, 404: {"description": "Emotion event not found"}, 422: {"description": "Invalid parameter or body format"}})
async def review_emotion_flag(
    event_id: UUID = Path(..., description="The unique UUID of the disputed emotion event to review."),
    body: EmotionReviewRequest = None,
    session: SessionDep = None,
    current_user: CurrentUser = None,
):
    """
    Review and submit a decision (accept/reject) on an agent-disputed emotion event.
    Accepting the dispute creates an EmotionFeedback correction record and notifies the agent.
    """
    _ensure_manager(current_user)

    event = (await session.exec(
        select(EmotionEvent).where(EmotionEvent.id == event_id)
    )).first()
    if not event:
        raise HTTPException(status_code=404, detail="Emotion event not found")
    if not event.is_flagged or event.agent_flagged_by is None:
        raise HTTPException(status_code=400, detail="Event is not pending review")

    interaction = (await session.exec(
        select(Interaction).where(Interaction.id == event.interaction_id)
    )).first()
    if not interaction or interaction.organization_id != current_user.organization_id:
        raise HTTPException(status_code=403, detail="Cross-organization access denied")

    agent_id = event.agent_flagged_by
    feedback_id: Optional[UUID] = None

    if body.decision == "accept":
        if not body.corrected_emotion:
            raise HTTPException(
                status_code=400,
                detail="corrected_emotion is required when accepting a flag",
            )
        feedback = EmotionFeedback(
            emotion_event_id=event.id,
            provided_by_user_id=current_user.id,
            llm_justification=event.llm_justification,
            corrected_emotion=body.corrected_emotion,
            corrected_justification=body.corrected_justification,
            correction_reason=body.manager_note,
            feedback_status=FeedbackStatus.reviewed,
        )
        session.add(feedback)
        await session.flush()
        feedback_id = feedback.id

        await emit(
            session,
            recipient_user_id=agent_id,
            organization_id=current_user.organization_id,
            type=NotificationType.flag_approved,
            title="Your emotion flag was approved",
            body=f"Manager accepted your flag and corrected the emotion to '{body.corrected_emotion}'.",
            link_url=f"/agent/calls/{event.interaction_id}",
            payload={
                "interaction_id": str(event.interaction_id),
                "event_id": str(event.id),
                "feedback_id": str(feedback_id),
            },
        )
    else:  # reject
        await emit(
            session,
            recipient_user_id=agent_id,
            organization_id=current_user.organization_id,
            type=NotificationType.flag_rejected,
            title="Your emotion flag was rejected",
            body=body.manager_note or "Manager kept the AI verdict after review.",
            link_url=f"/agent/calls/{event.interaction_id}",
            payload={
                "interaction_id": str(event.interaction_id),
                "event_id": str(event.id),
            },
        )

    # Clear the dispute either way
    event.is_flagged = False
    event.agent_flagged_by = None
    event.agent_flagged_at = None
    event.agent_flag_note = None
    session.add(event)

    await session.commit()
    return ReviewDecisionResponse(
        review_id=event_id, decision=body.decision, feedback_id=feedback_id
    )


# ── Compliance flag decision ────────────────────────────────────────────────

@router.post("/compliance/{compliance_id}", response_model=ReviewDecisionResponse, responses={401: {"description": "Not authenticated"}, 403: {"description": "Manager access or organization scope validation failed"}, 404: {"description": "Compliance record not found"}, 422: {"description": "Invalid parameter or body format"}})
async def review_compliance_flag(
    compliance_id: UUID = Path(..., description="The unique UUID of the disputed compliance record to review."),
    body: ComplianceReviewRequest = None,
    session: SessionDep = None,
    current_user: CurrentUser = None,
):
    """
    Review and submit a decision (accept/reject) on an agent-disputed compliance verdict.
    Accepting the dispute creates a ComplianceFeedback correction record and notifies the agent.
    """
    _ensure_manager(current_user)

    pc = (await session.exec(
        select(PolicyCompliance).where(PolicyCompliance.id == compliance_id)
    )).first()
    if not pc:
        raise HTTPException(status_code=404, detail="Compliance record not found")
    if not pc.is_flagged or pc.agent_flagged_by is None:
        raise HTTPException(status_code=400, detail="Record is not pending review")

    interaction = (await session.exec(
        select(Interaction).where(Interaction.id == pc.interaction_id)
    )).first()
    if not interaction or interaction.organization_id != current_user.organization_id:
        raise HTTPException(status_code=403, detail="Cross-organization access denied")

    agent_id = pc.agent_flagged_by
    feedback_id: Optional[UUID] = None

    if body.decision == "accept":
        if body.corrected_is_compliant is None:
            raise HTTPException(
                status_code=400,
                detail="corrected_is_compliant is required when accepting a flag",
            )
        feedback = ComplianceFeedback(
            policy_compliance_id=pc.id,
            provided_by_user_id=current_user.id,
            original_is_compliant=pc.is_compliant,
            corrected_is_compliant=body.corrected_is_compliant,
            original_score=pc.compliance_score,
            corrected_score=body.corrected_score,
            correction_reason=body.manager_note,
            feedback_status=FeedbackStatus.reviewed,
        )
        session.add(feedback)
        await session.flush()
        feedback_id = feedback.id

        await emit(
            session,
            recipient_user_id=agent_id,
            organization_id=current_user.organization_id,
            type=NotificationType.flag_approved,
            title="Your compliance flag was approved",
            body=f"Manager updated the verdict to {'compliant' if body.corrected_is_compliant else 'non-compliant'}.",
            link_url=f"/agent/calls/{pc.interaction_id}",
            payload={
                "interaction_id": str(pc.interaction_id),
                "compliance_id": str(pc.id),
                "feedback_id": str(feedback_id),
            },
        )
    else:
        await emit(
            session,
            recipient_user_id=agent_id,
            organization_id=current_user.organization_id,
            type=NotificationType.flag_rejected,
            title="Your compliance flag was rejected",
            body=body.manager_note or "Manager kept the AI verdict after review.",
            link_url=f"/agent/calls/{pc.interaction_id}",
            payload={
                "interaction_id": str(pc.interaction_id),
                "compliance_id": str(pc.id),
            },
        )

    pc.is_flagged = False
    pc.agent_flagged_by = None
    pc.agent_flagged_at = None
    pc.agent_flag_note = None
    session.add(pc)

    await session.commit()
    return ReviewDecisionResponse(
        review_id=compliance_id, decision=body.decision, feedback_id=feedback_id
    )
