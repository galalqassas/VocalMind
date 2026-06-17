from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone
from uuid import UUID, uuid4


class CompanyPolicy(SQLModel, table=True):
    """Policy definitions scoped to an organization."""
    __tablename__ = "company_policies"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(foreign_key="organizations.id")
    policy_category: str = Field(max_length=100)
    policy_title: str = Field(max_length=255)
    policy_text: str
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class OrganizationPolicy(SQLModel, table=True):
    """Junction table: which policies each organization has activated."""
    __tablename__ = "organization_policies"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(foreign_key="organizations.id")
    policy_id: UUID = Field(foreign_key="company_policies.id")
    is_active: bool = Field(default=True)
    assigned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class PolicyCompliance(SQLModel, table=True):
    """AI compliance verdict for a policy against an interaction.

    Agent-flagging workflow (mirrors EmotionEvent v5.2):
      - Agents see their compliance verdicts on their own call detail page.
      - "Dispute" → sets is_flagged + agent_flagged_by/at/note.
      - Manager review queue surfaces flagged verdicts.
      - Manager accept → ComplianceFeedback row at `reviewed`.
    """
    __tablename__ = "policy_compliance"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    interaction_id: UUID = Field(foreign_key="interactions.id")
    policy_id: UUID = Field(foreign_key="company_policies.id")
    is_compliant: bool
    compliance_score: float
    degraded: bool = Field(default=False)
    llm_reasoning: Optional[str] = None
    evidence_text: Optional[str] = None
    retrieved_policy_text: Optional[str] = None

    # ── Agent-dispute fields ────────────────────────────────
    is_flagged: bool = Field(default=False)
    agent_flagged_by: Optional[UUID] = Field(default=None, foreign_key="users.id")
    agent_flagged_at: Optional[datetime] = Field(default=None)
    agent_flag_note: Optional[str] = Field(default=None)
