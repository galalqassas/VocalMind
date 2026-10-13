from datetime import datetime
from types import SimpleNamespace
from uuid import UUID

from sqlmodel import SQLModel, Session, create_engine

from app.api.deps import get_current_user, get_db, get_session
from app.llm_trigger.schemas import EmotionShiftAnalysis, NLIEvaluation, ProcessAdherenceReport
from app.models.enums import SpeakerRole, UserRole
from app.models.interaction import Interaction
from app.models.organization import Organization
from app.models.transcript import Transcript
from app.models.user import User
from app.models.utterance import Utterance


def test_llm_trigger_run_blocks_cross_org_access(client, tmp_path, monkeypatch):
    db_path = tmp_path / "llm_trigger_cross_org.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    session = Session(engine)

    org_a = Organization(
        id=UUID("a0000000-0000-0000-0000-000000000001"),
        name="Org A",
        slug="org-a",
    )
    org_b = Organization(
        id=UUID("a0000000-0000-0000-0000-000000000002"),
        name="Org B",
        slug="org-b",
    )
    user_a = User(
        id=UUID("b0000000-0000-0000-0000-000000000001"),
        organization_id=org_a.id,
        email="a@org.local",
        password_hash="hash",
        name="Manager A",
        role=UserRole.manager,
        is_active=True,
    )
    user_b_agent = User(
        id=UUID("b0000000-0000-0000-0000-000000000002"),
        organization_id=org_b.id,
        email="agent@orgb.local",
        password_hash="hash",
        name="Agent B",
        role=UserRole.agent,
        is_active=True,
    )
    interaction_b = Interaction(
        id=UUID("c0000000-0000-0000-0000-000000000001"),
        organization_id=org_b.id,
        agent_id=user_b_agent.id,
        uploaded_by=user_b_agent.id,
        audio_file_path="org-b/call.wav",
        file_size_bytes=1234,
        duration_seconds=60,
        file_format="wav",
        interaction_date=datetime.utcnow(),
    )
    transcript_b = Transcript(
        id=UUID("d0000000-0000-0000-0000-000000000001"),
        interaction_id=interaction_b.id,
        full_text="customer: refund please\nagent: I can help",
    )
    utterance_b = Utterance(
        id=UUID("e0000000-0000-0000-0000-000000000001"),
        interaction_id=interaction_b.id,
        transcript_id=transcript_b.id,
        speaker_role=SpeakerRole.customer,
        sequence_index=0,
        start_time_seconds=0.0,
        end_time_seconds=1.0,
        text="refund please",
        emotion="frustrated",
        emotion_confidence=0.9,
    )
    session.add_all([org_a, org_b, user_a, user_b_agent, interaction_b, transcript_b, utterance_b])
    session.commit()

    from tests.conftest import AsyncSessionAdapter
    adapter = AsyncSessionAdapter(session)

    async def _override_get_db():
        yield adapter

    async def _override_get_session():
        yield adapter

    async def _override_current_user():
        return user_a

    client.app.dependency_overrides[get_db] = _override_get_db
    client.app.dependency_overrides[get_session] = _override_get_session
    client.app.dependency_overrides[get_current_user] = _override_current_user

    async def _fake_emotion_pipeline(**_kwargs):
        return EmotionShiftAnalysis(
            is_dissonance_detected=False,
            dissonance_type="None",
            root_cause="none",
            counterfactual_correction="none",
            evidence_quotes=[],
            citations=[],
        )

    async def _fake_grounded_checks(**_kwargs):
        return (
            ProcessAdherenceReport(
                detected_topic="refund_request",
                is_resolved=True,
                efficiency_score=9,
                justification="ok",
                missing_sop_steps=[],
                evidence_quotes=[],
                citations=[],
            ),
            NLIEvaluation(
                nli_category="Entailment",
                justification="ok",
                evidence_quotes=[],
                citations=[],
                confidence_score=0.95,
            ),
        )

    async def _fake_transcript_policy(**_kwargs):
        return None

    async def _fake_policy_context(**_kwargs):
        return SimpleNamespace(
            text="policy",
            version=None,
            effective_at=None,
            category=None,
            conflict_resolution_applied=False,
        )

    monkeypatch.setattr("app.llm_trigger.service._evaluate_emotion_pipeline", _fake_emotion_pipeline)
    monkeypatch.setattr("app.llm_trigger.service._evaluate_policy_and_sop_trigger_checks", _fake_grounded_checks)
    monkeypatch.setattr("app.llm_trigger.service._evaluate_transcript_policy_pipeline", _fake_transcript_policy)
    monkeypatch.setattr("app.llm_trigger.service._resolve_active_policy_context", _fake_policy_context)
    monkeypatch.setattr("app.llm_trigger.service.retrieve_policy_chunks", lambda **_kwargs: [])

    response = client.post(f"/api/v1/llm-trigger/interaction/{interaction_b.id}/run", json={})

    client.app.dependency_overrides.pop(get_current_user, None)
    client.app.dependency_overrides.pop(get_db, None)
    client.app.dependency_overrides.pop(get_session, None)
    session.close()

    assert response.status_code == 404


def _seed_single_org(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'llm_trigger_run.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    org = Organization(id=UUID("a1000000-0000-0000-0000-000000000001"), name="Org", slug="org")
    manager = User(
        id=UUID("b1000000-0000-0000-0000-000000000001"), organization_id=org.id, email="m@org.local",
        password_hash="hash", name="Manager", role=UserRole.manager, is_active=True,
    )
    interaction = Interaction(
        id=UUID("c1000000-0000-0000-0000-000000000001"), organization_id=org.id, agent_id=manager.id,
        uploaded_by=manager.id, audio_file_path="org/call.wav", file_size_bytes=1, duration_seconds=60,
        file_format="wav", interaction_date=datetime.utcnow(),
    )
    transcript = Transcript(
        id=UUID("d1000000-0000-0000-0000-000000000001"), interaction_id=interaction.id,
        full_text="customer: please send a wire transfer\nagent: I can help with the wire",
    )
    utterance = Utterance(
        id=UUID("e1000000-0000-0000-0000-000000000001"), interaction_id=interaction.id,
        transcript_id=transcript.id, speaker_role=SpeakerRole.customer, sequence_index=0,
        start_time_seconds=0.0, end_time_seconds=1.0, text="please send a wire transfer",
        emotion="neutral", emotion_confidence=0.9,
    )
    session.add_all([org, manager, interaction, transcript, utterance])
    session.commit()
    return session, manager, interaction


def _run_with_overrides(client, session, user, url):
    from tests.conftest import AsyncSessionAdapter

    adapter = AsyncSessionAdapter(session)

    async def _db():
        yield adapter

    async def _user():
        return user

    client.app.dependency_overrides[get_db] = _db
    client.app.dependency_overrides[get_session] = _db
    client.app.dependency_overrides[get_current_user] = _user
    try:
        return client.post(url, json={"force_rerun": True})
    finally:
        for dep in (get_current_user, get_db, get_session):
            client.app.dependency_overrides.pop(dep, None)
        session.close()


def _patch_non_llm_dependencies(monkeypatch):
    monkeypatch.setattr(
        "app.llm_trigger.service.fuse_emotion_signals", lambda **_kwargs: SimpleNamespace(emotion="neutral")
    )
    monkeypatch.setattr(
        "app.llm_trigger.service.resolve_retrieved_sop_context",
        lambda **_kwargs: SimpleNamespace(text="", chunks=[], retrieval_failed=False),
    )
    monkeypatch.setattr("app.llm_trigger.service.retrieve_policy_chunks", lambda **_kwargs: [])

    async def _none(**_kwargs):
        return None

    monkeypatch.setattr("app.llm_trigger.service._evaluate_transcript_policy_pipeline", _none)


def test_llm_trigger_run_classifies_topic_once_and_passes_it_down(client, tmp_path, monkeypatch):
    session, manager, interaction = _seed_single_org(tmp_path)
    _patch_non_llm_dependencies(monkeypatch)
    topic_calls: list[str] = []
    seen_topics: list[str | None] = []

    async def _classify(transcript_text):
        topic_calls.append(transcript_text)
        return "wire_transfer"

    async def _emotion(**_kwargs):
        return EmotionShiftAnalysis(dissonance_type="none")

    async def _grounded(**kwargs):
        seen_topics.append(kwargs.get("topic"))
        return (
            ProcessAdherenceReport(detected_topic=kwargs["topic"], is_resolved=True, efficiency_score=9),
            NLIEvaluation(nli_category="Entailment", justification="ok"),
        )

    monkeypatch.setattr("app.llm_trigger.service.classify_topic", _classify)
    monkeypatch.setattr("app.llm_trigger.service._evaluate_emotion_pipeline", _emotion)
    monkeypatch.setattr("app.llm_trigger.service._evaluate_policy_and_sop_trigger_checks", _grounded)

    response = _run_with_overrides(client, session, manager, f"/api/v1/llm-trigger/interaction/{interaction.id}/run")

    assert response.status_code == 200, response.text
    assert len(topic_calls) == 1
    assert seen_topics == ["wire_transfer"]
    assert response.json()["process_adherence"]["detected_topic"] == "wire_transfer"


def test_llm_trigger_run_returns_503_when_llm_unavailable(client, tmp_path, monkeypatch):
    session, manager, interaction = _seed_single_org(tmp_path)
    _patch_non_llm_dependencies(monkeypatch)

    class _DownChain:
        async def ainvoke(self, _payload):
            raise ConnectionError("connection refused")

    monkeypatch.setattr("app.llm_trigger.service.build_topic_classification_chain", lambda: _DownChain())

    response = _run_with_overrides(client, session, manager, f"/api/v1/llm-trigger/interaction/{interaction.id}/run")

    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()
