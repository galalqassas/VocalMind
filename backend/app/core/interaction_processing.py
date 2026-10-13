from __future__ import annotations

import asyncio
import logging
import httpx
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote as url_quote
from uuid import UUID

from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.routes.full.service import full_client
from app.core.audio_resolver import audio_media_type_from_path, fetch_audio_bytes
from app.core.config import settings
from app.core.database import engine
from app.core.notification_service import emit, emit_to_managers
from app.core.inference_contracts import (
    audio_content_type,
    is_supported_audio_filename,
)
from app.core.policy_violation_mapping import (
    ViolationMappingInput,
    derive_violation_specs,
    ensure_organization_policies_from_source,
    persist_policy_violations,
)
from app.llm_trigger.chains import is_gibberish
from app.llm_trigger.scoring import compute_scores
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
from app.models.utterance import Utterance


logger = logging.getLogger(__name__)

_processing_queue: asyncio.Queue[UUID | None] | None = None
_priority_queue: asyncio.Queue[UUID] | None = None
_worker_task: asyncio.Task[None] | None = None

STAGE_ORDER: tuple[JobStage, ...] = (
    JobStage.diarization,
    JobStage.stt,
    JobStage.emotion,
    JobStage.reasoning,
    JobStage.scoring,
    JobStage.rag_eval,
)


class StageFailed(RuntimeError):
    """A pipeline stage failed; ``stages`` are the ProcessingJobs to mark failed."""

    def __init__(self, stages: tuple[JobStage, ...], message: str):
        super().__init__(message)
        self.stages = stages


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
        if current == "unknown":
            current = None
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


class AudioStorageError(RuntimeError):
    pass


def build_audio_storage_path(organization_slug: str, interaction_id: UUID, filename: str) -> Path:
    return _storage_root() / organization_slug / str(interaction_id) / _sanitize_filename(filename)


def build_supabase_audio_object_path(organization_slug: str, interaction_id: UUID, filename: str) -> str:
    return f"{organization_slug}/{interaction_id}/{_sanitize_filename(filename)}"


def _audio_storage_backend() -> str:
    return (settings.AUDIO_STORAGE_BACKEND or "local").strip().lower()


async def upload_supabase_audio_object(object_path: str, filename: str, content: bytes) -> str:
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY or not settings.SUPABASE_AUDIO_BUCKET:
        raise AudioStorageError(
            "AUDIO_STORAGE_BACKEND=supabase requires SUPABASE_URL, "
            "SUPABASE_SERVICE_KEY, and SUPABASE_AUDIO_BUCKET."
        )

    bucket = settings.SUPABASE_AUDIO_BUCKET.strip("/")
    upload_url = (
        f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/object/"
        f"{url_quote(bucket, safe='')}/{url_quote(object_path, safe='/')}"
    )
    headers = {
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
        "apikey": settings.SUPABASE_SERVICE_KEY,
        "Content-Type": audio_media_type_from_path(filename),
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(upload_url, headers=headers, content=content, timeout=120.0)
    except httpx.RequestError as exc:
        raise AudioStorageError(f"Supabase audio upload failed: {exc.__class__.__name__}") from exc

    if response.status_code not in {200, 201}:
        detail = response.text[:300] if response.text else response.reason_phrase
        raise AudioStorageError(f"Supabase audio upload failed ({response.status_code}): {detail}")

    return f"{bucket}/{object_path}"


async def save_audio_upload(organization_slug: str, interaction_id: UUID, filename: str, content: bytes) -> Path | str:
    if _audio_storage_backend() == "supabase":
        object_path = build_supabase_audio_object_path(organization_slug, interaction_id, filename)
        return await upload_supabase_audio_object(object_path, filename, content)

    target_path = build_audio_storage_path(organization_slug, interaction_id, filename)
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)
    except OSError as exc:
        raise AudioStorageError(f"Local audio storage write failed: {exc.__class__.__name__}") from exc
    return target_path.resolve()


_lr_model = None
_lr_vectorizer = None


class SpeakerRoleModelUnavailable(RuntimeError):
    pass


def _load_lr_model_and_vectorizer():
    """Load the LR + TF-IDF agent/customer classifier (research/training/customerAgentClassifier.ipynb)."""
    global _lr_model, _lr_vectorizer
    if _lr_model is None:
        try:
            import joblib

            core_dir = Path(__file__).parent
            _lr_vectorizer = joblib.load(core_dir / "vectorizer.pkl")
            _lr_model = joblib.load(core_dir / "model.pkl")
        except Exception as exc:
            raise SpeakerRoleModelUnavailable(
                f"Speaker-role model failed to load: {_format_processing_exception(exc)}"
            ) from exc
    return _lr_model, _lr_vectorizer


def _agent_probabilities(texts: list[str]) -> list[float]:
    """P(agent) per text. The model was trained on single Taskmaster utterances (label 1 = agent)."""
    model, vectorizer = _load_lr_model_and_vectorizer()
    return [float(p) for p in model.predict_proba(vectorizer.transform(texts))[:, 1]]


def _explicit_role(segment: dict[str, Any]) -> SpeakerRole | None:
    """Upstream AGENT/CUSTOMER labels (WhisperX stereo channel diarization) are authoritative."""
    label = (segment.get("speaker") or "").strip().lower()
    return SpeakerRole(label) if label in {"agent", "customer"} else None


def _diarization_cluster(segment: dict[str, Any]) -> str | None:
    meta = segment.get("speaker_meta") or {}
    label = (meta.get("diarization_speaker") or segment.get("speaker") or "").strip()
    return label if label.upper().startswith("SPEAKER_") else None


def assign_speaker_roles(segments: list[dict[str, Any]]) -> list[SpeakerRole]:
    """Agent/customer role per segment.

    1. Explicit channel labels are kept as-is.
    2. Two or more diarization clusters: the cluster with the highest mean per-utterance
       P(agent) is the agent; every other cluster is the customer.
    3. Otherwise (diarization collapsed to one cluster or unavailable): per-segment LR.
    Raises ``SpeakerRoleModelUnavailable`` when the model cannot be loaded.
    """
    roles: list[SpeakerRole | None] = [_explicit_role(segment) for segment in segments]
    pending = [index for index, role in enumerate(roles) if role is None]
    if not pending:
        return roles  # type: ignore[return-value]

    texts = [(segments[index].get("text") or "").strip() for index in pending]
    probabilities = _agent_probabilities(texts)
    cluster_probs: dict[str, list[float]] = {}
    for index, text, prob in zip(pending, texts, probabilities):
        cluster = _diarization_cluster(segments[index])
        if cluster and text:
            cluster_probs.setdefault(cluster, []).append(prob)

    agent_cluster = (
        max(cluster_probs, key=lambda key: sum(cluster_probs[key]) / len(cluster_probs[key]))
        if len(cluster_probs) >= 2
        else None
    )
    for index, prob in zip(pending, probabilities):
        cluster = _diarization_cluster(segments[index])
        if agent_cluster and cluster:
            is_agent = cluster == agent_cluster
        else:
            is_agent = prob >= 0.5
        roles[index] = SpeakerRole.agent if is_agent else SpeakerRole.customer
    return roles  # type: ignore[return-value]


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


async def enqueue_interaction_processing(interaction_id: UUID, *, priority: bool = False) -> None:
    if _processing_queue is None or _priority_queue is None:
        raise RuntimeError("Processing worker has not been started")
    if priority:
        await _priority_queue.put(interaction_id)
    else:
        await _processing_queue.put(interaction_id)


async def _enqueue_pending_interactions_backlog() -> None:
    """Put every DB-pending interaction on the in-memory queue (e.g. after a restart)."""
    if _processing_queue is None:
        return
    async with AsyncSession(engine, expire_on_commit=False) as session:
        stuck_result = await session.exec(
            select(Interaction.id).where(Interaction.processing_status == ProcessingStatus.processing)
        )
        stuck_ids = list(stuck_result.all())
        for iid in stuck_ids:
            interaction = await session.get(Interaction, iid)
            if interaction:
                interaction.processing_status = ProcessingStatus.pending
                session.add(interaction)
        if stuck_ids:
            await session.commit()
            logger.warning(
                "Reset %d interaction(s) stuck in processing to pending after worker restart",
                len(stuck_ids),
            )

        res = await session.exec(
            select(Interaction.id).where(Interaction.processing_status == ProcessingStatus.pending)
        )
        pending_ids = list(res.all())
    for iid in pending_ids:
        await enqueue_interaction_processing(iid)
    if pending_ids:
        logger.info("Enqueued %d pending interaction(s) for processing backlog", len(pending_ids))


async def start_processing_worker() -> None:
    global _worker_task, _processing_queue, _priority_queue
    if _worker_task and not _worker_task.done():
        return
    _processing_queue = asyncio.Queue()
    _priority_queue = asyncio.Queue()
    _worker_task = asyncio.create_task(_worker_loop(), name="interaction-processing-worker")
    await _enqueue_pending_interactions_backlog()


async def stop_processing_worker() -> None:
    global _worker_task, _processing_queue, _priority_queue
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
        _priority_queue = None


async def _worker_loop() -> None:
    if _processing_queue is None or _priority_queue is None:
        return
    while True:
        # Always drain priority queue first before blocking on regular queue
        if not _priority_queue.empty():
            interaction_id = _priority_queue.get_nowait()
            from_priority = True
        else:
            try:
                # Block up to 1 second, then re-check priority queue
                interaction_id = await asyncio.wait_for(
                    _processing_queue.get(), timeout=1.0
                )
                from_priority = False
                # Sentinel None = shutdown signal
                if interaction_id is None:
                    if not _priority_queue.empty():
                        continue
                    return
            except asyncio.TimeoutError:
                # Woke up — loop back and check priority queue again
                continue
        try:
            await process_interaction(interaction_id)
        except StageFailed as exc:
            logger.error("Interaction %s failed at %s: %s", interaction_id, [s.value for s in exc.stages], exc)
            await mark_interaction_failed(interaction_id, str(exc), exc.stages)
        except Exception as exc:
            logger.exception("Interaction processing worker failed for %s", interaction_id)
            await mark_interaction_failed(interaction_id, _format_processing_exception(exc))
        finally:
            if not from_priority:
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

    audio_stages = (JobStage.diarization, JobStage.stt, JobStage.emotion)
    try:
        analysis = await full_client.analyze_bytes(audio_bytes, filename, audio_content_type(filename))
    except Exception as exc:
        raise StageFailed(audio_stages, f"Audio analysis failed: {_format_processing_exception(exc)}") from exc

    transcript_text = (analysis.get("text") or "").strip()
    if not transcript_text:
        transcript_text = " ".join(
            (segment.get("text") or "").strip()
            for segment in (analysis.get("segments") or [])
        ).strip()
    try:
        gibberish = await is_gibberish(transcript_text)
    except Exception as exc:
        raise StageFailed((JobStage.stt,), f"ASR quality check failed: {_format_processing_exception(exc)}") from exc
    if gibberish:
        raise StageFailed(
            (JobStage.stt,),
            "ASR quality gate failed: transcript is empty or gibberish. "
            "Check audio file format and WhisperX model availability.",
        )

    segments = apply_emotion_min_duration_gate([dict(s) for s in analysis.get("segments") or []])
    try:
        speaker_roles = assign_speaker_roles(segments)
    except SpeakerRoleModelUnavailable as exc:
        raise StageFailed((JobStage.diarization,), str(exc)) from exc

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

        transcript.full_text = transcript_text
        # TODO: store real ASR confidence once WhisperX/Kaggle return one; the clip-level
        # emotion score used to be stored here, which is not a transcript confidence.
        transcript.overall_confidence = None
        session.add(transcript)
        await session.flush()

        utterances: list[Utterance] = []
        for index, (segment, speaker_role) in enumerate(zip(segments, speaker_roles)):
            emotion_scores = segment.get("emotion_scores") or []
            emotion_confidence = float(emotion_scores[0].get("score") or 0.0) if emotion_scores else None

            utterance = Utterance(
                interaction_id=interaction_id,
                transcript_id=transcript.id,
                speaker_role=speaker_role,
                user_id=interaction.agent_id if speaker_role == SpeakerRole.agent else None,
                sequence_index=index,
                start_time_seconds=float(segment.get("start") or 0.0),
                end_time_seconds=float(segment.get("end") or 0.0),
                text=(segment.get("text") or "").strip(),
                emotion=(segment.get("emotion") or "unknown").strip() or "unknown",
                emotion_confidence=emotion_confidence,
            )
            utterances.append(utterance)
            session.add(utterance)

        await session.flush()

        previous_emotion: str | None = None
        for utterance in utterances:
            current_emotion = utterance.emotion
            if current_emotion == "unknown":
                continue
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

        interaction.language_detected = (analysis.get("language") or interaction.language_detected or "en")[:10]
        interaction.duration_seconds = int(max((float(seg.get("end") or 0.0) for seg in segments), default=interaction.duration_seconds or 0))
        session.add(interaction)
        for stage in audio_stages:
            await _set_job_status(session, interaction_id, stage, JobStatus.completed)
        await _set_job_status(session, interaction_id, JobStage.reasoning, JobStatus.running)
        await session.commit()

        organization = (
            await session.exec(select(Organization).where(Organization.id == interaction.organization_id))
        ).first()
        if not organization:
            raise StageFailed((JobStage.reasoning,), "Organization not found for interaction.")
        timeout = float(os.getenv("LLM_TRIGGER_EVAL_TIMEOUT_SECONDS", "600"))
        try:
            report = await asyncio.wait_for(
                evaluate_interaction_triggers(
                    session=session,
                    interaction_id=interaction_id,
                    org_filter=organization.slug,
                    requester_organization_id=interaction.organization_id,
                    force_rerun=True,
                ),
                timeout=timeout,
            )
        except TimeoutError as exc:
            raise StageFailed((JobStage.reasoning,), f"LLM trigger evaluation timed out after {timeout:g}s.") from exc
        except Exception as exc:
            raise StageFailed(
                (JobStage.reasoning,), f"LLM trigger evaluation failed: {_format_processing_exception(exc)}"
            ) from exc
        await _set_job_status(session, interaction_id, JobStage.reasoning, JobStatus.completed)

        try:
            await ensure_organization_policies_from_source(session, interaction.organization_id)
            scores = compute_scores(report)
            violation_specs = derive_violation_specs(ViolationMappingInput.from_llm_trigger_report(report))
            transcript_policy_degraded = bool(
                report.nli_policy.insufficient_evidence
                or report.process_adherence.insufficient_evidence
            )
            for spec in violation_specs:
                spec.degraded = transcript_policy_degraded
            await persist_policy_violations(
                session,
                interaction_id=interaction_id,
                organization_id=interaction.organization_id,
                specs=violation_specs,
                replace_existing=False,
            )
            session.add(
                InteractionScore(
                    interaction_id=interaction_id,
                    overall_score=scores.overall,
                    empathy_score=scores.empathy,
                    policy_score=scores.policy,
                    resolution_score=scores.resolution,
                    # TODO: compute silence / agent response time from utterance timestamps.
                    total_silence_seconds=None,
                    avg_response_time_seconds=None,
                    was_resolved=scores.was_resolved,
                )
            )
        except Exception as exc:
            raise StageFailed(
                (JobStage.scoring,), f"Scoring failed: {_format_processing_exception(exc)}"
            ) from exc

        for stage in (JobStage.scoring, JobStage.rag_eval):
            await _set_job_status(session, interaction_id, stage, JobStatus.completed)
        interaction.processing_status = ProcessingStatus.completed
        session.add(interaction)
        await session.commit()

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


async def mark_interaction_failed(
    interaction_id: UUID,
    error_message: str,
    failed_stages: tuple[JobStage, ...] = STAGE_ORDER,
) -> None:
    """Mark ``failed_stages`` failed with ``error_message``; other unfinished stages fail as not run."""
    failed_names = ", ".join(stage.value for stage in failed_stages)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        try:
            interaction = await session.get(Interaction, interaction_id)
            if interaction:
                interaction.processing_status = ProcessingStatus.failed
                session.add(interaction)

            jobs_result = await session.exec(
                select(ProcessingJob).where(ProcessingJob.interaction_id == interaction_id)
            )
            completed = {job.stage for job in jobs_result.all() if job.status == JobStatus.completed}
            for stage in STAGE_ORDER:
                if stage in failed_stages:
                    message = error_message
                elif stage in completed:
                    continue
                else:
                    message = f"Not run: {failed_names} stage failed."
                await _set_job_status(session, interaction_id, stage, JobStatus.failed, message)
            await session.commit()
        except Exception:
            await session.rollback()
            raise
