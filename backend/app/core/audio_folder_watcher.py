"""
Audio folder auto-ingest watcher.

Periodically scans `storage/audio/<org_slug>/` directories for audio files that
are not yet recorded as interactions, and:
  1) creates an Interaction row with status=pending,
  2) seeds processing jobs,
  3) enqueues the interaction for the existing in-memory processing worker.

Filename convention used to assign the agent:
  CALL_<NN>_<agent_lowercase>_<scenario>.<ext>

Examples:
  CALL_01_priya_refund_outage.wav      → assigned to user named "Priya"
  CALL_02_daniel_billing_dispute.wav   → assigned to user named "Daniel"

If the filename does not match the convention, the file is assigned to a
deterministic fallback agent for that org so processing still proceeds.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.database import engine
from app.core.inference_contracts import is_supported_audio_filename
from app.core.interaction_processing import (
    create_processing_jobs,
    enqueue_interaction_processing,
)
from app.models.enums import ProcessingStatus, UserRole
from app.models.interaction import Interaction
from app.models.organization import Organization
from app.models.transcript import Transcript
from app.models.user import User as UserModel


logger = logging.getLogger(__name__)


# How often to rescan for new audio files. The watcher is idempotent so a
# moderate interval (every 15s) is plenty for development and demo use.
SCAN_INTERVAL_SECONDS = 15

# CALL_<NN>_<agent>_<scenario>.<ext>
_AUDIO_FILENAME_AGENT_PATTERN = re.compile(r"^CALL_\d{2}_(?P<agent>[a-zA-Z]+)_")


def _extract_agent_token(filename: str) -> str | None:
    match = _AUDIO_FILENAME_AGENT_PATTERN.match(Path(filename).name)
    if not match:
        return None
    return match.group("agent").lower()


def _audio_root() -> Path:
    """Resolve the storage/audio root regardless of cwd."""
    candidates = [
        Path("storage/audio"),
        Path(__file__).resolve().parents[3] / "storage" / "audio",
        Path("/app/storage/audio"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _build_audio_path_record(org_slug: str, file_path: Path) -> str:
    """
    Build the value stored in interactions.audio_file_path so it matches what
    `seed_nexalink.seed_interactions` writes for the same files: a path relative
    to the backend working directory.
    """
    return str(Path("..") / "storage" / "audio" / org_slug / file_path.name)


async def _scan_organization_folder(
    session: AsyncSession,
    org: Organization,
) -> list[UUID]:
    org_dir = _audio_root() / org.slug
    if not org_dir.exists() or not org_dir.is_dir():
        return []

    candidate_files = sorted(
        path
        for ext in ("*.wav", "*.mp3")
        for path in org_dir.glob(ext)
        if is_supported_audio_filename(path.name)
    )
    if not candidate_files:
        return []

    agents_result = await session.exec(
        select(UserModel).where(
            UserModel.organization_id == org.id,
            UserModel.role == UserRole.agent,
            UserModel.is_active == True,  # noqa: E712
        )
    )
    agents = list(agents_result.all())
    if not agents:
        logger.debug("No active agents for org %s, skipping audio scan", org.slug)
        return []

    agent_by_token = {agent.name.lower(): agent for agent in agents}

    manager_result = await session.exec(
        select(UserModel).where(
            UserModel.organization_id == org.id,
            UserModel.role == UserRole.manager,
        )
    )
    manager = manager_result.first()
    uploader_id = manager.id if manager else agents[0].id

    enqueued_ids: list[UUID] = []
    for path in candidate_files:
        audio_file_path = _build_audio_path_record(org.slug, path)

        existing_result = await session.exec(
            select(Interaction.id).where(
                Interaction.organization_id == org.id,
                Interaction.audio_file_path == audio_file_path,
            )
        )
        if existing_result.first() is not None:
            continue

        token = _extract_agent_token(path.name)
        agent = agent_by_token.get(token) if token else None
        if agent is None:
            agent = agents[hash(path.name) % len(agents)]
            logger.warning(
                "Audio file %s did not match the CALL_<NN>_<agent>_... pattern; "
                "falling back to deterministic agent %s",
                path.name,
                agent.name,
            )

        interaction = Interaction(
            organization_id=org.id,
            agent_id=agent.id,
            uploaded_by=uploader_id,
            audio_file_path=audio_file_path,
            file_size_bytes=path.stat().st_size,
            duration_seconds=0,
            file_format=path.suffix.lstrip(".").lower() or "wav",
            interaction_date=datetime.now(timezone.utc).replace(tzinfo=None),
            processing_status=ProcessingStatus.pending,
            language_detected=None,
            has_overlap=False,
            channel_count=1,
        )
        session.add(interaction)
        await session.flush()

        session.add(Transcript(interaction_id=interaction.id, full_text="", overall_confidence=None))
        await create_processing_jobs(session, interaction.id)
        await session.commit()
        await session.refresh(interaction)

        await enqueue_interaction_processing(interaction.id)
        enqueued_ids.append(interaction.id)
        logger.info(
            "Auto-ingest queued %s for org=%s agent=%s interaction_id=%s",
            path.name,
            org.slug,
            agent.name,
            interaction.id,
        )

    return enqueued_ids


async def scan_audio_folders_once() -> int:
    """Scan all org folders once. Returns the number of new interactions queued."""
    total = 0
    async with AsyncSession(engine, expire_on_commit=False) as session:
        orgs_result = await session.exec(select(Organization))
        for org in orgs_result.all():
            try:
                queued = await _scan_organization_folder(session, org)
                total += len(queued)
            except Exception:
                logger.exception("Audio folder scan failed for org=%s", org.slug)
    return total


_watcher_task: asyncio.Task | None = None
_watcher_stop = asyncio.Event()


async def _watcher_loop() -> None:
    while not _watcher_stop.is_set():
        try:
            queued = await scan_audio_folders_once()
            if queued:
                logger.info("Audio folder watcher queued %d new interaction(s)", queued)
        except Exception:
            logger.exception("Audio folder watcher iteration failed")
        try:
            await asyncio.wait_for(_watcher_stop.wait(), timeout=SCAN_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            continue


async def start_audio_folder_watcher() -> None:
    global _watcher_task
    if _watcher_task and not _watcher_task.done():
        return
    if not getattr(settings, "AUDIO_FOLDER_WATCHER_ENABLED", True):
        logger.info("Audio folder watcher disabled via settings")
        return
    _watcher_stop.clear()
    _watcher_task = asyncio.create_task(_watcher_loop(), name="audio-folder-watcher")
    logger.info("Audio folder watcher started (interval=%ds)", SCAN_INTERVAL_SECONDS)


async def stop_audio_folder_watcher() -> None:
    global _watcher_task
    _watcher_stop.set()
    if _watcher_task is None:
        return
    try:
        await asyncio.wait_for(_watcher_task, timeout=SCAN_INTERVAL_SECONDS + 5)
    except asyncio.TimeoutError:
        _watcher_task.cancel()
    except asyncio.CancelledError:
        pass
    finally:
        _watcher_task = None
