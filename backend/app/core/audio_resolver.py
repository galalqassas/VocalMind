from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import httpx

from app.core.config import settings

_AUDIO_CONTENT_TYPES = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "flac": "audio/flac",
    "m4a": "audio/mp4",
}


def audio_media_type_from_path(audio_path: str) -> str:
    ext = audio_path.rsplit(".", 1)[-1].lower() if "." in audio_path else "wav"
    return _AUDIO_CONTENT_TYPES.get(ext, "audio/wav")


def audio_filename_from_path(audio_path: str) -> str:
    name = Path(audio_path).name.strip()
    return name or "audio.wav"


def _fixture_search_roots() -> list[Path]:
    """Repo roots that contain NexaLink WAV fixtures (works in Docker and native dev)."""
    here = Path(__file__).resolve()
    roots: list[Path] = []
    seen: set[Path] = set()
    for ancestor in here.parents:
        nexalink = ancestor / "storage" / "audio" / "nexalink"
        if nexalink.is_dir():
            try:
                resolved = ancestor.resolve()
            except (ValueError, OSError):
                continue
            if resolved not in seen:
                roots.append(resolved)
                seen.add(resolved)
    if roots:
        return roots
    return [here.parents[2]]


def _best_audio_file(candidates: list[Path]) -> Path | None:
    files = [path for path in candidates if path.is_file()]
    if not files:
        return None
    unique = list({path.resolve(): path for path in files}.values())
    return max(unique, key=lambda path: path.stat().st_size)


def resolve_telecom_fixture_path(audio_path: str) -> Path | None:
    """Map Supabase dataset object paths to checked-in NexaLink WAV fixtures."""
    if not audio_path or "\x00" in audio_path:
        return None

    filename = Path(audio_path.replace("\\", "/")).name
    if not filename.lower().endswith((".wav", ".mp3", ".ogg", ".flac", ".m4a")):
        return None

    search_roots: list[Path] = []
    for repo_root in _fixture_search_roots():
        search_roots.extend(
            [
                repo_root / "storage" / "audio" / "nexalink",
                repo_root / "audio_import" / "audio" / "nexalink",
                repo_root / "audio_import",
            ]
        )

    import os as _os

    extras_env = (settings.EXTRA_AUDIO_ROOTS or "").strip() or _os.getenv("EXTRA_AUDIO_ROOTS", "").strip()
    if extras_env:
        for raw in extras_env.replace(";", _os.pathsep).split(_os.pathsep):
            raw = raw.strip()
            if not raw:
                continue
            try:
                search_roots.append(Path(raw).resolve())
            except (ValueError, OSError):
                continue

    matches: list[Path] = []
    seen_roots: set[Path] = set()
    for root in search_roots:
        if not root.is_dir():
            continue
        try:
            resolved_root = root.resolve()
        except (ValueError, OSError):
            continue
        if resolved_root in seen_roots:
            continue
        seen_roots.add(resolved_root)

        direct = resolved_root / filename
        if direct.is_file():
            matches.append(direct)
        matches.extend(path for path in sorted(resolved_root.glob(f"**/{filename}")) if path.is_file())

    return _best_audio_file(matches)


def resolve_local_audio_path(audio_path: str) -> Path | None:
    import os as _os

    if not audio_path or "\0" in audio_path or "\x00" in audio_path:
        return None

    path_obj = Path(audio_path)
    if path_obj.is_absolute():
        try:
            resolved = path_obj.resolve(strict=False)
        except (ValueError, OSError):
            return None
        if resolved.exists() and resolved.is_file():
            return resolved
        return None

    # Normalize forward/backslash mix so Windows-built records still match.
    audio_path_norm = audio_path.replace("\\", "/")
    backend_dir = Path(__file__).resolve().parents[2]
    storage_root = Path(settings.LOCAL_AUDIO_STORAGE_DIR).resolve()
    audio_root = (storage_root.parent / "audio").resolve()
    candidates = [Path(audio_path_norm), backend_dir / audio_path_norm]
    if audio_path_norm.startswith("../storage/"):
        candidates.append(storage_root.parent / audio_path_norm[len("../storage/"):])
    allowed_roots = [
        storage_root,
        audio_root,
        (backend_dir / settings.LOCAL_AUDIO_STORAGE_DIR).resolve(),
        (backend_dir / ".." / "storage" / "audio").resolve(),
    ]
    # EXTRA_AUDIO_ROOTS: ';' or os.pathsep separated absolute paths that should
    # also be treated as trusted audio roots (e.g. when running natively against
    # a worktree but with audio mounted from another checkout). Each extra root
    # is also tried as a candidate base by stripping the leading "../storage/audio/"
    # so a relative path like "../storage/audio/nexalink/X.wav" can resolve under
    # a different concrete storage tree.
    extras_env = (settings.EXTRA_AUDIO_ROOTS or "").strip() or _os.getenv("EXTRA_AUDIO_ROOTS", "").strip()
    if extras_env:
        for raw in extras_env.replace(";", _os.pathsep).split(_os.pathsep):
            raw = raw.strip()
            if not raw:
                continue
            try:
                extra_root = Path(raw).resolve()
            except (ValueError, OSError):
                continue
            allowed_roots.append(extra_root)
            for prefix in ("../storage/audio/", "../storage/"):
                if audio_path_norm.startswith(prefix):
                    suffix = audio_path_norm[len(prefix):]
                    # strip a leading "audio/" so "extra_root/audio/<org>/file" doesn't double up
                    if prefix == "../storage/" and suffix.startswith("audio/"):
                        suffix = suffix[len("audio/"):]
                    candidates.append(extra_root / suffix)
                    break
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=False)
        except (ValueError, OSError):
            continue
        if not any(resolved.is_relative_to(root) for root in allowed_roots):
            continue
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


def _storage_url_for_path(audio_path: str) -> str:
    return f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/object/{quote(audio_path, safe='/')}"


async def fetch_supabase_audio(audio_path: str, timeout_seconds: float = 60.0) -> bytes:
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY:
        raise FileNotFoundError("Supabase storage is not configured")

    storage_url = _storage_url_for_path(audio_path)
    async with httpx.AsyncClient() as client:
        response = await client.get(
            storage_url,
            headers={
                "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
                "apikey": settings.SUPABASE_SERVICE_KEY,
            },
            timeout=timeout_seconds,
        )

    if response.status_code != 200:
        raise FileNotFoundError(f"Supabase object not found: {audio_path}")

    return response.content


async def supabase_object_exists(audio_path: str, timeout_seconds: float = 10.0) -> bool:
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY:
        return False

    storage_url = _storage_url_for_path(audio_path)
    headers = {
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
        "apikey": settings.SUPABASE_SERVICE_KEY,
    }
    async with httpx.AsyncClient() as client:
        response = await client.head(storage_url, headers=headers, timeout=timeout_seconds)
        if response.status_code == 200:
            return True
        if response.status_code not in {404, 405}:
            return False
        # Some storage gateways disable HEAD. Fall back to a 1-byte range GET.
        response = await client.get(
            storage_url,
            headers={**headers, "Range": "bytes=0-0"},
            timeout=timeout_seconds,
        )
    return response.status_code in {200, 206}


async def fetch_audio_bytes(audio_path: str, timeout_seconds: float = 60.0) -> tuple[bytes, str]:
    if "\x00" in audio_path:
        raise FileNotFoundError(f"Invalid audio path: {audio_path!r}")
    local_path = resolve_local_audio_path(audio_path) or resolve_telecom_fixture_path(audio_path)
    if local_path:
        return local_path.read_bytes(), local_path.name

    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY:
        raise FileNotFoundError(
            f"Audio file not found locally and Supabase storage is not configured: {audio_path!r}. "
            f"Checked LOCAL_AUDIO_STORAGE_DIR and EXTRA_AUDIO_ROOTS — verify the file exists "
            f"or configure SUPABASE_URL/SUPABASE_SERVICE_KEY."
        )

    return await fetch_supabase_audio(audio_path, timeout_seconds=timeout_seconds), audio_filename_from_path(audio_path)
