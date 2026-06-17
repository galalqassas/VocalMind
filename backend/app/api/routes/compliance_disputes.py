"""Agent-side compliance dispute endpoints (parity with emotion dispute_router).

Workflow mirrors v5.2 emotion disputes:
  1. Agent sees compliance verdicts on their call detail page.
  2. Agent clicks "Dispute" → POST /policy-compliance/{id}/dispute
  3. Notification fan-out to all org managers.
  4. Manager review queue surfaces the flag.
  5. Manager accepts/rejects via /reviews/compliance/{id}.
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.models.enums import NotificationType, UserRole
from app.models.interaction import Interaction
from app.models.policy import PolicyCompliance
from app.core.notification_service import emit_to_managers

router = APIRouter()


class DisputeRequest(BaseModel):
    agent_flag_note: Optional[str] = None


class DisputeResponse(BaseModel):
    compliance_id: UUID
    is_flagged: bool
    agent_flagged_at: datetime
    message: str


@router.post(
    "/{compliance_id}/dispute",
    response_model=DisputeResponse,
    summary="Agent disputes a compliance verdict",
)
async def dispute_compliance(
    compliance_id: UUID,
    body: DisputeRequest,
    session: SessionDep,
    current_user: CurrentUser,
):
    if current_user.role != UserRole.agent:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only agents can dispute compliance verdicts.",
        )

    pc = (await session.exec(
        select(PolicyCompliance).where(PolicyCompliance.id == compliance_id)
    )).first()
    if not pc:
        raise HTTPException(status_code=404, detail="Compliance record not found")

    interaction = (await session.exec(
        select(Interaction).where(Interaction.id == pc.interaction_id)
    )).first()
    if not interaction:
        raise HTTPException(status_code=404, detail="Interaction not found")
    if interaction.agent_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You can only dispute verdicts on your own calls.",
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    pc.is_flagged = True
    pc.agent_flagged_by = current_user.id
    pc.agent_flagged_at = now
    pc.agent_flag_note = body.agent_flag_note
    session.add(pc)

    await emit_to_managers(
        session,
        organization_id=current_user.organization_id,
        type=NotificationType.agent_flag_pending,
        title=f"{current_user.name} flagged a compliance verdict",
        body=body.agent_flag_note,
        link_url="/manager/reviews",
        payload={
            "interaction_id": str(pc.interaction_id),
            "compliance_id": str(pc.id),
            "kind": "compliance",
        },
    )

    await session.commit()
    return DisputeResponse(
        compliance_id=compliance_id,
        is_flagged=True,
        agent_flagged_at=now,
        message="Compliance verdict disputed. A manager will review it shortly.",
    )


@router.delete("/{compliance_id}/dispute")
async def retract_compliance_dispute(
    compliance_id: UUID,
    session: SessionDep,
    current_user: CurrentUser,
):
    pc = (await session.exec(
        select(PolicyCompliance).where(PolicyCompliance.id == compliance_id)
    )).first()
    if not pc:
        raise HTTPException(status_code=404, detail="Compliance record not found")

    # Agent can only retract their own flag; manager can clear any in their org
    if current_user.role == UserRole.agent and pc.agent_flagged_by != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You can only retract disputes you submitted.",
        )

    pc.is_flagged = False
    pc.agent_flagged_by = None
    pc.agent_flagged_at = None
    pc.agent_flag_note = None
    session.add(pc)
    await session.commit()
    return {"compliance_id": str(compliance_id), "message": "Dispute retracted."}
