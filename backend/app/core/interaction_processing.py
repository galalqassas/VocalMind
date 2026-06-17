from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.routes.full.service import full_client
from app.api.routes.transcription.service import transcription_client
from app.core.audio_resolver import fetch_audio_bytes
from app.core.config import settings
from app.core.database import engine
from app.core.emotion_fusion import build_deterministic_emotion_analysis
from app.core.notification_service import emit, emit_to_managers
from app.core.inference_contracts import (
    audio_content_type,
    build_local_full_response,
    is_supported_audio_filename,
)
from app.core.speaker_role_infer import relabel_segments_with_speaker_model
from app.llm_trigger.service import evaluate_interaction_triggers
from app.models.emotion_event import EmotionEvent
from app.models.enums import JobStage, JobStatus, NotificationType, ProcessingStatus, SpeakerRole
from app.models.interaction import Interaction
from app.models.interaction_score import InteractionScore
from app.models.llm_trigger_cache import InteractionLLMTriggerCache
from app.models.organization import Organization
from app.models.policy import CompanyPolicy, OrganizationPolicy, PolicyCompliance
from app.models.processing import ProcessingJob
from app.models.transcript import Transcript
from app.models.user import User
from app.models.utterance import Utterance


logger = logging.getLogger(__name__)

_processing_queue: asyncio.Queue[UUID | None] | None = None
_worker_task: asyncio.Task[None] | None = None

STAGE_ORDER: tuple[JobStage, ...] = (
    JobStage.diarization,
    JobStage.stt,
    JobStage.emotion,
    JobStage.reasoning,
    JobStage.scoring,
    JobStage.rag_eval,
)


def _deterministic_emotion_analysis(text: str) -> dict:
    return build_deterministic_emotion_analysis(text)


def _emotion_min_segment_secs() -> float:
    try:
        return max(0.0, float(os.getenv("EMOTION_MIN_SEGMENT_SECS", "1.0")))
    except (TypeError, ValueError):
        return 1.0


def apply_emotion_min_duration_gate(
    segments: list[dict[str, Any]],
    min_secs: float | None = None,
) -> list[dict[str, Any]]:
    """Inherit the previous segment's emotion for very short segments.

    Why: emotion2vec on sub-1s clips returns low-confidence "neutral" labels
    that drag the call-level distribution toward neutral. Inheriting from
    the prior segment keeps the per-utterance emotion sticky across short
    interjections while preserving real transitions on substantive turns.

    How to apply: mutates segments **in place** whose duration < threshold AND
    for which a prior segment exists. Stores the pre-gate value under
    `_emotion_original` and sets `_emotion_inherited=True` for telemetry. The
    inherited `emotion_scores` are shallow-copied to keep segments independent.
    Returns the same list for caller convenience.
    """
    threshold = _emotion_min_segment_secs() if min_secs is None else max(0.0, min_secs)
    if threshold <= 0.0 or not segments:
        return segments
    prev_emotion: str | None = None
    prev_scores: list[dict[str, Any]] | None = None
    for seg in segments:
        try:
            start = float(seg.get("start") or 0.0)
            end = float(seg.get("end") or 0.0)
        except (TypeError, ValueError):
            start, end = 0.0, 0.0
        duration = max(0.0, end - start)
        current = (seg.get("emotion") or "").strip() or None
        if duration < threshold and prev_emotion:
            if current and current != prev_emotion:
                seg["_emotion_original"] = current
                seg["_emotion_inherited"] = True
            seg["emotion"] = prev_emotion
            if prev_scores is not None:
                # Shallow-copy to keep segments independent — preserves the
                # invariant that mutating one segment's emotion_scores does
                # not affect others.
                seg["emotion_scores"] = list(prev_scores)
        else:
            if current:
                prev_emotion = current
                raw_scores = seg.get("emotion_scores")
                if raw_scores:
                    prev_scores = list(raw_scores)
    return segments


def _storage_root() -> Path:
    return Path(settings.LOCAL_AUDIO_STORAGE_DIR)


def _sanitize_filename(filename: str) -> str:
    cleaned = Path(filename or "").name.strip()
    return cleaned or f"audio_{datetime.now(timezone.utc).timestamp():.0f}.wav"


def _normalize_lookup_text(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _format_processing_exception(exc: Exception) -> str:
    detail = str(exc).strip()
    name = exc.__class__.__name__
    if detail:
        return f"{name}: {detail}"
    return name


async def _resolve_policy_record_for_report(
    session: AsyncSession,
    organization_id: UUID,
    report,
) -> CompanyPolicy | None:
    policies_result = await session.exec(
        select(CompanyPolicy)
        .join(OrganizationPolicy, OrganizationPolicy.policy_id == CompanyPolicy.id)
        .where(
            OrganizationPolicy.organization_id == organization_id,
            OrganizationPolicy.is_active.is_(True),
            CompanyPolicy.is_active.is_(True),
        )
    )
    policies = list(policies_result.all())
    if not policies:
        return None

    policy_quotes = [
        _normalize_lookup_text(citation.quote)
        for citation in report.nli_policy.citations
        if citation.source == "policy" and (citation.quote or "").strip()
    ]
    reference_hints: list[str] = []
    for claim in report.explainability.claim_provenance:
        if not claim.retrieved_policy:
            continue
        reference_hints.append(_normalize_lookup_text(claim.retrieved_policy.reference))
        if claim.retrieved_policy.provenance:
            reference_hints.append(_normalize_lookup_text(claim.retrieved_policy.provenance))

    best_policy: CompanyPolicy | None = None
    best_score = -1
    for policy in policies:
        title_norm = _normalize_lookup_text(policy.policy_title)
        text_norm = _normalize_lookup_text(policy.policy_text)
        title_tokens = set(title_norm.split())
        score = 0

        for quote in policy_quotes:
            if quote and quote in text_norm:
                score += 8

        for hint in reference_hints:
            if not hint:
                continue
            hint_tokens = set(hint.split())
            score += len(hint_tokens.intersection(title_tokens)) * 2
            if hint in title_norm or title_norm in hint:
                score += 4

        if score > best_score:
            best_score = score
            best_policy = policy

    return best_policy or policies[0]


def build_audio_storage_path(organization_slug: str, interaction_id: UUID, filename: str) -> Path:
    return _storage_root() / organization_slug / str(interaction_id) / _sanitize_filename(filename)


async def save_audio_upload(organization_slug: str, interaction_id: UUID, filename: str, content: bytes) -> Path:
    target_path = build_audio_storage_path(organization_slug, interaction_id, filename)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(content)
    return target_path.resolve()


# Weighted phrase tables for content-based speaker role inference.
# Diarization (WhisperX/PyAnnote) clusters voices into arbitrary IDs (SPEAKER_00,
# SPEAKER_01); the cluster IDs carry no role semantics. We score each cluster's
# accumulated text against these phrase lists to decide which cluster is the
# agent and which is the customer.
_AGENT_PHRASE_WEIGHTS: tuple[tuple[str, int], ...] = (
    # Strong scripted openings/closings (call-center signature)
    ("thank you for calling", 10),
    ("thanks for calling", 10),
    ("is there anything else i can help", 10),
    ("welcome to", 8),
    ("how can i help", 8),
    ("how may i help", 8),
    ("how can i assist", 8),
    ("case reference", 8),
    # Strong agent phrasing — verification script (high precision)
    ("i'll need to verify", 8),
    ("could you please confirm", 8),
    ("could you please verify", 8),
    ("could you confirm the", 7),
    ("can you confirm the", 7),
    ("for security purposes", 7),
    ("for security reasons", 7),
    ("let me pull up", 6),
    ("let me look up", 6),
    ("my name is", 6),
    ("i can help you", 6),
    ("i can assist", 6),
    ("your case", 6),
    ("case number", 6),
    ("i'm sorry to hear", 5),
    ("please verify", 5),
    ("for verification", 5),
    # Possessive flips — agent talks about the CUSTOMER's account
    ("your account", 4),
    ("your bill", 4),
    ("your service", 4),
    ("your name", 3),
    ("on file", 4),
    ("let me check", 3),
    ("i understand", 3),
    ("i apologize", 4),
)
_CUSTOMER_PHRASE_WEIGHTS: tuple[tuple[str, int], ...] = (
    ("i need help", 8),
    ("i was charged", 8),
    ("i want a credit", 8),
    # Refund / dispute openers — high-precision customer signals
    ("i'd like a refund", 8),
    ("i want a refund", 8),
    ("i want my money back", 8),
    ("i was overcharged", 8),
    ("i didn't authorize", 8),
    ("i didn't make this", 7),
    ("this is unacceptable", 6),
    ("this charge is wrong", 7),
    ("are you serious", 6),
    ("i'm calling because", 6),
    ("cannot access", 6),
    # Possessive flips — customer talks about THEIR OWN things
    ("my bill", 6),
    ("my internet", 6),
    ("my service", 6),
    ("my account", 4),
    ("i can't", 5),
    ("i cannot", 5),
    ("i want to", 4),
    ("i need to", 3),
)


_lr_model = None
_lr_vectorizer = None


def _load_lr_model_and_vectorizer():
    global _lr_model, _lr_vectorizer
    if _lr_model is None:
        try:
            import joblib
            core_dir = Path(__file__).parent
            model_path = core_dir / "model.pkl"
            vectorizer_path = core_dir / "vectorizer.pkl"
            if model_path.exists() and vectorizer_path.exists():
                _lr_model = joblib.load(model_path)
                _lr_vectorizer = joblib.load(vectorizer_path)
                logger.info("Successfully loaded Logistic Regression model and vectorizer for speaker classification.")
        except Exception as e:
            logger.warning("Failed to load Logistic Regression model or vectorizer: %s", e)


def assign_cluster_roles_from_text(
    segments: list[dict[str, Any]],
    agent_name: str | None = None,
) -> dict[str, SpeakerRole]:
    """Decide which raw diarization clusters are agent vs customer based on content.

    Uses a trained Logistic Regression model and TF-IDF vectorizer if available,
    falling back to heuristic phrase-matching.
    """
    cluster_texts: dict[str, list[str]] = {}
    cluster_first_seen: dict[str, float] = {}
    for segment in segments:
        raw = (segment.get("speaker") or "").strip()
        if not raw or raw.lower() in {"agent", "customer"}:
            continue
        cluster_texts.setdefault(raw, []).append((segment.get("text") or "").strip().lower())
        start = float(segment.get("start") or 0.0)
        if raw not in cluster_first_seen or start < cluster_first_seen[raw]:
            cluster_first_seen[raw] = start

    if not cluster_texts:
        return {}

    _load_lr_model_and_vectorizer()
    if _lr_model is not None and _lr_vectorizer is not None:
        if len(cluster_texts) == 1:
            cluster, texts = next(iter(cluster_texts.items()))
            probabilities = []
            for text in texts:
                text_clean = text.strip()
                if not text_clean:
                    continue
                feat = _lr_vectorizer.transform([text_clean])
                prob_agent = float(_lr_model.predict_proba(feat)[0][1])
                probabilities.append(prob_agent)
            prob = sum(probabilities) / len(probabilities) if probabilities else 0.5
            return {cluster: SpeakerRole.agent if prob >= 0.5 else SpeakerRole.customer}

    name_norm = (agent_name or "").strip().lower()

    # First-speaker prior: in inbound call-center audio, the agent answers
    # the line first. Whichever cluster owns the earliest segment within the
    # first 8s of audio gets a strong agent prior regardless of what they say.
    earliest_cluster: str | None = None
    earliest_start: float = float("inf")
    for cluster, start in cluster_first_seen.items():
        if start < earliest_start:
            earliest_start = start
            earliest_cluster = cluster
    if earliest_cluster is not None and earliest_start >= 8.0:
        earliest_cluster = None

    scores: dict[str, tuple[float, float]] = {}
    for cluster, texts in cluster_texts.items():
        joined = " ".join(texts)
        
        # 1. Base scores from ML and/or phrase weights
        a_base = 0.0
        c_base = 0.0
        if _lr_model is not None and _lr_vectorizer is not None:
            probabilities = []
            for text in texts:
                text_clean = text.strip()
                if not text_clean:
                    continue
                feat = _lr_vectorizer.transform([text_clean])
                prob_agent = float(_lr_model.predict_proba(feat)[0][1])
                probabilities.append(prob_agent)
            a_base += sum(5.0 * p for p in probabilities)
            c_base += sum(5.0 * (1.0 - p) for p in probabilities)

        # Always add phrase weights as reinforcement
        a_base += float(sum(weight for phrase, weight in _AGENT_PHRASE_WEIGHTS if phrase in joined))
        c_base += float(sum(weight for phrase, weight in _CUSTOMER_PHRASE_WEIGHTS if phrase in joined))

        # 2. Heuristic rules adjustments
        agent_score = a_base
        customer_score = c_base

        # Self-introduction with the known agent name is a near-decisive signal.
        if name_norm and name_norm not in {"agent", "customer"}:
            if f"my name is {name_norm}" in joined or f"this is {name_norm}" in joined:
                agent_score += 15.0

        # Whoever opens the call with the scripted greeting is the agent.
        if cluster_first_seen.get(cluster, float("inf")) < 15.0 and (
            "thank you for calling" in joined
            or "thanks for calling" in joined
            or "welcome to" in joined
        ):
            agent_score += 10.0

        # First-speaker prior — anchors agent role even on mistranscribed greetings.
        if cluster == earliest_cluster:
            agent_score += 12.0

        scores[cluster] = (agent_score, customer_score)

    # Single-cluster audio: pick role by sign of (agent − customer).
    if len(scores) == 1:
        cluster, (a, c) = next(iter(scores.items()))
        return {cluster: SpeakerRole.agent if a >= c else SpeakerRole.customer}

    # Multi-cluster: cluster with lowest net agent score is the customer; the rest are agents.
    nets = {cluster: a - c for cluster, (a, c) in scores.items()}
    # Tie-break: cluster speaking earlier wins agent, i.e., prefer the later speaker for customer.
    customer_cluster = min(
        nets,
        key=lambda k: (nets[k], -cluster_first_seen.get(k, 0.0)),
    )

    return {
        cluster: SpeakerRole.customer if cluster == customer_cluster else SpeakerRole.agent
        for cluster in cluster_texts
    }

def _speaker_role_from_label(
    label: str | None,
    *,
    cluster_map: dict[str, SpeakerRole],
    default: SpeakerRole = SpeakerRole.customer,
) -> SpeakerRole:
    """Resolve a single segment's role.

    Priority:
      1. Explicit "agent"/"customer" labels (e.g. set by the DistilBERT
         relabel pass) win as-is.
      2. Cluster map decision from ``assign_cluster_roles_from_text``.
      3. Caller-supplied default.
    """
    if not label:
        return default
    raw = label.strip()
    if not raw:
        return default
    normalized = raw.lower()
    if normalized == "agent":
        return SpeakerRole.agent
    if normalized == "customer":
        return SpeakerRole.customer
    if raw in cluster_map:
        return cluster_map[raw]
    return cluster_map.get(normalized, default)


async def create_processing_jobs(session: AsyncSession, interaction_id: UUID) -> None:
    existing_result = await session.exec(
        select(ProcessingJob.stage).where(ProcessingJob.interaction_id == interaction_id)
    )
    existing_stages = set(existing_result.all())

    for stage in STAGE_ORDER:
        if stage in existing_stages:
            continue
        session.add(ProcessingJob(interaction_id=interaction_id, stage=stage, status=JobStatus.pending))


async def _set_job_status(
    session: AsyncSession,
    interaction_id: UUID,
    stage: JobStage,
    status: JobStatus,
    error_message: str | None = None,
) -> None:
    result = await session.exec(
        select(ProcessingJob).where(
            ProcessingJob.interaction_id == interaction_id,
            ProcessingJob.stage == stage,
        )
    )
    job = result.first()
    if not job:
        job = ProcessingJob(interaction_id=interaction_id, stage=stage)
        session.add(job)

    job.status = status
    if status == JobStatus.running and not job.started_at:
        job.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if status == JobStatus.completed:
        job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        job.error_message = None
    if status == JobStatus.failed:
        job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        job.error_message = error_message

async def _set_interaction_status(session: AsyncSession, interaction_id: UUID, status: ProcessingStatus) -> None:
    interaction = await session.get(Interaction, interaction_id)
    if not interaction:
        return
    interaction.processing_status = status
    session.add(interaction)


async def enqueue_interaction_processing(interaction_id: UUID) -> None:
    if _processing_queue is None:
        raise RuntimeError("Processing worker has not been started")
    await _processing_queue.put(interaction_id)


async def _enqueue_pending_interactions_backlog() -> None:
    """Put every DB-pending interaction on the in-memory queue (e.g. after a restart)."""
    if _processing_queue is None:
        return
    async with AsyncSession(engine, expire_on_commit=False) as session:
        res = await session.exec(
            select(Interaction.id).where(Interaction.processing_status == ProcessingStatus.pending)
        )
        pending_ids = list(res.all())
    for iid in pending_ids:
        await enqueue_interaction_processing(iid)
    if pending_ids:
        logger.info("Enqueued %d pending interaction(s) for processing backlog", len(pending_ids))


async def start_processing_worker() -> None:
    global _worker_task, _processing_queue
    if _worker_task and not _worker_task.done():
        return
    _processing_queue = asyncio.Queue()
    _worker_task = asyncio.create_task(_worker_loop(), name="interaction-processing-worker")
    await _enqueue_pending_interactions_backlog()


async def stop_processing_worker() -> None:
    global _worker_task, _processing_queue
    if not _worker_task or _processing_queue is None:
        return
    await _processing_queue.put(None)
    try:
        await _worker_task
    except asyncio.CancelledError:
        pass
    finally:
        _worker_task = None
        _processing_queue = None


async def _worker_loop() -> None:
    if _processing_queue is None:
        return
    while True:
        interaction_id = await _processing_queue.get()
        try:
            if interaction_id is None:
                return
            await process_interaction(interaction_id)
        except Exception as exc:
            logger.exception("Interaction processing worker failed for %s", interaction_id)
            if interaction_id is not None:
                await mark_interaction_failed(interaction_id, _format_processing_exception(exc))
        finally:
            _processing_queue.task_done()


async def interaction_has_active_jobs(session: AsyncSession, interaction_id: UUID) -> bool:
    jobs_result = await session.exec(
        select(ProcessingJob).where(ProcessingJob.interaction_id == interaction_id)
    )
    for job in jobs_result.all():
        if job.status in {JobStatus.pending, JobStatus.running}:
            return True
    return False


async def reset_interaction_for_reprocess(session: AsyncSession, interaction_id: UUID) -> None:
    """Reset full processing artifacts and job stages for a clean re-run."""
    await session.exec(delete(EmotionEvent).where(EmotionEvent.interaction_id == interaction_id))
    await session.exec(delete(Utterance).where(Utterance.interaction_id == interaction_id))
    await session.exec(delete(PolicyCompliance).where(PolicyCompliance.interaction_id == interaction_id))
    await session.exec(delete(InteractionScore).where(InteractionScore.interaction_id == interaction_id))
    await session.exec(delete(InteractionLLMTriggerCache).where(InteractionLLMTriggerCache.interaction_id == interaction_id))

    transcript_result = await session.exec(
        select(Transcript).where(Transcript.interaction_id == interaction_id)
    )
    transcript = transcript_result.first()
    if transcript:
        transcript.full_text = ""
        transcript.overall_confidence = None
        session.add(transcript)

    jobs_result = await session.exec(
        select(ProcessingJob).where(ProcessingJob.interaction_id == interaction_id)
    )
    jobs = jobs_result.all()
    existing_stages = {job.stage for job in jobs}

    for stage in STAGE_ORDER:
        if stage in existing_stages:
            continue
        session.add(ProcessingJob(interaction_id=interaction_id, stage=stage, status=JobStatus.pending))

    for job in jobs:
        job.status = JobStatus.pending
        job.error_message = None
        job.started_at = None
        job.completed_at = None
        job.retry_count = 0
        session.add(job)

    interaction = await session.get(Interaction, interaction_id)
    if interaction:
        interaction.processing_status = ProcessingStatus.pending
        session.add(interaction)

    await session.commit()


async def _analyze_audio_for_interaction(
    interaction_id: UUID,
    audio_bytes: bytes,
    filename: str,
) -> dict:
    try:
        return await full_client.analyze_bytes(
            audio_bytes,
            filename,
            audio_content_type(filename),
        )
    except Exception:
        if not settings.IS_LOCAL:
            raise
        logger.exception(
            "Full analysis failed for %s; using transcription-only fallback",
            interaction_id,
        )
        try:
            transcription = await transcription_client.analyze_bytes(
                audio_bytes,
                filename,
                audio_content_type(filename),
            )
        except Exception:
            logger.exception(
                "Transcription fallback failed for %s; using deterministic minimal transcript",
                interaction_id,
            )
            transcription = {
                "language": "en",
                "text": "",
                "segments": [
                    {
                        "start": 0.0,
                        "end": 1.0,
                        "text": "",
                        "speaker": "customer",
                        "overlap": False,
                    }
                ],
                "processing_time_s": 0.0,
            }
        return build_local_full_response(
            transcription,
            _deterministic_emotion_analysis(transcription.get("text") or ""),
        )


async def process_interaction(interaction_id: UUID) -> None:
    """Run pipeline: short DB claim → release pool during slow I/O → persist."""
    audio_path: str
    async with AsyncSession(engine, expire_on_commit=False) as session:
        interaction = await session.get(Interaction, interaction_id)
        if not interaction:
            logger.warning("Skipping missing interaction %s", interaction_id)
            return

        if interaction.processing_status == ProcessingStatus.completed:
            logger.info("Skipping interaction %s (already completed)", interaction_id)
            return

        try:
            await _set_job_status(session, interaction_id, JobStage.diarization, JobStatus.running)
            await _set_job_status(session, interaction_id, JobStage.stt, JobStatus.running)
            await _set_job_status(session, interaction_id, JobStage.emotion, JobStatus.running)
            await _set_interaction_status(session, interaction_id, ProcessingStatus.processing)
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        audio_path = interaction.audio_file_path

    audio_bytes, filename = await fetch_audio_bytes(audio_path)
    if not is_supported_audio_filename(filename):
        raise ValueError(f"Unsupported audio file: {filename}")

    analysis = await _analyze_audio_for_interaction(interaction_id, audio_bytes, filename)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        interaction = await session.get(Interaction, interaction_id)
        if not interaction:
            logger.warning("Interaction %s removed during processing", interaction_id)
            return
        if interaction.processing_status == ProcessingStatus.completed:
            logger.info("Skipping interaction %s (completed concurrently)", interaction_id)
            return

        await session.exec(delete(EmotionEvent).where(EmotionEvent.interaction_id == interaction_id))
        await session.exec(delete(Utterance).where(Utterance.interaction_id == interaction_id))
        await session.exec(delete(PolicyCompliance).where(PolicyCompliance.interaction_id == interaction_id))
        await session.exec(delete(InteractionScore).where(InteractionScore.interaction_id == interaction_id))
        await session.exec(delete(InteractionLLMTriggerCache).where(InteractionLLMTriggerCache.interaction_id == interaction_id))

        transcript_result = await session.exec(
            select(Transcript).where(Transcript.interaction_id == interaction_id)
        )
        transcript = transcript_result.first() or Transcript(interaction_id=interaction_id)

        segments = analysis.get("segments", []) or []
        segments = relabel_segments_with_speaker_model([dict(s) for s in segments])
        segments = apply_emotion_min_duration_gate(segments)
        agent_user = await session.get(User, interaction.agent_id) if interaction.agent_id else None
        agent_name = agent_user.name if agent_user else None
        cluster_role_map = assign_cluster_roles_from_text(segments, agent_name)
        transcript_text = (analysis.get("text") or "").strip()
        if not transcript_text:
            transcript_text = " ".join((segment.get("text") or "").strip() for segment in segments).strip()

        transcript.full_text = transcript_text
        transcript.overall_confidence = float(analysis.get("top_score") or 0.0)
        session.add(transcript)
        await session.flush()

        utterances: list[Utterance] = []
        for index, segment in enumerate(segments):
            speaker_role = _speaker_role_from_label(
                segment.get("speaker"),
                cluster_map=cluster_role_map,
                default=SpeakerRole.agent if index == 0 else SpeakerRole.customer,
            )
            emotion_scores = segment.get("emotion_scores") or []
            emotion_confidence = 0.0
            if emotion_scores:
                emotion_confidence = float(emotion_scores[0].get("score") or 0.0)

            utterance = Utterance(
                interaction_id=interaction_id,
                transcript_id=transcript.id,
                speaker_role=speaker_role,
                user_id=interaction.agent_id if speaker_role == SpeakerRole.agent else None,
                sequence_index=index,
                start_time_seconds=float(segment.get("start") or 0.0),
                end_time_seconds=float(segment.get("end") or 0.0),
                text=(segment.get("text") or "").strip(),
                emotion=(segment.get("emotion") or "neutral").strip() or "neutral",
                emotion_confidence=emotion_confidence,
            )
            utterances.append(utterance)
            session.add(utterance)

        await session.flush()

        previous_emotion: str | None = None
        for utterance in utterances:
            current_emotion = utterance.emotion or "neutral"
            if previous_emotion is None:
                previous_emotion = current_emotion
                continue
            if current_emotion == previous_emotion:
                continue

            session.add(
                EmotionEvent(
                    interaction_id=interaction_id,
                    utterance_id=utterance.id,
                    previous_emotion=previous_emotion,
                    new_emotion=current_emotion,
                    emotion_delta=1.0,
                    speaker_role=utterance.speaker_role or SpeakerRole.customer,
                    llm_justification=f"Emotion changed from {previous_emotion} to {current_emotion}.",
                    jump_to_seconds=utterance.start_time_seconds,
                    confidence_score=utterance.emotion_confidence,
                )
            )
            previous_emotion = current_emotion

        organization_result = await session.exec(
            select(Organization).where(Organization.id == interaction.organization_id)
        )
        organization = organization_result.first()

        report = None
        if organization:
            try:
                report = await asyncio.wait_for(
                    evaluate_interaction_triggers(
                        session=session,
                        interaction_id=interaction_id,
                        org_filter=organization.slug,
                        requester_organization_id=interaction.organization_id,
                        force_rerun=True,
                    ),
                    timeout=float(os.getenv("LLM_TRIGGER_EVAL_TIMEOUT_SECONDS", "600")),
                )
            except TimeoutError:
                logger.error(
                    "LLM trigger evaluation timed out after %ss for interaction %s",
                    os.getenv("LLM_TRIGGER_EVAL_TIMEOUT_SECONDS", "600"),
                    interaction_id,
                )
            except Exception:
                logger.exception("LLM trigger evaluation failed for interaction %s", interaction_id)

        if report:
            policy = await _resolve_policy_record_for_report(
                session=session,
                organization_id=interaction.organization_id,
                report=report,
            )
            compliance_score = max(0.0, min(1.0, float(report.process_adherence.efficiency_score) / 10.0))
            policy_alignment = report.nli_policy.policy_alignment_score
            if policy_alignment is None:
                policy_alignment = 1.0 if report.nli_policy.nli_category in {"Entailment", "Benign Deviation"} else 0.35
            policy_score = max(0.0, min(1.0, (compliance_score * 0.55) + (float(policy_alignment) * 0.45)))

            if report.emotion_shift.is_dissonance_detected:
                empathy_score = 0.55
            elif report.emotion_shift.insufficient_evidence:
                empathy_score = 0.82
            else:
                empathy_score = 0.95

            if report.process_adherence.is_resolved:
                resolution_score = 0.94 if not report.process_adherence.missing_sop_steps else 0.84
            else:
                resolution_score = 0.42

            overall_score = round(
                (empathy_score * 0.3) + (policy_score * 0.4) + (resolution_score * 0.3),
                4,
            )
            evidence_text = "; ".join(
                quote for quote in (
                    report.process_adherence.evidence_quotes[:1] + report.nli_policy.evidence_quotes[:1]
                )
                if quote
            ) or transcript_text[:250]

            if policy:
                is_compliant = report.nli_policy.nli_category in {"Entailment", "Benign Deviation"}
                transcript_policy_degraded = bool(
                    report.nli_policy.insufficient_evidence
                    or report.process_adherence.insufficient_evidence
                )
                session.add(
                    PolicyCompliance(
                        interaction_id=interaction_id,
                        policy_id=policy.id,
                        is_compliant=is_compliant,
                        compliance_score=compliance_score,
                        degraded=transcript_policy_degraded,
                        llm_reasoning=report.nli_policy.justification or report.process_adherence.justification,
                        evidence_text=evidence_text,
                        retrieved_policy_text=policy.policy_text,
                    )
                )

            session.add(
                InteractionScore(
                    interaction_id=interaction_id,
                    overall_score=overall_score,
                    empathy_score=empathy_score,
                    policy_score=policy_score,
                    resolution_score=resolution_score,
                    total_silence_seconds=0.0,
                    avg_response_time_seconds=1.0,
                    was_resolved=report.process_adherence.is_resolved,
                )
            )
        else:
            session.add(
                InteractionScore(
                    interaction_id=interaction_id,
                    overall_score=0.7,
                    empathy_score=0.7,
                    policy_score=0.7,
                    resolution_score=0.7,
                    total_silence_seconds=0.0,
                    avg_response_time_seconds=1.0,
                    was_resolved=False,
                )
            )

        interaction.language_detected = (analysis.get("language") or interaction.language_detected or "en")[:10]
        interaction.duration_seconds = int(max((float(seg.get("end") or 0.0) for seg in segments), default=interaction.duration_seconds or 0))
        interaction.processing_status = ProcessingStatus.completed
        session.add(interaction)

        await session.commit()

        try:
            for stage in STAGE_ORDER:
                await _set_job_status(session, interaction_id, stage, JobStatus.completed)
            await session.commit()
        except Exception:
            await session.rollback()
            raise

        # Notify the agent and managers that the call finished evaluation.
        try:
            score_row = (await session.exec(
                select(InteractionScore).where(InteractionScore.interaction_id == interaction_id)
            )).first()
            score_pct = int(round((score_row.overall_score or 0.0) * 100)) if score_row else None
            body = (
                f"Evaluation finished. Overall score {score_pct}."
                if score_pct is not None
                else "Evaluation finished."
            )
            if interaction.agent_id:
                await emit(
                    session,
                    recipient_user_id=interaction.agent_id,
                    organization_id=interaction.organization_id,
                    type=NotificationType.evaluation_complete,
                    title="Call evaluation complete",
                    body=body,
                    link_url=f"/agent/calls/{interaction_id}",
                    payload={"interaction_id": str(interaction_id)},
                )
            await emit_to_managers(
                session,
                organization_id=interaction.organization_id,
                type=NotificationType.evaluation_complete,
                title="Call evaluation complete",
                body=body,
                link_url=f"/manager/inspector/{interaction_id}",
                payload={"interaction_id": str(interaction_id)},
            )
            await session.commit()
        except Exception:
            logger.exception("Failed to emit evaluation_complete notification for %s", interaction_id)


async def mark_interaction_failed(interaction_id: UUID, error_message: str) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        try:
            interaction = await session.get(Interaction, interaction_id)
            if interaction:
                interaction.processing_status = ProcessingStatus.failed
                session.add(interaction)

            for stage in STAGE_ORDER:
                await _set_job_status(session, interaction_id, stage, JobStatus.failed, error_message)
            await session.commit()
        except Exception:
            await session.rollback()
            raise
