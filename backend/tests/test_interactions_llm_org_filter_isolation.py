from types import SimpleNamespace
from uuid import UUID

from app.api.deps import get_current_user, get_db, get_session
from app.models.enums import ProcessingStatus, UserRole
from app.models.user import User


def test_interaction_detail_ignores_client_llm_org_filter_override(client, monkeypatch):
    seen_org_filter: dict[str, str | None] = {"value": None}

    class _FakeExecResult:
        def __init__(self, first_value=None, all_values=None):
            self._first = first_value
            self._all = all_values or []

        def first(self):
            return self._first

        def all(self):
            return self._all

    class _FakeSession:
        async def exec(self, statement):
            sql = str(statement).lower()
            if "from organizations" in sql and "join interactions" in sql:
                return _FakeExecResult(first_value="org-a")
            if "from interactions join users" in sql and "where interactions.id" in sql:
                row = SimpleNamespace(
                    id=UUID("c0000000-0000-0000-0000-000000000001"),
                    agent_id=UUID("b0000000-0000-0000-0000-000000000010"),
                    agent_name="Agent A",
                    interaction_date=None,
                    duration_seconds=60,
                    language_detected=None,
                    has_overlap=False,
                    processing_status=ProcessingStatus.completed,
                    audio_file_path="org-a/a.wav",
                    overall_score=None,
                    empathy_score=None,
                    policy_score=None,
                    resolution_score=None,
                    was_resolved=None,
                    total_silence_seconds=None,
                    avg_response_time_seconds=None,
                )
                return _FakeExecResult(first_value=row)
            return _FakeExecResult(all_values=[])

    async def _override_get_db():
        yield _FakeSession()

    async def _override_get_session():
        yield _FakeSession()

    async def _override_current_user():
        return User(
            id=UUID("b0000000-0000-0000-0000-000000000001"),
            organization_id=UUID("a0000000-0000-0000-0000-000000000001"),
            email="manager@orga.local",
            password_hash="hash",
            name="Manager A",
            role=UserRole.manager,
            is_active=True,
        )

    async def _fake_eval(*, session, interaction_id, org_filter, force_rerun, commit_cache, requester_organization_id):
        seen_org_filter["value"] = org_filter

        class _Report:
            interaction_id = interaction_id
            emotion_shift = type(
                "Emotion",
                (),
                {
                    "is_dissonance_detected": False,
                    "dissonance_type": "None",
                    "root_cause": "none",
                    "current_customer_emotion": "neutral",
                    "current_emotion_reasoning": "none",
                    "counterfactual_correction": "none",
                    "evidence_quotes": [],
                    "citations": [],
                    "insufficient_evidence": False,
                    "confidence_score": 1.0,
                },
            )()
            process_adherence = type(
                "Process",
                (),
                {
                    "detected_topic": "topic",
                    "is_resolved": True,
                    "efficiency_score": 10,
                    "justification": "ok",
                    "missing_sop_steps": [],
                    "evidence_quotes": [],
                    "citations": [],
                    "insufficient_evidence": False,
                    "confidence_score": 1.0,
                },
            )()
            nli_policy = type(
                "NLI",
                (),
                {
                    "nli_category": "Entailment",
                    "justification": "ok",
                    "evidence_quotes": [],
                    "citations": [],
                    "policy_version": None,
                    "policy_effective_at": None,
                    "policy_category": None,
                    "conflict_resolution_applied": False,
                    "insufficient_evidence": False,
                    "confidence_score": 1.0,
                    "policy_alignment_score": 1.0,
                },
            )()
            explainability = type("Explainability", (), {"trigger_attributions": [], "claim_provenance": []})()
            derived_customer_text = "customer"
            derived_acoustic_emotion = "neutral"
            derived_fused_emotion = "neutral"
            derived_agent_statement = "agent"

        return _Report()

    client.app.dependency_overrides[get_db] = _override_get_db
    client.app.dependency_overrides[get_session] = _override_get_session
    client.app.dependency_overrides[get_current_user] = _override_current_user
    monkeypatch.setattr("app.api.routes.interactions.evaluate_interaction_triggers", _fake_eval)

    response = client.get(
        "/api/v1/interactions/c0000000-0000-0000-0000-000000000001"
        "?include_llm_triggers=true&llm_org_filter=org-b"
    )

    client.app.dependency_overrides.pop(get_current_user, None)
    client.app.dependency_overrides.pop(get_db, None)
    client.app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 200
    assert seen_org_filter["value"] == "org-a"
