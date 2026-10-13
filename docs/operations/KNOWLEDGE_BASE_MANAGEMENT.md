# Knowledge Base Management

Policies, SOPs, and KB articles exist in two places that are maintained separately:

| Store | Written by | Read by |
|---|---|---|
| Qdrant (`vocalmind_parents`, `vocalmind_children`, `vocalmind_sop_parents`) | `services/rag` ingestion of PDFs under `storage/docs/{org_slug}/` | LLM trigger retrieval (SOP and policy context, claim cards) |
| PostgreSQL (`company_policies` + `organization_policies`, `faq_articles` + `organization_faq_articles`, `knowledge_versions`) | Knowledge Base UI → `/api/v1/knowledge/*` (`backend/app/api/routes/knowledge.py`) | Policy fallback when Qdrant returns nothing, policy-violation mapping, knowledge versions |

SOPs and KB articles are both `faq_articles`; KB rows have a `kb:` category prefix.

## Adding documents

**PDF folders** (picked up by the ingestion container's watch loop, default every 60 s, or `cd services/rag && uv run python main.py --ingest`):

| Folder | Indexed as |
|---|---|
| `storage/docs/{org_slug}/policy-docs/` | `policy` |
| `storage/docs/{org_slug}/sop-procedures/` | `sop` |
| `storage/docs/{org_slug}/knowledge-base/` | `kb` |

Only `.pdf` files are ingested. The folder name must equal the organization slug. Details: [INGESTION_PIPELINE.md](../rag/INGESTION_PIPELINE.md).

**UI uploads** (`POST /knowledge/policies/upload`, `/knowledge/faqs/upload`, `/knowledge/kb/upload` and the `PATCH …/{id}/upload` replacements) store the PDF as `{id}.pdf` in the matching folder above (roots `POLICY_DOCS_ROOT` / `KNOWLEDGE_DOCS_ROOT`) and save its text (pypdf) in the DB row, so it reaches Qdrant on the next ingestion pass. Text-only creates (`POST /knowledge/policies`, `POST /knowledge/faqs`) and `PATCH` text edits update the DB only.

**Toggle** (`POST …/{id}/toggle`) flips the org link's `is_active`. **Delete** removes the org link, and the row plus its PDF when no other org links it. Neither changes Qdrant: ingestion never removes points for deleted PDFs, and retrieval does not consult DB flags. To purge a document from retrieval, delete the PDF and run `main.py --ingest --force`.

## Knowledge versioning

Implementation: `backend/app/core/knowledge_versioning.py`; model `KnowledgeVersion` (`knowledge_versions` table, Alembic `20260623_1200_a1b2c3d4e5f6`); UI `frontend/src/app/components/manager/KnowledgeVersions.tsx`.

- A version is an immutable JSON snapshot of the org's **owned** policies and FAQ/KB rows (content + `is_active`) and its link rows. Exactly one version per org is active.
- Every mutating knowledge endpoint calls `create_version` after committing (`version_number = max + 1`, previous active demoted).
- `ensure_baseline_version` lazily creates v1 ("Initial knowledge baseline") the first time an org's active version is requested.
- Each LLM trigger cache row is tagged with the active version number (`interaction_llm_trigger_cache.knowledge_version`). Editing knowledge does not invalidate cached analyses; interaction detail responses include `knowledgeVersion`, `activeKnowledgeVersion`, and `isStale` (`tag < active`).

Endpoints (manager role; others 403):

| Method | Path | Behaviour |
|---|---|---|
| GET | `/api/v1/knowledge/versions` | All versions, newest first: `id`, `versionNumber`, `summary`, `createdBy`, `createdAt`, `isActive`, `isLatest` |
| GET | `/api/v1/knowledge/versions/active` | The active version |
| POST | `/api/v1/knowledge/versions/{id}/activate` | `activate_version`: restore the snapshot into the live tables (upsert owned rows, delete owned rows not in the snapshot, restore link flags) and make it active. Rows owned by another org keep their content; only this org's link flags are restored. Existing analyses keep their tags. |
| POST | `/api/v1/knowledge/versions/reprocess` | Body: `interaction_ids` or `scope: "stale"`, and `target` |

Reprocess targets:

- `target: "active"` (default): `reset_interaction_for_reprocess` + enqueue the full pipeline for each interaction; results are tagged with the active version.
- `target: "original"`: for each interaction with a tag, rebuild grounding from that version's snapshot (`snapshot_to_grounding`: active policy texts → `ground_truth_policy`, active FAQ/KB answers → SOP override), re-run `evaluate_interaction_triggers` with those overrides, and persist the cache with the original tag. Only the trigger report is recomputed; scores and violations are not.
- `scope: "stale"` selects cached interactions whose tag is below the active version. No targets → 422.

## Troubleshooting

- **Empty retrieval**: the `storage/docs/` folder name must match `organizations.slug`; check Qdrant points for that `org`.
- **Ingestion cannot connect**: Qdrant `:6333` must be reachable, plus the embedding host: the Kaggle server at `KAGGLE_SERVER_URL` (`RAG_MODELS_HOST=kaggle`) or Ollama `:11434` with `make ollama-pull-embed` (`local`).
- **Dimension mismatch or poor retrieval** after changing `EMBEDDING_MODEL` or `RAG_MODELS_HOST`: run `main.py --ingest --force`.

## Known issues

- The policy/FAQ/KB CRUD endpoints (everything except `/versions*`) check only authentication, not the manager role.
- A disabled or deleted policy can still be retrieved from Qdrant and used as NLI policy context.
