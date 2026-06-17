"""Export reviewed feedback rows as JSONL training data.

Provider-agnostic shape so the LLM-trigger team can map it to whichever
few-shot / fine-tune format their new model uses:

    {"task": "emotion|compliance", "input": {...}, "expected_output": {...},
     "reason": str | null, "feedback_id": "...", "interaction_id": "..."}

After successful export, flips feedback_status pending|reviewed → applied and
sets is_used_in_training=True on the exported rows.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable, Literal, Optional
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.emotion_event import EmotionEvent
from app.models.enums import FeedbackStatus
from app.models.feedback import ComplianceFeedback, EmotionFeedback
from app.models.interaction import Interaction
from app.models.policy import PolicyCompliance

logger = logging.getLogger(__name__)

TaskKind = Literal["emotion", "compliance"]


async def _emotion_rows(
    session: AsyncSession, organization_id: Optional[UUID]
) -> list[dict]:
    stmt = (
        select(EmotionFeedback, EmotionEvent, Interaction)
        .join(EmotionEvent, EmotionFeedback.emotion_event_id == EmotionEvent.id)
        .join(Interaction, EmotionEvent.interaction_id == Interaction.id)
        .where(EmotionFeedback.feedback_status == FeedbackStatus.reviewed)
        .where(EmotionFeedback.is_used_in_training.is_(False))
    )
    if organization_id:
        stmt = stmt.where(Interaction.organization_id == organization_id)

    rows = (await session.exec(stmt)).all()
    out: list[dict] = []
    for fb, event, interaction in rows:
        out.append(
            {
                "task": "emotion",
                "input": {
                    "previous_emotion": event.previous_emotion,
                    "ai_predicted_emotion": event.new_emotion,
                    "ai_justification": event.llm_justification,
                    "confidence_score": event.confidence_score,
                },
                "expected_output": {
                    "emotion": fb.corrected_emotion,
                    "justification": fb.corrected_justification,
                },
                "reason": fb.correction_reason,
                "feedback_id": str(fb.id),
                "interaction_id": str(interaction.id),
            }
        )
    return out


async def _compliance_rows(
    session: AsyncSession, organization_id: Optional[UUID]
) -> list[dict]:
    stmt = (
        select(ComplianceFeedback, PolicyCompliance, Interaction)
        .join(PolicyCompliance, ComplianceFeedback.policy_compliance_id == PolicyCompliance.id)
        .join(Interaction, PolicyCompliance.interaction_id == Interaction.id)
        .where(ComplianceFeedback.feedback_status == FeedbackStatus.reviewed)
        .where(ComplianceFeedback.is_used_in_training.is_(False))
    )
    if organization_id:
        stmt = stmt.where(Interaction.organization_id == organization_id)

    rows = (await session.exec(stmt)).all()
    out: list[dict] = []
    for fb, pc, interaction in rows:
        out.append(
            {
                "task": "compliance",
                "input": {
                    "policy_id": str(pc.policy_id),
                    "ai_is_compliant": pc.is_compliant,
                    "ai_score": pc.compliance_score,
                    "ai_reasoning": pc.llm_reasoning,
                    "evidence_text": pc.evidence_text,
                    "retrieved_policy_text": pc.retrieved_policy_text,
                },
                "expected_output": {
                    "is_compliant": fb.corrected_is_compliant,
                    "score": fb.corrected_score,
                },
                "reason": fb.correction_reason,
                "feedback_id": str(fb.id),
                "interaction_id": str(interaction.id),
            }
        )
    return out


async def export_reviewed_feedback(
    session: AsyncSession,
    *,
    output_path: Path,
    organization_id: Optional[UUID] = None,
    mark_applied: bool = True,
    kinds: Iterable[TaskKind] = ("emotion", "compliance"),
) -> dict:
    """Write a JSONL file with all reviewed-but-unused feedback rows.

    Returns: {"path": str, "emotion": int, "compliance": int}
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    emotion_rows = await _emotion_rows(session, organization_id) if "emotion" in kinds else []
    compliance_rows = await _compliance_rows(session, organization_id) if "compliance" in kinds else []

    with output_path.open("w", encoding="utf-8") as fh:
        for row in (*emotion_rows, *compliance_rows):
            fh.write(json.dumps(row, ensure_ascii=False))
            fh.write("\n")

    if mark_applied:
        for row in emotion_rows:
            fb = (await session.exec(
                select(EmotionFeedback).where(EmotionFeedback.id == UUID(row["feedback_id"]))
            )).first()
            if fb:
                fb.feedback_status = FeedbackStatus.applied
                fb.is_used_in_training = True
                session.add(fb)
        for row in compliance_rows:
            fb = (await session.exec(
                select(ComplianceFeedback).where(ComplianceFeedback.id == UUID(row["feedback_id"]))
            )).first()
            if fb:
                fb.feedback_status = FeedbackStatus.applied
                fb.is_used_in_training = True
                session.add(fb)
        await session.commit()

    logger.info(
        "Exported %d emotion + %d compliance feedback rows to %s",
        len(emotion_rows),
        len(compliance_rows),
        output_path,
    )
    return {
        "path": str(output_path),
        "emotion": len(emotion_rows),
        "compliance": len(compliance_rows),
    }
