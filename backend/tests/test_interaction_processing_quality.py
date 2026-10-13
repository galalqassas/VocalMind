from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlmodel import SQLModel, Session, create_engine, select

import app.models  # noqa: F401
from app.core import interaction_processing as ip
from app.models.emotion_event import EmotionEvent
from app.models.enums import JobStage, JobStatus, ProcessingStatus, SpeakerRole
from app.models.interaction import Interaction
from app.models.interaction_score import InteractionScore
from app.models.organization import Organization
from app.models.processing import ProcessingJob
from app.models.transcript import Transcript
from app.models.utterance import Utterance
from app.models.user import User
from app.models.enums import UserRole


from tests.conftest import AsyncSessionAdapter


def _seed_interaction(tmp_path) -> tuple[Session, object]:
    engine = create_engine(f"sqlite:///{tmp_path / 'interaction-quality.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    org_id, manager_id, agent_id, interaction_id = uuid4(), uuid4(), uuid4(), uuid4()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    session.add(Organization(id=org_id, name="Nexa", slug="nexa", created_at=now))
    for user_id, email, role in ((manager_id, "manager@example.com", UserRole.manager), (agent_id, "agent@example.com", UserRole.agent)):
        session.add(User(id=user_id, organization_id=org_id, email=email, password_hash="hash", name=email, role=role, is_active=True))
    session.add(
        Interaction(
            id=interaction_id,
            organization_id=org_id,
            agent_id=agent_id,
            uploaded_by=manager_id,
            audio_file_path=str(Path(tmp_path / "call.wav")),
            processing_status=ProcessingStatus.pending,
            duration_seconds=0,
            file_size_bytes=10,
            file_format="wav",
            interaction_date=now,
        )
    )
    session.add(Transcript(interaction_id=interaction_id, full_text=""))
    for stage in ip.STAGE_ORDER:
        session.add(ProcessingJob(interaction_id=interaction_id, stage=stage, status=JobStatus.pending))
    session.commit()
    return session, interaction_id


_ANALYSIS = {
    "language": "en",
    "text": "",
    "segments": [
        {"start": 0.0, "end": 2.0, "text": "Thank you for calling, how can I help you today?", "speaker": "SPEAKER_01",
         "speaker_meta": {"source": "diarization"}, "emotion": "neutral", "emotion_scores": [{"label": "neutral", "score": 0.8}]},
        {"start": 2.2, "end": 4.5, "text": "I was charged twice on my bill.", "speaker": "SPEAKER_00",
         "speaker_meta": {"source": "diarization"}, "emotion": "frustrated", "emotion_scores": [{"label": "frustrated", "score": 0.9}]},
        {"start": 4.7, "end": 7.0, "text": "I still cannot access my account.", "speaker": "SPEAKER_00",
         "speaker_meta": {"source": "diarization"}, "emotion": "frustrated", "emotion_scores": [{"label": "frustrated", "score": 0.9}]},
    ],
}


def _patch_pipeline(monkeypatch, session, evaluate):
    monkeypatch.setattr(ip, "AsyncSession", lambda *args, **kwargs: AsyncSessionAdapter(session))
    monkeypatch.setattr(ip, "engine", SimpleNamespace())
    monkeypatch.setattr(ip, "fetch_audio_bytes", AsyncMock(return_value=(b"RIFF", "call.wav")))
    monkeypatch.setattr(ip.full_client, "analyze_bytes", AsyncMock(return_value=_ANALYSIS))
    monkeypatch.setattr(ip, "is_gibberish", AsyncMock(return_value=False))
    monkeypatch.setattr(ip, "evaluate_interaction_triggers", evaluate)


def _jobs(session, interaction_id) -> dict:
    rows = session.exec(select(ProcessingJob).where(ProcessingJob.interaction_id == interaction_id)).all()
    return {job.stage: job for job in rows}


@pytest.mark.asyncio
async def test_process_interaction_persists_lr_roles_and_scores(monkeypatch, tmp_path):
    session, interaction_id = _seed_interaction(tmp_path)
    report = SimpleNamespace(
        nli_policy=SimpleNamespace(insufficient_evidence=False),
        process_adherence=SimpleNamespace(insufficient_evidence=False),
    )
    _patch_pipeline(monkeypatch, session, AsyncMock(return_value=report))
    monkeypatch.setattr(ip, "ensure_organization_policies_from_source", AsyncMock())
    monkeypatch.setattr(ip, "persist_policy_violations", AsyncMock())
    monkeypatch.setattr(ip, "derive_violation_specs", lambda _inp: [])
    monkeypatch.setattr(ip.ViolationMappingInput, "from_llm_trigger_report", classmethod(lambda cls, _r: cls()))
    monkeypatch.setattr(
        ip, "compute_scores",
        lambda _r: SimpleNamespace(overall=0.8, empathy=0.9, policy=0.7, resolution=0.6, was_resolved=True),
    )

    await ip.process_interaction(interaction_id)

    utterances = session.exec(
        select(Utterance).where(Utterance.interaction_id == interaction_id).order_by(Utterance.sequence_index)
    ).all()
    assert [u.speaker_role for u in utterances] == [SpeakerRole.agent, SpeakerRole.customer, SpeakerRole.customer]
    events = session.exec(select(EmotionEvent).where(EmotionEvent.interaction_id == interaction_id)).all()
    assert [e.new_emotion for e in events] == ["frustrated"]
    score = session.exec(select(InteractionScore).where(InteractionScore.interaction_id == interaction_id)).one()
    assert (score.overall_score, score.total_silence_seconds, score.avg_response_time_seconds) == (0.8, None, None)
    assert all(job.status == JobStatus.completed for job in _jobs(session, interaction_id).values())
    assert session.get(Interaction, interaction_id).processing_status == ProcessingStatus.completed


@pytest.mark.asyncio
async def test_reasoning_failure_marks_stage_failed_without_default_scores(monkeypatch, tmp_path):
    session, interaction_id = _seed_interaction(tmp_path)
    _patch_pipeline(monkeypatch, session, AsyncMock(side_effect=RuntimeError("LLM provider down")))

    with pytest.raises(ip.StageFailed) as exc_info:
        await ip.process_interaction(interaction_id)
    await ip.mark_interaction_failed(interaction_id, str(exc_info.value), exc_info.value.stages)

    jobs = _jobs(session, interaction_id)
    assert jobs[JobStage.reasoning].status == JobStatus.failed
    assert "LLM provider down" in jobs[JobStage.reasoning].error_message
    for stage in (JobStage.scoring, JobStage.rag_eval):
        assert jobs[stage].status == JobStatus.failed
        assert jobs[stage].error_message == "Not run: reasoning stage failed."
    for stage in (JobStage.diarization, JobStage.stt, JobStage.emotion):
        assert jobs[stage].status == JobStatus.completed
    assert session.exec(select(InteractionScore).where(InteractionScore.interaction_id == interaction_id)).first() is None
    assert session.get(Interaction, interaction_id).processing_status == ProcessingStatus.failed
    # Reprocess is allowed without force once nothing is pending/running.
    assert not await ip.interaction_has_active_jobs(AsyncSessionAdapter(session), interaction_id)


@pytest.mark.asyncio
async def test_audio_analysis_failure_fails_audio_stages(monkeypatch, tmp_path):
    session, interaction_id = _seed_interaction(tmp_path)
    _patch_pipeline(monkeypatch, session, AsyncMock())
    monkeypatch.setattr(ip.full_client, "analyze_bytes", AsyncMock(side_effect=RuntimeError("emotion service down")))

    with pytest.raises(ip.StageFailed) as exc_info:
        await ip.process_interaction(interaction_id)

    assert exc_info.value.stages == (JobStage.diarization, JobStage.stt, JobStage.emotion)
    assert "emotion service down" in str(exc_info.value)


def _fake_lr(monkeypatch, probabilities: dict[str, float]):
    monkeypatch.setattr(ip, "_agent_probabilities", lambda texts: [probabilities[t] for t in texts])


def test_assign_speaker_roles_two_clusters_uses_mean_agent_probability(monkeypatch):
    _fake_lr(monkeypatch, {"a1": 0.9, "a2": 0.4, "c1": 0.3, "c2": 0.5})
    segments = [
        {"speaker": "SPEAKER_00", "text": "c1"},
        {"speaker": "SPEAKER_01", "text": "a1"},
        {"speaker": "SPEAKER_00", "text": "c2"},
        {"speaker": "SPEAKER_01", "text": "a2"},
    ]
    assert ip.assign_speaker_roles(segments) == [
        SpeakerRole.customer, SpeakerRole.agent, SpeakerRole.customer, SpeakerRole.agent,
    ]


def test_assign_speaker_roles_single_cluster_classifies_each_segment(monkeypatch):
    _fake_lr(monkeypatch, {"hello": 0.8, "refund": 0.2})
    segments = [
        {"speaker": "SPEAKER_00", "text": "hello"},
        {"speaker": "SPEAKER_00", "text": "refund"},
    ]
    assert ip.assign_speaker_roles(segments) == [SpeakerRole.agent, SpeakerRole.customer]


def test_assign_speaker_roles_keeps_stereo_channel_labels(monkeypatch):
    monkeypatch.setattr(ip, "_agent_probabilities", lambda texts: pytest.fail("LR must not run"))
    segments = [
        {"speaker": "CUSTOMER", "text": "Thank you for calling", "speaker_meta": {"source": "channel"}},
        {"speaker": "AGENT", "text": "I was charged twice", "speaker_meta": {"source": "channel"}},
    ]
    assert ip.assign_speaker_roles(segments) == [SpeakerRole.customer, SpeakerRole.agent]


def test_assign_speaker_roles_with_real_model():
    segments = [
        {"speaker": "SPEAKER_00", "text": "Thank you for calling, how can I help you today?"},
        {"speaker": "SPEAKER_01", "text": "I was charged twice on my bill and I want a refund."},
    ]
    assert ip.assign_speaker_roles(segments) == [SpeakerRole.agent, SpeakerRole.customer]


def test_assign_speaker_roles_raises_when_model_missing(monkeypatch):
    monkeypatch.setattr(ip, "_lr_model", None)
    monkeypatch.setattr("joblib.load", lambda _path: (_ for _ in ()).throw(FileNotFoundError("model.pkl")))
    with pytest.raises(ip.SpeakerRoleModelUnavailable):
        ip.assign_speaker_roles([{"speaker": "SPEAKER_00", "text": "hello"}])


def test_emotion_min_duration_gate_inherits_prev_for_short_segments():
    """Sub-threshold segments inherit the previous segment's emotion so that
    low-confidence emotion2vec outputs on brief interjections don't pollute
    the call-level distribution. Segments at or above the threshold keep
    their own emotion.
    """
    segments = [
        {"start": 0.0, "end": 3.0, "emotion": "happy",
         "emotion_scores": [{"label": "happy", "score": 0.9}]},
        {"start": 3.0, "end": 3.4, "emotion": "neutral",  # 0.4 s → inherit
         "emotion_scores": [{"label": "neutral", "score": 0.3}]},
        {"start": 3.5, "end": 7.5, "emotion": "sad",      # 4 s → keep
         "emotion_scores": [{"label": "sad", "score": 0.85}]},
        {"start": 7.5, "end": 8.2, "emotion": "neutral",  # 0.7 s → inherit
         "emotion_scores": [{"label": "neutral", "score": 0.3}]},
    ]
    out = ip.apply_emotion_min_duration_gate([dict(s) for s in segments], min_secs=1.0)
    assert [s["emotion"] for s in out] == ["happy", "happy", "sad", "sad"]
    assert out[1].get("_emotion_inherited") is True
    assert out[1].get("_emotion_original") == "neutral"
    assert "_emotion_inherited" not in out[0]
    assert "_emotion_inherited" not in out[2]


def test_emotion_min_duration_gate_first_segment_has_no_prior():
    """When the first segment is itself sub-threshold there is nothing to
    inherit from — it must keep its own emotion (or 'neutral' default).
    """
    segments = [
        {"start": 0.0, "end": 0.3, "emotion": "neutral",
         "emotion_scores": [{"label": "neutral", "score": 0.2}]},
    ]
    out = ip.apply_emotion_min_duration_gate([dict(s) for s in segments], min_secs=1.0)
    assert out[0]["emotion"] == "neutral"
    assert "_emotion_inherited" not in out[0]


def test_emotion_min_duration_gate_disabled_when_threshold_zero():
    segments = [
        {"start": 0.0, "end": 3.0, "emotion": "happy", "emotion_scores": []},
        {"start": 3.0, "end": 3.2, "emotion": "neutral", "emotion_scores": []},
    ]
    out = ip.apply_emotion_min_duration_gate([dict(s) for s in segments], min_secs=0.0)
    assert [s["emotion"] for s in out] == ["happy", "neutral"]


@pytest.mark.asyncio
async def test_mark_interaction_failed_stage_status_transaction_rolls_back_on_mid_loop_failure(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'interaction-failed-rollback.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    session = Session(engine)

    org_id = uuid4()
    manager_id = uuid4()
    agent_id = uuid4()
    interaction_id = uuid4()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    session.add(Organization(id=org_id, name="Org", slug="org", created_at=now))
    session.add(
        User(
            id=manager_id,
            organization_id=org_id,
            email="manager@org.local",
            password_hash="hash",
            name="Manager",
            role=UserRole.manager,
            is_active=True,
        )
    )
    session.add(
        User(
            id=agent_id,
            organization_id=org_id,
            email="agent@org.local",
            password_hash="hash",
            name="Agent",
            role=UserRole.agent,
            is_active=True,
        )
    )
    session.add(
        Interaction(
            id=interaction_id,
            organization_id=org_id,
            agent_id=agent_id,
            uploaded_by=manager_id,
            audio_file_path=str(Path(tmp_path / "call.wav")),
            processing_status=ProcessingStatus.processing,
            duration_seconds=1,
            file_size_bytes=1,
            file_format="wav",
            interaction_date=now,
        )
    )
    for stage in ip.STAGE_ORDER:
        session.add(
            ProcessingJob(
                interaction_id=interaction_id,
                stage=stage,
                status=JobStatus.pending,
            )
        )
    session.commit()

    original_set_job_status = ip._set_job_status
    call_counter = {"n": 0}

    async def _exploding_set_job_status(session_obj, interaction_id_obj, stage, status, error_message=None):
        await original_set_job_status(session_obj, interaction_id_obj, stage, status, error_message)
        if status == JobStatus.failed:
            call_counter["n"] += 1
            if call_counter["n"] == 3:
                raise RuntimeError("simulated mid-loop failure")

    monkeypatch.setattr(
        ip,
        "AsyncSession",
        lambda *args, **kwargs: AsyncSessionAdapter(session),
    )
    monkeypatch.setattr(ip, "engine", SimpleNamespace())
    monkeypatch.setattr(ip, "_set_job_status", _exploding_set_job_status)

    with pytest.raises(RuntimeError, match="simulated mid-loop failure"):
        await ip.mark_interaction_failed(interaction_id, "boom")

    jobs = session.exec(
        select(ProcessingJob).where(ProcessingJob.interaction_id == interaction_id)
    ).all()
    assert all(job.status == JobStatus.pending for job in jobs)
