# Audio Auto-Ingest Watcher

Implementation: `backend/app/core/audio_folder_watcher.py`. It is started from the backend lifespan in `backend/app/main.py`.

## Enabling

| Source | `AUDIO_FOLDER_WATCHER_ENABLED` |
|---|---|
| `Settings` default (`backend/app/core/config.py`) | `False` |
| `backend/.env.example` and root `.env.example` | `true` |

When the variable is unset, the watcher is off. Copying either example env file turns it on, and compose loads both files into the backend. Set it to `false` to stop scanning.

## Behaviour

- Every 15 s (`SCAN_INTERVAL_SECONDS`), it scans `storage/audio/<org_slug>/*.wav` and `*.mp3` for every organization. The root is the first of these that exists: `storage/audio`, then `<repo>/storage/audio`, then `/app/storage/audio`.
- Orgs with no active agent users are skipped.
- It skips any file whose `interactions.audio_file_path` already exists for that org. The stored path is `../storage/audio/<org_slug>/<file>`, the same form the seed scripts write, so seeded calls are not ingested twice.
- For each new file it creates an `Interaction` (`processing_status=pending`, `uploaded_by` = the org's first manager, or the first agent if there is no manager), an empty `Transcript`, and the processing jobs. It then calls `enqueue_interaction_processing()` (in-process queue; see [ADR-002](../ADR-002-job-queue.md)).
- Files that resolve outside the org directory (e.g. through symlinks) are skipped with a warning.

## Agent assignment

- The filename must match `^CALL_\d{2}_<agent>_`, e.g. `CALL_03_priya_billing_issue.wav`. The `<agent>` token is lowercased and matched against the lowercased `name` of the org's active agents.
- When there is no match, the call goes to a fallback agent, `agents[hash(filename) % len(agents)]`, and a warning is logged. Python string hashing is randomized per process, so the fallback agent can change between backend restarts.

## Related settings

- `EXTRA_AUDIO_ROOTS` (`;`-separated absolute paths) adds trusted roots for *resolving* stored audio paths during processing (`backend/app/core/audio_resolver.py`). The watcher does not scan these roots.
- Manual alternative: **Upload audio** in the Session Inspector (`POST /api/v1/interactions`).
- `infra/scripts/ingest_audio_folder.py` is a separate CLI ingester for one-off batches.
